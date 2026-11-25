"""Card M2-01: departments, sources, documents, chunks and user profiles."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import delete, inspect, select, text, update
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from app.modules.auth.models import UserProfile
from app.modules.sources.models import Chunk, Document, Source
from app.shared.types import Sensitivity, SourceType
from tests import factories as make


def _chunk_labels(db: Session) -> list[tuple[str, str, str]]:
    return [
        (c.department_id, c.source_type.value, c.sensitivity.value)
        for c in db.scalars(select(Chunk).execution_options(populate_existing=True))
    ]


def test_tables_and_chunk_indexes_exist(db: Session):
    inspector = inspect(db.connection())
    tables = set(inspector.get_table_names())
    assert {"departments", "sources", "documents", "chunks", "user_profiles"} <= tables

    indexes = {i["name"]: i for i in inspector.get_indexes("chunks")}
    assert indexes["ix_chunks_access"]["column_names"] == [
        "department_id",
        "source_type",
        "sensitivity",
    ]
    assert indexes["ix_chunks_search"]["column_names"] == ["search"]
    assert indexes["ix_chunks_search"]["dialect_options"]["postgresql_using"] == "gin"


def test_source_defaults(db: Session):
    src = make.source(db)
    db.refresh(src)
    assert src.config == {}
    assert src.last_sync_status == "never"
    assert src.sync_cursor is None
    assert src.created_at is not None


def test_document_and_chunk_round_trip(db: Session):
    src = make.source(db, "finance", SourceType.TICKETS)
    doc = make.document(db, src, "TICKET-1", Sensitivity.RESTRICTED, "Vendor payment hold")
    make.chunk(db, doc, "Q4 vendor payments are on hold pending review.")

    stored = db.scalars(select(Chunk)).one()
    assert (stored.department_id, stored.source_type, stored.sensitivity) == (
        "finance",
        SourceType.TICKETS,
        Sensitivity.RESTRICTED,
    )
    assert len(stored.embedding) == 384
    assert stored.embedding_model == "fake-v2"
    assert db.get(Document, doc.id).deleted is False


def test_document_sensitivity_defaults_to_restricted(db: Session):
    src = make.source(db)
    db.execute(
        text(
            "INSERT INTO documents (source_id, department_id, source_type, external_id, title,"
            " link, content_hash) VALUES (:s, :d, :t, 'X', 'x', 'x', 'x')"
        ),
        {"s": src.id, "d": src.department_id, "t": src.source_type.value},
    )
    assert db.scalar(text("SELECT sensitivity FROM documents")) == "restricted"


# The copied labels: the database keeps them in step with their source and document.


def test_chunk_labels_that_disagree_with_their_document_are_refused(db: Session):
    src = make.source(db, "finance", SourceType.TICKETS)
    make.department(db, "engineering")
    doc = make.document(db, src, sensitivity=Sensitivity.RESTRICTED)
    # Every column is valid on its own (including embedding_model), so the only thing that can
    # refuse this row is the composite foreign key tying the labels to the document.
    with pytest.raises(IntegrityError, match="fk_chunks_document_id_documents"):
        db.add(
            Chunk(
                document_id=doc.id,
                position=0,
                text="restricted finance text",
                embedding=make.unit_vector(0),
                embedding_model="fake-v2",
                department_id="engineering",
                source_type=SourceType.DOCS,
                sensitivity=Sensitivity.PUBLIC,
            )
        )
        db.flush()
    db.rollback()


def test_an_upsert_cannot_relabel_a_chunk(db: Session):
    src = make.source(db, "finance", SourceType.TICKETS)
    chunk = make.chunk(db, make.document(db, src, sensitivity=Sensitivity.RESTRICTED), "secret")
    with pytest.raises(IntegrityError, match="fk_chunks_document_id_documents"):
        db.execute(
            text(
                "INSERT INTO chunks (document_id, position, text, embedding, embedding_model,"
                " department_id, source_type, sensitivity)"
                " SELECT document_id, position, text, embedding, embedding_model,"
                " department_id, source_type, sensitivity FROM chunks WHERE id = :id"
                " ON CONFLICT (document_id, position) DO UPDATE SET sensitivity = 'public'"
            ),
            {"id": chunk.id},
        )
    db.rollback()


# Deleted documents are never searchable (triggers in migration 0002).


def test_marking_a_document_deleted_removes_its_chunks(db: Session):
    doc = make.document(db, make.source(db))
    make.chunk(db, doc, "one", 0)
    make.chunk(db, doc, "two", 1)

    db.execute(update(Document).where(Document.id == doc.id).values(deleted=True))
    assert db.scalars(select(Chunk)).all() == []


def test_a_deleted_document_cannot_get_chunks(db: Session):
    doc = make.document(db, make.source(db))
    db.execute(update(Document).where(Document.id == doc.id).values(deleted=True))
    with pytest.raises(IntegrityError, match="is deleted"):
        make.chunk(db, doc, "sneaked back in")
    db.rollback()


def test_a_revived_document_can_be_chunked_again(db: Session):
    doc = make.document(db, make.source(db))
    db.execute(update(Document).where(Document.id == doc.id).values(deleted=True))
    db.execute(update(Document).where(Document.id == doc.id).values(deleted=False))
    make.chunk(db, doc, "back again")
    assert len(db.scalars(select(Chunk)).all()) == 1


def test_document_labels_that_disagree_with_their_source_are_refused(db: Session):
    src = make.source(db, "finance", SourceType.TICKETS)
    make.department(db, "engineering")
    with pytest.raises(IntegrityError):
        db.add(
            Document(
                source_id=src.id,
                department_id="engineering",
                source_type=SourceType.TICKETS,
                external_id="X",
                title="x",
                link="x",
                sensitivity=Sensitivity.PUBLIC,
                content_hash="x",
            )
        )
        db.flush()
    db.rollback()


def test_moving_a_source_to_another_department_relabels_its_chunks(db: Session):
    src = make.source(db, "finance", SourceType.TICKETS)
    make.department(db, "engineering")
    make.chunk(db, make.document(db, src, sensitivity=Sensitivity.INTERNAL), "x")

    db.execute(update(Source).where(Source.id == src.id).values(department_id="engineering"))
    assert _chunk_labels(db) == [("engineering", "tickets", "internal")]


def test_changing_a_document_sensitivity_relabels_its_chunks(db: Session):
    src = make.source(db)
    doc = make.document(db, src, sensitivity=Sensitivity.PUBLIC)
    make.chunk(db, doc, "one", 0)
    make.chunk(db, doc, "two", 1)

    db.execute(
        update(Document).where(Document.id == doc.id).values(sensitivity=Sensitivity.RESTRICTED)
    )
    assert _chunk_labels(db) == [("engineering", "docs", "restricted")] * 2


# Search columns


def test_full_text_search_column_is_computed_by_the_database(db: Session):
    doc = make.document(db, make.source(db))
    make.chunk(db, doc, "Q4 vendor payments are on hold pending review.", 0)
    make.chunk(db, doc, "The deploy pipeline runs nightly.", 1)

    query = text("SELECT text FROM chunks WHERE search @@ plainto_tsquery('english', :q)")
    # "payment" matches "payments" because both are stemmed to the same word.
    assert db.scalars(query, {"q": "payment"}).all() == [
        "Q4 vendor payments are on hold pending review."
    ]


def test_nearest_embedding_comes_first(db: Session):
    doc = make.document(db, make.source(db))
    make.chunk(db, doc, "far", 0, make.unit_vector(5))
    make.chunk(db, doc, "near", 1, make.unit_vector(1))

    # Cosine distance (<=>), the operator retrieval should use for unit-length embeddings.
    nearest = db.scalars(
        select(Chunk.text).order_by(Chunk.embedding.cosine_distance(make.unit_vector(1)))
    ).first()
    assert nearest == "near"


def test_wrong_embedding_size_is_refused(db: Session):
    doc = make.document(db, make.source(db))
    with pytest.raises(DBAPIError):
        make.chunk(db, doc, "too short", embedding=[1.0, 0.0, 0.0])
    db.rollback()


# Deletes and constraints


def test_deleting_a_document_deletes_its_chunks(db: Session):
    doc = make.document(db, make.source(db))
    make.chunk(db, doc, "one", 0)
    make.chunk(db, doc, "two", 1)

    db.execute(delete(Document).where(Document.id == doc.id))
    assert db.scalars(select(Chunk)).all() == []


def test_deleting_a_source_deletes_its_documents_and_chunks(db: Session):
    src = make.source(db)
    make.chunk(db, make.document(db, src), "x")

    db.execute(delete(Source).where(Source.id == src.id))
    assert db.scalars(select(Document)).all() == []
    assert db.scalars(select(Chunk)).all() == []


@pytest.mark.parametrize(
    "sql",
    [
        # Values outside the enums are refused by the database itself, not only by Python.
        "UPDATE chunks SET sensitivity = 'secret'",
        "UPDATE documents SET sensitivity = 'secret'",
        "UPDATE sources SET source_type = 'email'",
        "UPDATE sources SET default_sensitivity = 'secret'",
        "UPDATE sources SET last_sync_status = 'maybe'",
    ],
)
def test_database_refuses_unknown_values(db: Session, sql: str):
    make.chunk(db, make.document(db, make.source(db)), "x")
    with pytest.raises(IntegrityError):
        db.execute(text(sql))
    db.rollback()


def test_external_id_is_unique_within_a_source(db: Session):
    src = make.source(db)
    make.document(db, src, "DOC-1")
    make.document(db, make.source(db), "DOC-1")  # same ID in another source is fine
    with pytest.raises(IntegrityError):
        make.document(db, src, "DOC-1")
    db.rollback()


def test_source_department_must_exist(db: Session):
    src = make.source(db)
    with pytest.raises(IntegrityError):
        db.execute(update(Source).where(Source.id == src.id).values(department_id="nope"))
    db.rollback()


def test_updated_at_changes_on_raw_sql_updates(db: Session):
    src = make.source(db)
    long_ago = datetime(2000, 1, 1, tzinfo=UTC)
    db.execute(update(Source).where(Source.id == src.id).values(updated_at=long_ago))
    # Like the upsert ingestion will use: plain SQL, so SQLAlchemy's onupdate does not fire.
    db.execute(text("UPDATE sources SET sync_cursor = 'c1' WHERE id = :id"), {"id": src.id})
    assert db.scalar(text("SELECT updated_at FROM sources")) > long_ago


def test_user_profile(db: Session):
    db.add(UserProfile(user_id="kc-123", display_name="Olivia"))
    db.flush()
    assert db.get(UserProfile, "kc-123").display_name == "Olivia"


def test_an_update_that_changes_nothing_keeps_updated_at(db: Session):
    src = make.source(db)
    long_ago = datetime(2000, 1, 1, tzinfo=UTC)
    db.execute(update(Source).where(Source.id == src.id).values(updated_at=long_ago))
    # A sync re-writing the same value must not look like a change.
    db.execute(text("UPDATE sources SET sync_cursor = sync_cursor WHERE id = :id"), {"id": src.id})
    assert db.scalar(text("SELECT updated_at FROM sources")) == long_ago


def test_in_place_edits_to_source_config_are_saved(db: Session):
    src = make.source(db)
    src.config["folder"] = "seed/docs/finance"
    db.flush()
    db.expire_all()
    assert db.get(Source, src.id).config == {"folder": "seed/docs/finance"}
