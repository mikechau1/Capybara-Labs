"""Tables for company data. Card M2-01 owns this file.

- departments   one row per department; its id is the slug used everywhere ("engineering")
- sources       one registered data source (a docs folder, the ticket system, a Discord server)
- documents     one item from a source (a file, a ticket, a Discord thread)
- chunks        pieces of a document's text with their embedding; what retrieval searches

Access labels and how the database keeps them honest:
- A source's department and type are set when it is registered (card M2-04 / M4-10).
- A document copies its source's department and type, and has its own sensitivity, which comes
  from the source registration or the item itself, never from what the text says.
- A chunk copies all three from its document, so retrieval (card M2-07) can filter on them
  directly. (Retrieval still joins documents for titles and links.)
Both copies are composite foreign keys with ON UPDATE CASCADE: a chunk whose labels disagree
with its document cannot be inserted, and changing a source's department or a document's
sensitivity updates every copy in the same statement. Retrieval can trust the chunk columns.

Deleted items (enforced by triggers in migration 0002): setting `documents.deleted` deletes the
document's chunks, and inserting a chunk into a deleted document is refused. So a tombstoned
item is never searchable.

Other rules for the ingestion pipeline (card M2-04):
- Department ids are permanent slugs; do not rename them.
- Re-derive each document's sensitivity on every sync, even when its content hash is unchanged:
  a source's default_sensitivity may have been tightened since. (Nothing else propagates it.)
- When an item comes back after being deleted, clear `deleted` and re-chunk it even if its
  content hash is unchanged.
- Re-chunking a document means deleting all its chunks, then inserting the new ones; shifting
  positions in place hits the (document_id, position) unique constraint.
- Chunk text should stay under ~200 words (the embedding model's input limit, card M2-03).
- Embeddings are unit length, so search should use cosine distance (`<=>`), and only
  over chunks whose `embedding_model` is the current embedder's `model_id`. There is no
  vector index at demo scale; if one is added, filtered search needs pgvector's
  `hnsw.iterative_scan`. Full-text queries must use the same config:
  plainto_tsquery('english', ...).

Only the ingestion pipeline writes chunks, and only the retrieval module reads them.
"""

import uuid
from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Computed,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.ext.mutable import MutableDict
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, Timestamps, enum_column
from app.shared.types import Sensitivity, SourceType

# Size of each embedding. Must match the model in app/shared/embeddings.py (card M2-03):
# all-MiniLM-L6-v2 produces 384 numbers per text. Changing it needs a migration.
EMBEDDING_DIMENSIONS = 384

SYNC_STATUSES = ("never", "ok", "running", "failed")


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()")
    )


class Department(Timestamps, Base):
    __tablename__ = "departments"
    __table_args__ = (
        # Lowercase slugs only, as in tokens and pool names; added by migration 0003 (M2-02).
        CheckConstraint("id ~ '^[a-z0-9][a-z0-9-]*$'", name="id_is_slug"),
    )

    id: Mapped[str] = mapped_column(String(50), primary_key=True)  # e.g. "engineering"
    name: Mapped[str] = mapped_column(String(100))  # e.g. "Engineering"


