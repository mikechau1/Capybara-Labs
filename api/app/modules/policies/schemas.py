"""Grant and access request shapes. Shared contract with the UI: change both sides in one PR."""

from datetime import UTC, datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, StringConstraints, model_validator

from app.shared.types import Role, Sensitivity, SourceType

NonBlank = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
ANY = "any"  # what an API caller sends to mean "any department" or "any source type"


class GrantRules(BaseModel):
    """The same rules as the grants table's CHECK constraints (card M2-02), so a malformed grant
    is refused before it reaches the database or `resolve_scope`. Here None means "any"."""

    # Grantee: either a department (or None for any) plus minimum role, or one named user.
    grantee_department: str | None = None
    grantee_min_role: Role | None = None
    grantee_user_id: NonBlank | None = None
    source_type: SourceType | None = None  # None means any
    max_sensitivity: Sensitivity
    expires_at: AwareDatetime | None = None  # required when max_sensitivity is restricted

    @model_validator(mode="after")
    def _valid_grant(self) -> "GrantRules":
        if (self.grantee_user_id is None) == (self.grantee_min_role is None):
            raise ValueError("a grant names either one user or a minimum role, not both or neither")
        if self.grantee_user_id is not None and self.grantee_department is not None:
            raise ValueError("a grant to a named user has no grantee department")
        if self.max_sensitivity == Sensitivity.PUBLIC:
            raise ValueError("public data needs no grant")
        if self.max_sensitivity == Sensitivity.RESTRICTED and self.expires_at is None:
            raise ValueError("a restricted grant must expire")
        return self


class GrantCreate(GrantRules):
    """What the grants API (card M4-01) accepts. Breadth must be stated, never implied: a
    missing or empty grantee department or source type is refused, and "any" must be sent to
    mean any. An empty dropdown therefore can't create a company-wide grant by accident."""

    @model_validator(mode="before")
    @classmethod
    def _breadth_is_explicit(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        data = dict(data)
        if data.get("source_type") in (None, ""):
            raise ValueError('source_type is required: a source type, or "any"')
        if data["source_type"] == ANY:
            data["source_type"] = None
        if data.get("grantee_user_id") is None:
            if data.get("grantee_department") in (None, ""):
                raise ValueError('grantee_department is required: a department id, or "any"')
            if data["grantee_department"] == ANY:
                data["grantee_department"] = None
        return data

    @model_validator(mode="after")
    def _expires_in_the_future(self) -> "GrantCreate":
        if self.expires_at is not None and self.expires_at <= datetime.now(UTC):
            raise ValueError("expires_at must be in the future")
        return self


class Grant(GrantRules):
    """A stored grant, as loaded from the database."""

    id: UUID  # sent as a string in JSON
    owning_department: str
    created_by: NonBlank
    created_at: AwareDatetime
    revoked_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def _expires_after_creation(self) -> "Grant":
        if self.expires_at is not None and self.expires_at <= self.created_at:
            raise ValueError("expires_at must be after created_at")
        return self


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
    grant_id: UUID | None = None
