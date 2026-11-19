"""Grant and access request shapes. Shared contract with the UI: change both sides in one PR."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from app.shared.types import Role, Sensitivity, SourceType


class GrantCreate(BaseModel):
    # Grantee: either a department (or None for any) plus minimum role, or one named user.
    grantee_department: str | None = None
    grantee_min_role: Role | None = None
    grantee_user_id: str | None = None
    source_type: SourceType | None = None  # None means any
    max_sensitivity: Sensitivity
    expires_at: datetime | None = None  # required when max_sensitivity is restricted


class Grant(GrantCreate):
    id: str
    owning_department: str
    created_by: str
    created_at: datetime
    revoked_at: datetime | None = None


class AccessRequestCreate(BaseModel):
    department: str
    source_type: SourceType
    justification: str


class AccessRequestDecision(BaseModel):
    # Used when approving; ignored when denying.
    max_sensitivity: Sensitivity = Sensitivity.INTERNAL
    expires_at: datetime | None = None  # default 30 days, set by the API
    note: str | None = None


class AccessRequest(AccessRequestCreate):
    id: str
    requester_id: str
    requester_department: str
    requester_role: Role
    status: Literal["pending", "approved", "denied", "expired", "cancelled"]
    created_at: datetime
    decided_by: str | None = None
    decided_at: datetime | None = None
    note: str | None = None
    grant_id: str | None = None
