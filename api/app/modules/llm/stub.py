"""Deterministic model for tests and local work. Card M3-01 owns this file.

No network, no key, same output every time.

For the leakage tests (card M2-08), the stub keeps an exact record of everything it was given:
`StubLLM.calls` holds every call's arguments, untouched. Assert on that, not only on the
answer text, because later steps (citation checks, M3-04) may rewrite or drop parts of the
text. Its answers also repeat every input field word for word, so a canary is visible in the
output too. Never shorten, summarise or filter either.

The planner only recognises department names and a few source-type words as whole words, which
is enough for the seeded demo company. It is not a language model: "financial" does not match
"finance", and a department named with a common word (e.g. "it") would match too often.
"""

import re
from dataclasses import dataclass, field
from typing import Any

from app.modules.llm.base import DraftAnswer, Plan, SubQuery, Turn, split_pool_key
from app.modules.retrieval.gateway import RetrievedChunk
from app.shared.types import SourceType

MAX_SUB_QUERIES = 3

# Words in a question that point at a source type.
_SOURCE_WORDS = {
    SourceType.DOCS: {"doc", "docs", "document", "documents", "documentation", "wiki", "policy"},
    SourceType.TICKETS: {"ticket", "tickets", "bug", "bugs"},
    SourceType.DISCORD: {"discord", "channel", "thread", "threads"},
}
_WORD = re.compile(r"[a-z0-9-]+")


@dataclass
class StubCall:
    """One call to the stub, with its arguments exactly as received."""

    operation: str  # "plan" or "answer"
    arguments: dict[str, Any] = field(default_factory=dict)


class StubLLM:
    def __init__(self) -> None:
        self.calls: list[StubCall] = []

    def plan(
        self, question: str, pool_descriptions: dict[str, str], metrics: dict[str, str]
    ) -> Plan:
        """One sub-query per department the question names, narrowed to the source types it
        names. "Finance tickets?" -> finance/tickets; "engineering and finance" -> one query
        each, every source type; a source type only -> that type everywhere; nothing named ->
        one query over the whole scope. Never picks a metric."""
        self.calls.append(
            StubCall(
                "plan",
                {"question": question, "pool_descriptions": pool_descriptions, "metrics": metrics},
            )
        )
        words = set(_WORD.findall(question.lower()))
        named_types = sorted(t for t, cues in _SOURCE_WORDS.items() if words & cues)
        available: dict[str, set[SourceType]] = {}
        for key in pool_descriptions:
            department, source_type = split_pool_key(key)
            available.setdefault(department, set()).add(source_type)

        queries = []
        for department in sorted(available):
            if department not in words:
                continue
            types = [t for t in named_types if t in available[department]]
            if named_types and len(types) == 1:
                queries.append(
                    SubQuery(query=question, department=department, source_type=types[0])
                )
            else:
                queries.append(SubQuery(query=question, department=department))
        if not queries and len(named_types) == 1:
            queries.append(SubQuery(query=question, source_type=named_types[0]))
        if not queries:
            queries.append(SubQuery(query=question))
        return Plan(sub_queries=queries[:MAX_SUB_QUERIES])

    def answer(
        self, question: str, chunks: list[RetrievedChunk], history: list[Turn]
    ) -> DraftAnswer:
        self.calls.append(
            StubCall("answer", {"question": question, "chunks": chunks, "history": history})
        )
        lines = [f"Stub answer to: {question}"]
        for turn in history:
            lines.append(f"(earlier {turn.role}) {turn.text}")
        if not chunks:
            lines.append("I found nothing you have access to that answers this.")
            return DraftAnswer(text="\n".join(lines), cited=[])
        for number, chunk in enumerate(chunks, start=1):
            # Every field, so a canary anywhere in a chunk shows up in the answer too.
            lines.append(
                f"[{number}] {chunk.document_title} ({chunk.department}/{chunk.source_type.value}/"
                f"{chunk.sensitivity.value}, {chunk.link}, id {chunk.chunk_id}):\n{chunk.text}"
            )
        return DraftAnswer(text="\n".join(lines), cited=list(range(1, len(chunks) + 1)))
