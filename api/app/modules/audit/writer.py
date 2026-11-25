"""The one way to write an audit event. Card M3-07 owns this file.

    from app.modules.audit.schemas import AuditEventCreate
    from app.modules.audit.writer import record

    record(db, AuditEventCreate.by(user, "chat", question=q, pools_searched=..., ...))
    db.commit()   # the caller commits the event together with the work it describes

`record` adds the event to the caller's session and flushes it, so a failed insert raises
right here, before anything is committed, and the whole request fails with it. It never
commits on its own: an answer and its audit event are saved together or not at all.

Don't wrap `record` in a savepoint (`db.begin_nested()`) and carry on after it fails: the
answer would then be committed without its event. Let the error end the request.
"""

from sqlalchemy.orm import Session

from app.modules.audit import models
from app.modules.audit.schemas import AuditEvent, AuditEventCreate
from app.shared.logs import current_request_id


def record(db: Session, event: AuditEventCreate) -> AuditEvent:
    departments = set(event.departments)
    departments |= {p.department for p in event.pools_searched + event.pools_used}
    # One JSON dump for every JSONB column, so UUIDs, datetimes and enums (in `detail` too)
    # are stored as strings; the engine has no JSON serializer of its own.
    as_json = event.model_dump(mode="json")
    row = models.AuditEvent(
        type=event.type,
        request_id=current_request_id(),
        user_id=event.user_id,
        user_department=event.user_department,
        user_role=event.user_role,
        user_is_admin=event.user_is_admin,
        question=event.question,
        pools_searched=as_json["pools_searched"],
        pools_denied=as_json["pools_denied"],
        pools_used=as_json["pools_used"],
        chunks_retrieved=as_json["chunks_retrieved"],
        chunks_cited=as_json["chunks_cited"],
        grant_ids=sorted(str(g) for g in event.grant_ids),
        departments=sorted(departments),
        detail=as_json["detail"],
    )
    db.add(row)
    db.flush()
    return AuditEvent.model_validate(row, from_attributes=True)
