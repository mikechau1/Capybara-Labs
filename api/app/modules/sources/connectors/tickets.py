"""Tickets connector: reads the mock ticketing database over SQL. Card M4-07 owns this file.

Ticket metrics (counting queries) are card M4-08 and live in their own file when built.
"""

from collections.abc import Iterator

from app.modules.sources.connectors.base import SourceItem


class TicketsConnector:
    def fetch(self, cursor: str | None) -> Iterator[SourceItem]:
        # TODO(M4-07): one ticket is one document; updated time is the cursor.
        raise NotImplementedError("Card M4-07")

    def next_cursor(self) -> str | None:
        raise NotImplementedError("Card M4-07")

    def current_ids(self) -> set[str]:
        raise NotImplementedError("Card M4-07")
