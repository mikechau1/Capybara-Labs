"""Deterministic model for tests and local work. Card M3-01 owns this file."""

from app.modules.llm.base import DraftAnswer, Plan
from app.modules.retrieval.gateway import RetrievedChunk


class StubLLM:
    def plan(self, question: str, pool_descriptions: dict[str, str]) -> Plan:
        # TODO(M3-01): rule-based plan, e.g. search the raw question everywhere in scope.
        raise NotImplementedError("Card M3-01")

    def answer(
        self, question: str, chunks: list[RetrievedChunk], history: list[dict[str, str]]
    ) -> DraftAnswer:
        # TODO(M3-01): echo the chunks with citations, so leakage tests can inspect output.
        raise NotImplementedError("Card M3-01")
