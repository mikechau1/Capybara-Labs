from datetime import datetime

from fastapi import APIRouter

from app.modules.audit.schemas import AuditEvent, EventType
from app.modules.auth.dependencies import CurrentUser
from app.shared.errors import not_implemented

router = APIRouter(tags=["audit"])

# ---- Audit log: card M4-03 -----------------------------------------------------------------


@router.get("/audit", response_model=list[AuditEvent])
def list_audit_events(
    user: CurrentUser,
    user_id: str | None = None,
    department: str | None = None,
    event_type: EventType | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
) -> list[AuditEvent]:
    raise not_implemented("M4-03")
