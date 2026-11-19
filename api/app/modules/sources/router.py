from fastapi import APIRouter

from app.modules.auth.dependencies import CurrentUser
from app.modules.sources.schemas import SourceStatus
from app.shared.errors import not_implemented

router = APIRouter(tags=["sources"])

# ---- Sources page and "Sync now": card M4-10 -----------------------------------------------


@router.get("/sources", response_model=list[SourceStatus])
def list_sources(user: CurrentUser) -> list[SourceStatus]:
    raise not_implemented("M4-10")


@router.post("/sources/{source_id}/sync", status_code=202)
def sync_now(source_id: str, user: CurrentUser) -> dict[str, str]:
    raise not_implemented("M4-10")
