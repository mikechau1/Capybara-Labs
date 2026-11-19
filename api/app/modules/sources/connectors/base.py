"""The contract every connector follows. Card M2-04 owns this file."""

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from app.shared.types import Sensitivity


@dataclass(frozen=True)
class SourceItem:
    external_id: str
    title: str
    text: str
    updated_at: datetime
    link: str
    sensitivity: Sensitivity | None = None  # None: use the source default, else restricted


class Connector(Protocol):
    def fetch(self, cursor: str | None) -> Iterator[SourceItem]:
        """Yield items changed since `cursor` (None means everything)."""
        ...

    def next_cursor(self) -> str | None:
        """Cursor to store after a successful run."""
        ...

    def current_ids(self) -> set[str]:
        """Every external ID that still exists, so the pipeline can remove deleted items."""
        ...
