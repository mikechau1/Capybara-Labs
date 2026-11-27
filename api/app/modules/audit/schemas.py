"""Audit event shapes. Card M3-07 owns this file; the read API and page are card M4-03."""

from datetime import datetime
from typing import Annotated, Any, Literal, get_args
from uuid import UUID

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    Field,
    StringConstraints,
    TypeAdapter,
    field_validator,
)

from app.shared.types import Pool, Principal, Role, Sensitivity, SourceType

EventType = Literal[
    "chat",
    "grant_created",
    "grant_revoked",
    "access_request_created",
    "access_request_approved",
    "access_request_denied",
    "access_request_expired",
]
EVENT_TYPES: tuple[str, ...] = get_args(EventType)

# Department ids are lowercase slugs (the departments table enforces the same pattern).
DepartmentId = Annotated[
    str,
    BeforeValidator(lambda v: v.strip().lower() if isinstance(v, str) else v),
    StringConstraints(pattern=r"^[a-z0-9][a-z0-9-]*$", max_length=50),
]
_DEPARTMENT_ID: TypeAdapter[str] = TypeAdapter(DepartmentId)


def _storable(text: str) -> str:
    """`text` as PostgreSQL can store it: NUL characters removed and lone surrogates (which JSON
    allows but UTF-8 can't encode) replaced, so a user's odd input never fails the request."""
    return text.replace("\x00", "").encode("utf-8", "replace").decode("utf-8")


def _no_nul_in_id(value: str) -> str:
    # Refused, not cleaned: an id must be recorded exactly.
    if _storable(value) != value:
        raise ValueError("ids cannot contain NUL characters or lone surrogates")
    return value


def without_nul(value: Any) -> Any:
    """`value` with every string, at any depth, keys included, made storable (`_storable`).
    PostgreSQL text and JSONB cannot hold NUL or lone surrogates."""
    if isinstance(value, str):
        return _storable(value)
    if isinstance(value, dict):
        return {without_nul(k): without_nul(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [without_nul(v) for v in value]
    return value


class ChunkRef(BaseModel):
    """A chunk as it was when the event happened. Chunks are deleted and re-created when their
    item changes (card M2-04), so the labels are copied here, not looked up later."""

    chunk_id: UUID
    document_id: UUID
    department: DepartmentId
    source_type: SourceType
    sensitivity: Sensitivity


class AuditEventCreate(BaseModel):
    """What a module passes to `writer.record`. Who did it is copied from the Principal at the
    time, so the record stays true even if their department or role changes later.

    `detail` is for ids and small facts (e.g. {"grant_id": ...}), never document text or
    answers: it is not trimmed per department on the audit page.
    """

    type: EventType
    user_id: Annotated[str, Field(min_length=1, max_length=255), AfterValidator(_no_nul_in_id)]
    user_department: DepartmentId
    user_role: Role
    user_is_admin: bool = False
    question: str | None = None
    pools_searched: list[Pool] = []  # the user's pools the search actually ran over
    pools_denied: list[Pool] = []  # pools the plan suggested but the user cannot read
    pools_used: list[Pool] = []  # pools of the chunks the answer was built from
    chunks_retrieved: list[ChunkRef] = []
    chunks_cited: list[ChunkRef] = []
    grant_ids: list[UUID] = []  # Scope.grants_for(pools_used): the grants this answer relied on
    # Departments the event concerns besides those in pools_searched and pools_used, e.g. a
    # grant's owning department. Owners see events touching their department (card M4-03).
    departments: list[DepartmentId] = []
    detail: dict[str, Any] = {}

    @field_validator("question")
    @classmethod
    def _no_nul(cls, value: str | None) -> str | None:
        # PostgreSQL text cannot hold NUL characters; storing one would fail the whole request.
        return _storable(value) if value is not None else None

    @field_validator("detail", mode="before")
    @classmethod
    def _no_nul_in_detail(cls, value: Any) -> Any:
        return without_nul(value)

    @field_validator("pools_searched", "pools_denied", "pools_used")
    @classmethod
    def _pool_departments_are_ids(cls, pools: list[Pool]) -> list[Pool]:
        # The same rule as `departments`, so an owner filter on "finance" never misses a pool
        # recorded as "Finance".
        return [
            Pool(
                department=_DEPARTMENT_ID.validate_python(p.department),
                source_type=p.source_type,
                sensitivity=p.sensitivity,
            )
            for p in pools
        ]

    @classmethod
    def by(cls, principal: Principal, type: EventType, **fields: Any) -> "AuditEventCreate":
        return cls(
            type=type,
            user_id=principal.user_id,
            user_department=principal.department,
            user_role=principal.role,
            user_is_admin=principal.is_admin,
            **fields,
        )


class AuditEvent(AuditEventCreate):
    id: UUID
    at: datetime  # set by the database at insert time
    # The X-Request-ID of the request (card M1-03), linking the event to its log lines. A caller
    # may choose its own request ID, so treat this as a lookup aid, not as proof.
    request_id: str | None = None
