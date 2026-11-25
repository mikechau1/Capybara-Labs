"""Loading grants and resolving a user's scope from the database. Card M2-02.

    from app.modules.policies.service import scope_for

    scope = scope_for(db, user)   # fresh on every question; never cache it

Grants API endpoints (create, revoke) are card M4-01.
"""

import logging
from datetime import UTC, datetime

from pydantic import ValidationError
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.modules.policies import models
from app.modules.policies.schemas import Grant
from app.modules.policies.scope import Scope, resolve_scope
from app.modules.sources.models import Department
from app.shared.types import Principal

log = logging.getLogger(__name__)


def active_grants(db: Session, now: datetime, principal: Principal | None = None) -> list[Grant]:
    """Grants that are neither revoked nor expired at `now`. With a principal, only those that
    could match them (named for them, or for their department or any department); the pure
    function still checks every rule, so this is only a filter for speed."""
    query = select(models.Grant).where(
        models.Grant.revoked_at.is_(None),
        or_(models.Grant.expires_at.is_(None), models.Grant.expires_at > now),
    )
    if principal is not None:
        query = query.where(
            or_(
                models.Grant.grantee_user_id == principal.user_id,
                and_(
                    models.Grant.grantee_user_id.is_(None),
                    or_(
                        models.Grant.grantee_department.is_(None),
                        models.Grant.grantee_department == principal.department,
                    ),
                ),
            )
        )
    grants = []
    for row in db.scalars(query):
        # One row the schema rejects is skipped and logged; it must never stop everyone else's
        # scope from resolving (resolve_scope re-checks the rest).
        try:
            grants.append(Grant.model_validate(row, from_attributes=True))
        except ValidationError:
            log.warning("ignoring a malformed grant", extra={"grant_id": str(row.id)})
    return grants


def department_ids(db: Session) -> list[str]:
    return list(db.scalars(select(Department.id).order_by(Department.id)))


class UnknownDepartment(ValueError):
    """The user's department isn't in the departments table: usually a token-mapping bug
    (card M1-06). Refused rather than silently giving an empty or odd scope."""


def scope_for(db: Session, principal: Principal, now: datetime | None = None) -> Scope:
    now = now or datetime.now(UTC)
    departments = department_ids(db)
    if principal.department not in departments:
        raise UnknownDepartment(f"unknown department {principal.department!r}")
    return resolve_scope(principal, active_grants(db, now, principal), departments, now)
