"""The audit log (card M3-07), and what the API's database login may do.

The API connects as a member of the capybara_app role (infra/postgres/init). This migration
creates that role if needed and grants it reading and writing on the data tables, but only
SELECT and INSERT on audit_events and nothing on alembic_version. Tables created later by the
migration owner get the same default rights. Not being a superuser or an owner, the app cannot
disable triggers, change functions or alter tables, so it cannot edit or erase the log.

The app cannot create temporary tables either: one named audit_events would otherwise shadow
the real table on its connection and silently swallow later events. Downgrading refuses while
the log holds events (override: -x allow_audit_loss=1).

Triggers on audit_events add a second layer that also stops the owner by accident: UPDATE,
DELETE and TRUNCATE are refused, and `at` is always the real insert time (clock_timestamp()),
whatever the client sends.

Revision ID: 0004
Revises: 0003
Created: 2026-11-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "audit_events",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("type", sa.String(length=40), nullable=False),
        sa.Column(
            "at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("request_id", sa.String(length=128), nullable=True),
        sa.Column("user_id", sa.String(length=255), nullable=False),
        sa.Column("user_department", sa.String(length=50), nullable=False),
        sa.Column(
            "user_role",
            sa.Enum(
                "member",
                "manager",
                "owner",
                name="user_role",
                native_enum=False,
                create_constraint=True,
                length=20,
            ),
            nullable=False,
        ),
        sa.Column("user_is_admin", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("question", sa.Text(), nullable=True),
        sa.Column(
            "pools_searched",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "pools_denied",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "pools_used",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "chunks_retrieved",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "chunks_cited",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "grant_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "departments",
            postgresql.ARRAY(sa.String(length=50)),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column(
            "detail",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "type IN ('chat', 'grant_created', 'grant_revoked', 'access_request_created', "
            "'access_request_approved', 'access_request_denied', 'access_request_expired')",
            name=op.f("ck_audit_events_type"),
        ),
        sa.CheckConstraint("length(user_id) > 0", name=op.f("ck_audit_events_user_id_not_empty")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_events")),
    )
    op.create_index("ix_audit_events_at", "audit_events", ["at"], unique=False)
    op.create_index(
        "ix_audit_events_departments",
        "audit_events",
        ["departments"],
        unique=False,
        postgresql_using="gin",
    )
    op.create_index("ix_audit_events_user_id_at", "audit_events", ["user_id", "at"], unique=False)

    op.execute(
        """
        CREATE FUNCTION audit_events_append_only() RETURNS trigger LANGUAGE plpgsql
            SET search_path = pg_catalog, public, pg_temp AS $$
        BEGIN
            RAISE EXCEPTION 'audit_events is append-only: % is not allowed', TG_OP
                USING ERRCODE = 'insufficient_privilege';
        END $$
        """
    )
    op.execute(
        "CREATE TRIGGER audit_events_no_update_or_delete BEFORE UPDATE OR DELETE ON audit_events "
        "FOR EACH ROW EXECUTE FUNCTION audit_events_append_only()"
    )
    op.execute(
        "CREATE TRIGGER audit_events_no_truncate BEFORE TRUNCATE ON audit_events "
        "FOR EACH STATEMENT EXECUTE FUNCTION audit_events_append_only()"
    )

    op.execute(
        """
        CREATE FUNCTION audit_events_stamp_time() RETURNS trigger LANGUAGE plpgsql
            SET search_path = pg_catalog, public, pg_temp AS $$
        BEGIN
            -- Qualified, and a fixed search_path above: a clock_timestamp() of the caller's own
            -- earlier on their search_path must not be able to choose the time.
            NEW.at := pg_catalog.clock_timestamp();
            RETURN NEW;
        END $$
        """
    )
    op.execute(
        "CREATE TRIGGER audit_events_stamp_time BEFORE INSERT ON audit_events "
        "FOR EACH ROW EXECUTE FUNCTION audit_events_stamp_time()"
    )

    # The API's rights (see the docstring). The role is shared by the whole server, so
    # downgrade only revokes; it never drops it.
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'capybara_app') THEN
                CREATE ROLE capybara_app NOLOGIN;
            END IF;
        END $$
        """
    )
    op.execute("GRANT USAGE ON SCHEMA public TO capybara_app")
    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO capybara_app"
    )
    op.execute("REVOKE ALL ON alembic_version FROM capybara_app")
    op.execute("REVOKE UPDATE, DELETE, TRUNCATE ON audit_events FROM capybara_app")
    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO capybara_app"
    )
    # Tables with serial/identity ids need their sequences too.
    op.execute("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO capybara_app")
    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO capybara_app"
    )
    # Temporary tables are searched before `public`, so a temp table named audit_events would
    # silently swallow every later event on that pooled connection. Only the owner may create
    # temporary tables in this database.
    op.execute(
        "DO $$ BEGIN EXECUTE 'REVOKE TEMPORARY ON DATABASE ' || quote_ident(current_database())"
        " || ' FROM PUBLIC'; END $$"
    )
    # PostgreSQL 15+ already denies this; clusters created on 14 or older (or upgraded from
    # one) still let everyone create objects in public, e.g. a function that shadows a
    # built-in. Revoked here so every cluster matches what check_app_login expects. Not
    # restored on downgrade: no supported version needs it.
    op.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")


