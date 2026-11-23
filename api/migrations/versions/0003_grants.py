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
            "grantee_user_id IS NULL OR length(btrim(grantee_user_id)) > 0",
            name=op.f("ck_grants_user_id_not_empty"),
        ),
        sa.CheckConstraint(
            "length(btrim(created_by)) > 0", name=op.f("ck_grants_created_by_not_empty")
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
        op.f("ck_departments_id_is_slug"), "departments", "id ~ '^[a-z0-9][a-z0-9-]*$'"
    )

    op.execute(
        """
        CREATE FUNCTION grants_only_revoke() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'grants are never deleted; revoke instead'
                    USING ERRCODE = 'check_violation';
            END IF;
            IF OLD.revoked_at IS NOT NULL THEN
                RAISE EXCEPTION 'grant % is already revoked', OLD.id
                    USING ERRCODE = 'check_violation';
            END IF;
            IF NEW.revoked_at IS NULL
               OR (NEW.id, NEW.owning_department, NEW.grantee_department, NEW.grantee_min_role,
                   NEW.grantee_user_id, NEW.source_type, NEW.max_sensitivity, NEW.expires_at,
                   NEW.created_by, NEW.created_at)
                  IS DISTINCT FROM
                  (OLD.id, OLD.owning_department, OLD.grantee_department, OLD.grantee_min_role,
                   OLD.grantee_user_id, OLD.source_type, OLD.max_sensitivity, OLD.expires_at,
                   OLD.created_by, OLD.created_at)
            THEN
                RAISE EXCEPTION 'a grant can only be revoked, never changed'
                    USING ERRCODE = 'check_violation';
            END IF;
            -- An app clock slightly behind the database must not make a revoke fail.
            NEW.revoked_at := GREATEST(NEW.revoked_at, OLD.created_at);
            RETURN NEW;
        END $$
        """
    )
    op.execute(
        "CREATE TRIGGER grants_only_revoke BEFORE UPDATE OR DELETE ON grants "
        "FOR EACH ROW EXECUTE FUNCTION grants_only_revoke()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER grants_only_revoke ON grants")
    op.execute("DROP FUNCTION grants_only_revoke()")
    op.drop_constraint(op.f("ck_departments_id_is_slug"), "departments", type_="check")
    op.drop_index("ix_grants_active_grantee", table_name="grants")
    op.drop_index(op.f("ix_grants_owning_department"), table_name="grants")
    op.drop_table("grants")
