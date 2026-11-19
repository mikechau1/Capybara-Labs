from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from app.shared.types import Sensitivity, SourceType


class SourceStatus(BaseModel):
    id: str
    name: str
    department: str
    source_type: SourceType
    default_sensitivity: Sensitivity | None
    item_count: int
    last_sync_at: datetime | None
    last_sync_status: Literal["never", "ok", "running", "failed"]
    last_error: str | None = None
