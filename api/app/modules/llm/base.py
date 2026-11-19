"""The two operations the chat pipeline needs from a model. Card M3-01 owns this file."""

from typing import Protocol

from pydantic import BaseModel

from app.modules.retrieval.gateway import RetrievedChunk
from app.shared.types import SourceType


class SubQuery(BaseModel):
    query: str
    department: str | None = None
    source_type: SourceType | None = None


class Plan(BaseModel):
    sub_queries: list[SubQuery]  # at most three, checked by code (card M3-03)
    metric: str | None = None  # name of a predefined ticket metric (card M4-08)
    metric_params: dict[str, str] = {}


class DraftAnswer(BaseModel):
    text: str  # cites chunks as [1], [2], ...
    cited: list[int]  # verified against what was retrieved (card M3-04)


class LLM(Protocol):
    def plan(self, question: str, pool_descriptions: dict[str, str]) -> Plan:
        """Sees pool names and descriptions only, never company content."""
        ...

    def answer(
        self, question: str, chunks: list[RetrievedChunk], history: list[dict[str, str]]
    ) -> DraftAnswer: ...
