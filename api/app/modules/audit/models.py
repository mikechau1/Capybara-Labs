"""The audit log table. Card M3-07 owns this file.

Append-only, enforced by the database (migration 0004): the API's login may only SELECT and
INSERT, and is not an owner or superuser, so it cannot get around that; triggers also refuse
UPDATE, DELETE and TRUNCATE by anyone, and stamp `at` with the real insert time. Fixing a wrong
event means recording a correcting one. No retention or erasure path exists yet (a team
decision; it would have to run as the owner and record an event of its own).

`departments` lists the departments an event concerns: those of the pools searched and used,
plus any named explicitly, but not pools that were only denied, so a planner's guess never
shows a question to another department's owner. The audit page (card M4-03) shows owners only
events touching their department.
Questions are stored as asked and may be sensitive; only admins and the owners of the
departments involved may read them (M4-03).
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, CheckConstraint, DateTime, Index, String, Text, func, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, enum_column
from app.modules.audit.schemas import EVENT_TYPES
from app.shared.types import Role


def _json_list() -> Mapped[list[Any]]:
    return mapped_column(JSONB, default=list, server_default=text("'[]'::jsonb"))


class AuditEvent(Base):
    __tablename__ = "audit_events"
    # Read back id and the trigger-set `at` in the INSERT itself (RETURNING), not a second query.
    __mapper_args__ = {"eager_defaults": True}
    __table_args__ = (
        CheckConstraint(
            "type IN ({})".format(", ".join(f"'{t}'" for t in EVENT_TYPES)), name="type"
        ),
        CheckConstraint("length(user_id) > 0", name="user_id_not_empty"),
        Index("ix_audit_events_at", "at"),
        Index("ix_audit_events_user_id_at", "user_id", "at"),
        Index("ix_audit_events_departments", "departments", postgresql_using="gin"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()")
    )
    type: Mapped[str] = mapped_column(String(40))
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    request_id: Mapped[str | None] = mapped_column(String(128))
    user_id: Mapped[str] = mapped_column(String(255))
    user_department: Mapped[str] = mapped_column(String(50))
    user_role: Mapped[Role] = mapped_column(enum_column(Role, "user_role"))
    user_is_admin: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    question: Mapped[str | None] = mapped_column(Text)
    # Pools as {"department", "source_type", "sensitivity"} objects; chunks as ChunkRef objects
    # (id, document id and labels at the time); grant ids as strings.
    pools_searched: Mapped[list[Any]] = _json_list()
    pools_denied: Mapped[list[Any]] = _json_list()
    pools_used: Mapped[list[Any]] = _json_list()
    chunks_retrieved: Mapped[list[Any]] = _json_list()
    chunks_cited: Mapped[list[Any]] = _json_list()
    grant_ids: Mapped[list[Any]] = _json_list()
    departments: Mapped[list[str]] = mapped_column(
        ARRAY(String(50)), default=list, server_default=text("'{}'")
    )
    detail: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb")
    )
