from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel

from app.shared.types import Pool, Role

EventType = Literal[
    "chat",
    "grant_created",
    "grant_revoked",
    "access_request_created",
    "access_request_approved",
    "access_request_denied",
    "access_request_expired",
]


class AuditEvent(BaseModel):
    id: str
    type: EventType
    at: datetime
    user_id: str
    user_department: str
    user_role: Role
    question: str | None = None
    pools_searched: list[Pool] = []
    pools_denied: list[Pool] = []
    chunk_ids_retrieved: list[str] = []
    chunk_ids_cited: list[str] = []
    grant_ids: list[str] = []
    detail: dict[str, Any] = {}