def downgrade() -> None:
    # Dropping audit_events deletes the audit trail. Refuse while it holds events, unless asked
    # explicitly: alembic -x allow_audit_loss=1 downgrade ...
    allowed = context.get_x_argument(as_dictionary=True).get("allow_audit_loss") == "1"
    # Lock first, so an event being written right now is either counted or blocked until the
    # table is gone, never committed into a table that is about to be dropped.
    op.execute("LOCK TABLE audit_events IN ACCESS EXCLUSIVE MODE")
    if context.is_offline_mode():
        if not allowed:  # the printed SQL refuses for itself when it is run
            op.execute(
                "DO $$ BEGIN IF EXISTS (SELECT FROM audit_events) THEN RAISE EXCEPTION "
                "'audit_events holds events; downgrading would delete them'; END IF; END $$"
            )
    else:
        rows = op.get_bind().scalar(sa.text("SELECT count(*) FROM audit_events"))
        if rows and not allowed:
            raise RuntimeError(
                f"audit_events holds {rows} events and downgrading would delete them. "
                "Run with -x allow_audit_loss=1 to do it anyway."
            )
    op.execute(
        "DO $$ BEGIN EXECUTE 'GRANT TEMPORARY ON DATABASE ' || quote_ident(current_database())"
        " || ' TO PUBLIC'; END $$"
    )
    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        "REVOKE USAGE, SELECT ON SEQUENCES FROM capybara_app"
    )
    op.execute("REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM capybara_app")
    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        "REVOKE SELECT, INSERT, UPDATE, DELETE ON TABLES FROM capybara_app"
    )
    op.execute("REVOKE ALL ON ALL TABLES IN SCHEMA public FROM capybara_app")
    op.execute("REVOKE USAGE ON SCHEMA public FROM capybara_app")
    op.execute("DROP TRIGGER audit_events_stamp_time ON audit_events")
    op.execute("DROP TRIGGER audit_events_no_truncate ON audit_events")
    op.execute("DROP TRIGGER audit_events_no_update_or_delete ON audit_events")
    op.drop_index("ix_audit_events_user_id_at", table_name="audit_events")
    op.drop_index("ix_audit_events_departments", table_name="audit_events", postgresql_using="gin")
    op.drop_index("ix_audit_events_at", table_name="audit_events")
    op.drop_table("audit_events")
    op.execute("DROP FUNCTION audit_events_append_only()")
    op.execute("DROP FUNCTION audit_events_stamp_time()")
