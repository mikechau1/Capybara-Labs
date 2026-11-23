"""Tables for company data (card M2-01): departments, sources, documents, chunks, user_profiles.

Documents copy department and source type from their source, and chunks copy department,
source type and sensitivity from their document. Composite foreign keys with ON UPDATE CASCADE
keep those copies in step, so retrieval can filter on chunk columns safely. Chunks hold a
384-number embedding (card M2-03), the id of the embedder that made it, and a full-text
column PostgreSQL computes.
Every table with updated_at gets the set_updated_at trigger, so raw SQL and upserts update it.
Deleted documents are enforced too: marking one deleted removes its chunks, and a chunk cannot
be inserted into a deleted document.

Revision ID: 0002
Revises: 0001
Created: 2026-11-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TIMESTAMPED_TABLES = ["departments", "user_profiles", "sources", "documents"]


def upgrade() -> None:
    op.create_table(
        "departments",
        sa.Column("id", sa.String(length=50), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_departments")),
    )
    op.create_table(
        "user_profiles",
        sa.Column("user_id", sa.String(length=255), nullable=False),
        sa.Column("display_name", sa.String(length=200), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("user_id", name=op.f("pk_user_profiles")),
    )
    op.create_table(
        "sources",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("department_id", sa.String(length=50), nullable=False),
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
            nullable=False,
        ),
        sa.Column(
            "default_sensitivity",
            sa.Enum(
                "public",
                "internal",
                "restricted",
                name="default_sensitivity",
                native_enum=False,
                create_constraint=True,
                length=20,
            ),
            nullable=True,
        ),
        sa.Column(
            "config",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("sync_cursor", sa.Text(), nullable=True),
        sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_sync_status", sa.String(length=10), server_default="never", nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "last_sync_status IN ('never', 'ok', 'running', 'failed')",
            name=op.f("ck_sources_last_sync_status"),
        ),
        sa.ForeignKeyConstraint(
            ["department_id"], ["departments.id"], name=op.f("fk_sources_department_id_departments")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sources")),
        sa.UniqueConstraint(
            "id",
            "department_id",
            "source_type",
            name=op.f("uq_sources_id_department_id_source_type"),
        ),
        sa.UniqueConstraint("name", name=op.f("uq_sources_name")),
    )
    op.create_table(
        "documents",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("department_id", sa.String(length=50), nullable=False),
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
            nullable=False,
        ),
        sa.Column("external_id", sa.String(length=500), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("link", sa.Text(), nullable=False),
        sa.Column(
            "sensitivity",
            sa.Enum(
                "public",
                "internal",
                "restricted",
                name="sensitivity",
                native_enum=False,
                create_constraint=True,
                length=20,
            ),
            server_default="restricted",
            nullable=False,
        ),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("source_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["source_id", "department_id", "source_type"],
            ["sources.id", "sources.department_id", "sources.source_type"],
            name=op.f("fk_documents_source_id_sources"),
            onupdate="CASCADE",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_documents")),
        sa.UniqueConstraint(
            "id",
            "department_id",
            "source_type",
            "sensitivity",
            name=op.f("uq_documents_id_department_id_source_type_sensitivity"),
        ),
        sa.UniqueConstraint(
            "source_id", "external_id", name=op.f("uq_documents_source_id_external_id")
        ),
    )
    op.create_table(
        "chunks",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        # 384 is written out on purpose: a migration must not change when app code does.
        sa.Column("embedding", Vector(384), nullable=False),
        sa.Column("embedding_model", sa.String(length=100), nullable=False),
        sa.Column(
            "search",
            postgresql.TSVECTOR(),
            sa.Computed("to_tsvector('english', text)", persisted=True),
            nullable=False,
        ),
        sa.Column("department_id", sa.String(length=50), nullable=False),
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
            nullable=False,
        ),
        sa.Column(
            "sensitivity",
            sa.Enum(
                "public",
                "internal",
                "restricted",
                name="sensitivity",
                native_enum=False,
                create_constraint=True,
                length=20,
            ),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["document_id", "department_id", "source_type", "sensitivity"],
            [
                "documents.id",
                "documents.department_id",
                "documents.source_type",
                "documents.sensitivity",
            ],
            name=op.f("fk_chunks_document_id_documents"),
            onupdate="CASCADE",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_chunks")),
        sa.UniqueConstraint("document_id", "position", name=op.f("uq_chunks_document_id_position")),
    )
    op.create_index(
        "ix_chunks_access", "chunks", ["department_id", "source_type", "sensitivity"], unique=False
    )
    op.create_index("ix_chunks_search", "chunks", ["search"], unique=False, postgresql_using="gin")

    # Sets updated_at on every UPDATE, including raw SQL and INSERT ... ON CONFLICT DO UPDATE,
    # which SQLAlchemy's onupdate= does not cover.
    op.execute(
        """
        CREATE FUNCTION set_updated_at() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            -- Stamp the time unless the UPDATE set updated_at itself.
            IF NEW.updated_at IS NOT DISTINCT FROM OLD.updated_at THEN
                NEW.updated_at = now();
            END IF;
            RETURN NEW;
        END $$
        """
    )
    for table in TIMESTAMPED_TABLES:
        op.execute(
            f"CREATE TRIGGER set_updated_at BEFORE UPDATE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION set_updated_at()"
        )
    _tombstone_triggers()


def _tombstone_triggers() -> None:
    op.execute(
        """
        CREATE FUNCTION documents_delete_chunks() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            DELETE FROM chunks WHERE document_id = NEW.id;
            RETURN NEW;
        END $$
        """
    )
    op.execute(
        "CREATE TRIGGER documents_delete_chunks AFTER UPDATE OF deleted ON documents "
        "FOR EACH ROW WHEN (NEW.deleted AND NOT OLD.deleted) "
        "EXECUTE FUNCTION documents_delete_chunks()"
    )
    op.execute(
        """
        CREATE FUNCTION chunks_refuse_deleted_document() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF (SELECT deleted FROM documents WHERE id = NEW.document_id) THEN
                RAISE EXCEPTION 'document % is deleted; it cannot get chunks', NEW.document_id
                    USING ERRCODE = 'check_violation';
            END IF;
            RETURN NEW;
        END $$
        """
    )
    op.execute(
        "CREATE TRIGGER chunks_refuse_deleted_document BEFORE INSERT OR UPDATE OF document_id "
        "ON chunks FOR EACH ROW EXECUTE FUNCTION chunks_refuse_deleted_document()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER chunks_refuse_deleted_document ON chunks")
    op.execute("DROP FUNCTION chunks_refuse_deleted_document()")
    op.execute("DROP TRIGGER documents_delete_chunks ON documents")
    op.execute("DROP FUNCTION documents_delete_chunks()")
    for table in TIMESTAMPED_TABLES:
        op.execute(f"DROP TRIGGER set_updated_at ON {table}")
    op.execute("DROP FUNCTION set_updated_at()")
    op.drop_index("ix_chunks_search", table_name="chunks", postgresql_using="gin")
    op.drop_index("ix_chunks_access", table_name="chunks")
    op.drop_table("chunks")
    op.drop_table("documents")
    op.drop_table("sources")
    op.drop_table("user_profiles")
    op.drop_table("departments")