class Source(Timestamps, Base):
    __tablename__ = "sources"
    __table_args__ = (
        CheckConstraint(
            "last_sync_status IN ({})".format(", ".join(f"'{s}'" for s in SYNC_STATUSES)),
            name="last_sync_status",
        ),
        # Lets documents reference (id, department, type) together; see the module docstring.
        UniqueConstraint("id", "department_id", "source_type"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    name: Mapped[str] = mapped_column(String(100), unique=True)  # e.g. "finance-tickets"
    department_id: Mapped[str] = mapped_column(ForeignKey("departments.id"))
    source_type: Mapped[SourceType] = mapped_column(enum_column(SourceType, "source_type"))
    # Used when an item has no sensitivity of its own; if this is empty too, items are restricted.
    default_sensitivity: Mapped[Sensitivity | None] = mapped_column(
        enum_column(Sensitivity, "default_sensitivity")
    )
    # Connector settings, e.g. {"folder": "seed/docs/finance"} or {"channel_ids": [...]}.
    # MutableDict: in-place edits (src.config["folder"] = ...) are saved too.
    config: Mapped[dict[str, Any]] = mapped_column(
        MutableDict.as_mutable(JSONB), default=dict, server_default=text("'{}'::jsonb")
    )
    sync_cursor: Mapped[str | None] = mapped_column(Text)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_sync_status: Mapped[str] = mapped_column(
        String(10), default="never", server_default="never"
    )
    last_error: Mapped[str | None] = mapped_column(Text)


class Document(Timestamps, Base):
    __tablename__ = "documents"
    __table_args__ = (
        UniqueConstraint("source_id", "external_id"),
        # Lets chunks reference (id, department, type, sensitivity) together.
        UniqueConstraint("id", "department_id", "source_type", "sensitivity"),
        ForeignKeyConstraint(
            ["source_id", "department_id", "source_type"],
            ["sources.id", "sources.department_id", "sources.source_type"],
            ondelete="CASCADE",
            onupdate="CASCADE",
        ),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    source_id: Mapped[uuid.UUID]
    # Copied from the source; kept in step by the foreign key above.
    department_id: Mapped[str] = mapped_column(String(50))
    source_type: Mapped[SourceType] = mapped_column(enum_column(SourceType, "source_type"))
    external_id: Mapped[str] = mapped_column(String(500))  # the item's ID in its own system
    title: Mapped[str] = mapped_column(Text)
    link: Mapped[str] = mapped_column(Text)
    # Defaults to restricted in the database too: unknown sensitivity means restricted.
    sensitivity: Mapped[Sensitivity] = mapped_column(
        enum_column(Sensitivity, "sensitivity"), server_default=Sensitivity.RESTRICTED.value
    )
    content_hash: Mapped[str] = mapped_column(String(64))  # sha256 hex of the text
    source_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Set when the item disappears from its source; its chunks are deleted at the same time.
    deleted: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))


class Chunk(Base):
    __tablename__ = "chunks"
    __table_args__ = (
        # Also serves lookups by document_id, so no separate index is needed for that.
        UniqueConstraint("document_id", "position"),
        ForeignKeyConstraint(
            ["document_id", "department_id", "source_type", "sensitivity"],
            [
                "documents.id",
                "documents.department_id",
                "documents.source_type",
                "documents.sensitivity",
            ],
            ondelete="CASCADE",
            onupdate="CASCADE",
        ),
        # Retrieval filters every search on these three (card M2-07).
        Index("ix_chunks_access", "department_id", "source_type", "sensitivity"),
        Index("ix_chunks_search", "search", postgresql_using="gin"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    document_id: Mapped[uuid.UUID]
    position: Mapped[int] = mapped_column(Integer)  # 0, 1, 2, ... within the document
    text: Mapped[str] = mapped_column(Text)
    embedding: Mapped[Any] = mapped_column(Vector(EMBEDDING_DIMENSIONS))
    # Which embedder made `embedding` (Embedder.model_id, card M2-03). Retrieval compares only
    # vectors with the current model_id; after a model change, re-embed the rest.
    embedding_model: Mapped[str] = mapped_column(String(100))
    # Full-text search vector, kept up to date by the database itself.
    search: Mapped[str] = mapped_column(
        TSVECTOR, Computed("to_tsvector('english', text)", persisted=True)
    )
    # Copied from the document; kept in step by the foreign key above.
    department_id: Mapped[str] = mapped_column(String(50))
    source_type: Mapped[SourceType] = mapped_column(enum_column(SourceType, "source_type"))
    sensitivity: Mapped[Sensitivity] = mapped_column(enum_column(Sensitivity, "sensitivity"))
