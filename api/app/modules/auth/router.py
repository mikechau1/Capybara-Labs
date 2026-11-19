from fastapi import APIRouter

from app.modules.auth.dependencies import CurrentUser
from app.shared.types import Principal

router = APIRouter(tags=["auth"])


@router.get("/me", response_model=Principal)
def me(user: CurrentUser) -> Principal:
    return user
