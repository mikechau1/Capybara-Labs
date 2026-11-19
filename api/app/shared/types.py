"""Domain types shared by every module. Change these only in a PR the whole team reviews."""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class Role(StrEnum):
    MEMBER = "member"
    MANAGER = "manager"
    OWNER = "owner"


class Sensitivity(StrEnum):
    PUBLIC = "public"
    INTERNAL = "internal"
    RESTRICTED = "restricted"


class SourceType(StrEnum):
    DOCS = "docs"
    TICKETS = "tickets"
    DISCORD = "discord"


# Enums compare alphabetically, so use these ranks for "at least" checks.
ROLE_RANK = {Role.MEMBER: 0, Role.MANAGER: 1, Role.OWNER: 2}
SENSITIVITY_RANK = {Sensitivity.PUBLIC: 0, Sensitivity.INTERNAL: 1, Sensitivity.RESTRICTED: 2}


class Pool(BaseModel):
    """One slice of company data. Access is decided per pool, never per document."""

    model_config = ConfigDict(frozen=True)

    department: str
    source_type: SourceType
    sensitivity: Sensitivity


class Principal(BaseModel):
    """The verified user behind a request. Built only by the auth module."""

    user_id: str
    username: str
    display_name: str
    department: str
    role: Role
    is_admin: bool = False
