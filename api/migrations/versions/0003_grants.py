"""The grants table (card M2-02): who may read which slice of a department's data.

CHECK constraints make a malformed grant impossible: exactly one kind of grantee (department +
minimum role, or one named user), never public, and restricted grants must expire. A trigger
makes grants immutable: the only update allowed is revoking once, and rows are never deleted.

Revision ID: 0003
Revises: 0002
Created: 2026-11-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "grants",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("owning_department", sa.String(length=50), nullable=False),
        sa.Column("grantee_department", sa.String(length=50), nullable=True),
        sa.Column(
            "grantee_min_role",
            sa.Enum(
                "member",
                "manager",
                "owner",
                name="grantee_min_role",
                native_enum=False,
                create_constraint=True,
                length=20,
            ),
            nullable=True,
        ),
        sa.Column("grantee_user_id", sa.String(length=255), nullable=True),
        sa.Column(
            "source_type",
            sa.Enum(
                "docs",
                "tickets",
                "discord",
                name="source_type",
                native_enum=False,
                create_constraint=True,
                length=20,
            ),
            nullable=True,
        ),
        sa.Column(
            "max_sensitivity",
            sa.Enum(
                "public",
                "internal",
                "restricted",
                name="max_sensitivity",
                native_enum=False,
                create_constraint=True,
                length=20,
            ),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("max_sensitivity <> 'public'", name=op.f("ck_grants_not_public")),
        sa.CheckConstraint(
            "max_sensitivity <> 'restricted' OR expires_at IS NOT NULL",
            name=op.f("ck_grants_restricted_expires"),
        ),
        sa.CheckConstraint(
            "(grantee_user_id IS NULL) <> (grantee_min_role IS NULL)",
            name=op.f("ck_grants_one_grantee_kind"),
        ),
        sa.CheckConstraint(
            "expires_at IS NULL OR expires_at > created_at",
            name=op.f("ck_grants_expires_after_created"),
        ),
        sa.CheckConstraint(
            "grantee_user_id IS NULL OR grantee_department IS NULL",
            name=op.f("ck_grants_user_grant_has_no_department"),
        ),
        sa.CheckConstraint(
            "revoked_at IS NULL OR revoked_at >= created_at",
            name=op.f("ck_grants_revoked_after_created"),
        ),
        sa.CheckConstraint(
            "grantee_user_id IS NULL OR grantee_user_id"
            " ~ '^[^ \\t\\n\\r\\f\\v](.*[^ \\t\\n\\r\\f\\v])?$'",
            name=op.f("ck_grants_user_id_not_empty"),
        ),
        sa.CheckConstraint(
            "created_by ~ '^[^ \\t\\n\\r\\f\\v](.*[^ \\t\\n\\r\\f\\v])?$'",
            name=op.f("ck_grants_created_by_not_empty"),
        ),
        sa.ForeignKeyConstraint(
            ["grantee_department"],
            ["departments.id"],
            name=op.f("fk_grants_grantee_department_departments"),
        ),
        sa.ForeignKeyConstraint(
            ["owning_department"],
            ["departments.id"],
            name=op.f("fk_grants_owning_department_departments"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_grants")),
    )
    op.create_index(
        op.f("ix_grants_owning_department"), "grants", ["owning_department"], unique=False
    )
    op.create_index(
        "ix_grants_active_grantee",
        "grants",
        ["grantee_department", "grantee_user_id"],
        postgresql_where=sa.text("revoked_at IS NULL"),
    )
    # Department ids are lowercase slugs (tokens, pool names and scope fingerprints rely on it).
    op.create_check_constraint(
        op.f("ck_departments_id_is_slug"),
        "departments",
        "id ~ '^[a-z0-9][a-z0-9-]*$' AND id <> 'any'",
    )

    op.execute(
        """
        CREATE FUNCTION grants_only_revoke() RETURNS trigger LANGUAGE plpgsql
            SET search_path = pg_catalog, public AS $$
        BEGIN
            IF TG_OP IN ('DELETE', 'TRUNCATE') THEN
                RAISE EXCEPTION 'grants are never deleted; revoke instead'
                    USING ERRCODE = 'check_violation';
            END IF;
            IF OLD.revoked_at IS NOT NULL THEN
                RAISE EXCEPTION 'grant % is already revoked', OLD.id
                    USING ERRCODE = 'check_violation';
            END IF;
            -- Every column except revoked_at, including any a later migration adds.
            IF NEW.revoked_at IS NULL
               OR to_jsonb(NEW) - 'revoked_at' IS DISTINCT FROM to_jsonb(OLD) - 'revoked_at'
            THEN
                RAISE EXCEPTION 'a grant can only be revoked, never changed'
                    USING ERRCODE = 'check_violation';
            END IF;
            -- The revoke time is the database's, whatever the caller sent: never backdated,
            -- never in the future, never before creation.
            NEW.revoked_at := now();
            RETURN NEW;
        END $$
        """
    )
    op.execute(
        "CREATE TRIGGER grants_only_revoke BEFORE UPDATE OR DELETE ON grants "
        "FOR EACH ROW EXECUTE FUNCTION grants_only_revoke()"
    )
    op.execute(
        "CREATE TRIGGER grants_no_truncate BEFORE TRUNCATE ON grants "
        "FOR EACH STATEMENT EXECUTE FUNCTION grants_only_revoke()"
    )
    op.execute(
        """
        CREATE FUNCTION grants_stamp_created() RETURNS trigger LANGUAGE plpgsql
            SET search_path = pg_catalog, public AS $$
        BEGIN
            -- The database's clock, so a grant can't be backdated or start in the future.
            NEW.created_at := now();
            RETURN NEW;
        END $$
        """
    )
    op.execute(
        "CREATE TRIGGER grants_stamp_created BEFORE INSERT ON grants "
        "FOR EACH ROW EXECUTE FUNCTION grants_stamp_created()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER grants_stamp_created ON grants")
    op.execute("DROP FUNCTION grants_stamp_created()")
    op.execute("DROP TRIGGER grants_no_truncate ON grants")
    op.execute("DROP TRIGGER grants_only_revoke ON grants")
    op.execute("DROP FUNCTION grants_only_revoke()")
    op.drop_constraint(op.f("ck_departments_id_is_slug"), "departments", type_="check")
    op.drop_index("ix_grants_active_grantee", table_name="grants")
    op.drop_index(op.f("ix_grants_owning_department"), table_name="grants")
    op.drop_table("grants")
