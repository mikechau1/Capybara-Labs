"""Races between transactions, run with real separate connections (card M2-01).

These commit for real (the `db` fixture's rollback can't show what another connection sees), so
each test cleans up after itself.
"""

import threading
from collections.abc import Iterator

import pytest
from sqlalchemy import Engine, text

_VECTOR = "('[' || array_to_string(array_fill(0, ARRAY[383]), ',') || ',1]')::vector"
_CHUNK = (
    "INSERT INTO chunks (document_id, position, text, embedding, embedding_model,"
    " department_id, source_type, sensitivity)"
    f" VALUES (:d, 0, 're-chunked text', {_VECTOR}, 'fake-v2', 'race-dept', 'docs', 'internal')"
)


@pytest.fixture
def document_id(db_engine: Engine) -> Iterator[str]:
    with db_engine.begin() as c:
        c.execute(text("INSERT INTO departments (id, name) VALUES ('race-dept', 'Race')"))
        source = c.scalar(
            text(
                "INSERT INTO sources (name, department_id, source_type)"
                " VALUES ('race-src', 'race-dept', 'docs') RETURNING id"
            )
        )
        doc = c.scalar(
            text(
                "INSERT INTO documents (source_id, department_id, source_type, external_id,"
                " title, link, sensitivity, content_hash)"
                " VALUES (:s, 'race-dept', 'docs', 'R1', 't', 'l', 'internal', 'h') RETURNING id"
            ),
            {"s": source},
        )
    try:
        yield doc
    finally:
        with db_engine.begin() as c:
            c.execute(text("DELETE FROM sources WHERE name = 'race-src'"))
            c.execute(text("DELETE FROM departments WHERE id = 'race-dept'"))


def _chunks_left(db_engine: Engine, document_id: str) -> int:
    with db_engine.connect() as c:
        return c.scalar(
            text("SELECT count(*) FROM chunks WHERE document_id = :d"), {"d": document_id}
        )


def test_deleting_while_rechunking_leaves_no_searchable_chunks(db_engine, document_id):
    """T1 re-chunks (has read deleted = false); T2 marks the document deleted meanwhile.
    T2 must wait for T1, then remove T1's chunk too."""
    rechunk = db_engine.connect()
    transaction = rechunk.begin()
    rechunk.execute(text(_CHUNK), {"d": document_id})

    finished = threading.Event()

    def delete_document() -> None:
        with db_engine.begin() as c:
            c.execute(text("UPDATE documents SET deleted = true WHERE id = :d"), {"d": document_id})
        finished.set()

    other = threading.Thread(target=delete_document)
    other.start()
    waited_for_rechunk = not finished.wait(1.0)
    transaction.commit()
    rechunk.close()
    other.join(10)

    assert waited_for_rechunk, "the delete did not wait for the re-chunk to finish"
    assert _chunks_left(db_engine, document_id) == 0


def test_rechunking_while_deleting_is_refused(db_engine, document_id):
    """T2 marks the document deleted first (not yet committed); T1 then tries to add a chunk.
    T1 must wait for T2, see deleted = true and be refused."""
    delete = db_engine.connect()
    transaction = delete.begin()
    delete.execute(text("UPDATE documents SET deleted = true WHERE id = :d"), {"d": document_id})

    errors: list[str] = []

    def rechunk() -> None:
        try:
            with db_engine.begin() as c:
                c.execute(text(_CHUNK), {"d": document_id})
        except Exception as exc:  # noqa: BLE001 - the refusal is what we want to see
            errors.append(str(exc))

    other = threading.Thread(target=rechunk)
    other.start()
    other.join(1.0)
    transaction.commit()
    delete.close()
    other.join(10)

    assert errors and "is deleted" in errors[0]
    assert _chunks_left(db_engine, document_id) == 0
