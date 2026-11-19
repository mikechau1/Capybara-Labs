"""Discord connector: allow-listed channels only, pulled over the REST API. Card M4-09 owns this.

No always-on bot. Tests use recorded responses and never call Discord.
"""

from collections.abc import Iterator

from app.modules.sources.connectors.base import SourceItem


class DiscordConnector:
    def __init__(self, allowed_channel_ids: list[str]) -> None:
        self.allowed_channel_ids = allowed_channel_ids

    def fetch(self, cursor: str | None) -> Iterator[SourceItem]:
        # TODO(M4-09): one thread is one document (long threads split into overlapping windows
        # that carry the title); messages outside threads grouped by channel and day.
        raise NotImplementedError("Card M4-09")

    def next_cursor(self) -> str | None:
        raise NotImplementedError("Card M4-09")

    def current_ids(self) -> set[str]:
        raise NotImplementedError("Card M4-09")
