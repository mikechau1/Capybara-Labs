"""Docs connector: a folder of Markdown and PDF files. Card M2-05 owns this file."""

from collections.abc import Iterator

from app.modules.sources.connectors.base import SourceItem


class DocsConnector:
    def __init__(self, folder: str) -> None:
        self.folder = folder

    def fetch(self, cursor: str | None) -> Iterator[SourceItem]:
        # TODO(M2-05): Markdown sensitivity from front matter; PDF sensitivity from folder name.
        raise NotImplementedError("Card M2-05")

    def next_cursor(self) -> str | None:
        raise NotImplementedError("Card M2-05")

    def current_ids(self) -> set[str]:
        raise NotImplementedError("Card M2-05")
