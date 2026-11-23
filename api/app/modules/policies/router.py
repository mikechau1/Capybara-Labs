from uuid import UUID

from fastapi import APIRouter

from app.modules.auth.dependencies import CurrentUser
from app.modules.policies.schemas import (
    AccessRequest,
    AccessRequestCreate,
    AccessRequestDecision,
    Grant,
    GrantCreate,
)
from app.shared.errors import not_implemented

router = APIRouter(tags=["policies"])

# ---- Grants: card M4-01 -------------------------------------------------------------------


@router.get("/grants", response_model=list[Grant])
def list_grants(user: CurrentUser) -> list[Grant]:
    raise not_implemented("M4-01")


@router.post("/grants", response_model=Grant, status_code=201)
def create_grant(body: GrantCreate, user: CurrentUser) -> Grant:
    raise not_implemented("M4-01")


@router.post("/grants/{grant_id}/revoke", response_model=Grant)
def revoke_grant(grant_id: UUID, user: CurrentUser) -> Grant:
    raise not_implemented("M4-01")


# ---- Access requests: card M4-04 ----------------------------------------------------------


@router.post("/access-requests", response_model=AccessRequest, status_code=201)
def create_access_request(body: AccessRequestCreate, user: CurrentUser) -> AccessRequest:
    raise not_implemented("M4-04")


@router.get("/access-requests/mine", response_model=list[AccessRequest])
def my_access_requests(user: CurrentUser) -> list[AccessRequest]:
    raise not_implemented("M4-04")


@router.get("/access-requests/inbox", response_model=list[AccessRequest])
def owner_inbox(user: CurrentUser) -> list[AccessRequest]:
    raise not_implemented("M4-04")


@router.post("/access-requests/{request_id}/approve", response_model=AccessRequest)
def approve_request(
    request_id: str, body: AccessRequestDecision, user: CurrentUser
) -> AccessRequest:
    raise not_implemented("M4-04")


@router.post("/access-requests/{request_id}/deny", response_model=AccessRequest)
def deny_request(request_id: str, body: AccessRequestDecision, user: CurrentUser) -> AccessRequest:
    raise not_implemented("M4-04")
