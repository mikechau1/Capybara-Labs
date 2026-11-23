"""Helpers that create rows for database tests, with sensible defaults.

Each one adds the row and flushes it (so it gets its ID) but does not commit; the `db` fixture
rolls everything back after the test.
"""

import hashlib
import uuid

from sqlalchemy.orm import Session

from app.modules.sources.models import EMBEDDING_DIMENSIONS, Chunk, Department, Document, Source
from app.shared.types import Sensitivity, SourceType


def unit_vector(index: int) -> list[float]:
    """A 384-number embedding pointing along one axis; handy for predictable distances."""
    vector = [0.0] * EMBEDDING_DIMENSIONS
    vector[index] = 1.0
    return vector


def department(db: Session, id: str = "engineering", name: str | None = None) -> Department:
    row = db.get(Department, id) or Department(id=id, name=name or id.title())
    db.add(row)
    db.flush()
    return row


def source(
    db: Session,
    department_id: str = "engineering",
    source_type: SourceType = SourceType.DOCS,
    name: str | None = None,
    default_sensitivity: Sensitivity | None = None,
) -> Source:
    department(db, department_id)
    row = Source(
        name=name or f"{department_id}-{source_type}-{uuid.uuid4().hex[:6]}",
        department_id=department_id,
        source_type=source_type,
        default_sensitivity=default_sensitivity,
    )
    db.add(row)
    db.flush()
    return row


def document(
    db: Session,
    src: Source,
    external_id: str | None = None,
    sensitivity: Sensitivity = Sensitivity.INTERNAL,
    title: str = "A document",
    text: str = "",
) -> Document:
    row = Document(
        source_id=src.id,
        department_id=src.department_id,
        source_type=src.source_type,
        external_id=external_id or uuid.uuid4().hex,
        title=title,
        link=f"https://example.com/{title.replace(' ', '-').lower()}",
        sensitivity=sensitivity,
        content_hash=hashlib.sha256(text.encode()).hexdigest(),
    )
    db.add(row)
    db.flush()
    return row


def chunk(
    db: Session,
    doc: Document,
    text: str,
    position: int = 0,
    embedding: list[float] | None = None,
) -> Chunk:
    """Labels are copied from the document, as the ingestion pipeline must do."""
    row = Chunk(
        document_id=doc.id,
        position=position,
        text=text,
        embedding=embedding or unit_vector(0),
        embedding_model="fake-v2",
        department_id=doc.department_id,
        source_type=doc.source_type,
        sensitivity=doc.sensitivity,
    )
    db.add(row)
    db.flush()
    return row


def grant(db: Session, owning_department: str = "finance", **fields):
    """A department grant to every member by default; pass grantee_user_id for a named user."""
    from app.modules.policies.models import Grant
    from app.shared.types import Role

    department(db, owning_department)
    if fields.get("grantee_department"):
        department(db, fields["grantee_department"])
    if "grantee_user_id" not in fields:
        fields.setdefault("grantee_min_role", Role.MEMBER)
    fields.setdefault("max_sensitivity", Sensitivity.INTERNAL)
    row = Grant(owning_department=owning_department, created_by="owner-1", **fields)
    db.add(row)
    db.flush()
    return row
