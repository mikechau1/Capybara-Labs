"""The two operations the chat pipeline needs from a model. Card M3-01 owns this file.

The pipeline (card M3-05) calls a model at exactly two points and decides everything else
itself; the model gets no tools:

- `plan`: question + the names of ALL data pools in the company (not only the user's) + the
  available ticket metrics -> up to three sub-queries saying where to look. Seeing every pool is
  what lets the pipeline tell the user "you don't have access to Finance tickets": code
  intersects the plan with the user's scope, and suggested pools outside it become the denial
  notice.
- `answer`: question + the retrieved chunks (numbered [1], [2], ...) + earlier turns -> answer
  text that cites those numbers.

What the planner may see: pool names, and a short fixed description per pool written by
developers in code (e.g. "Finance tickets: payment and vendor issues"). Never text from source
registrations, documents or any other company content, and never anything about sensitivity:
one pool name covers all sensitivities, so whatever describes it is shown to every user.

Pools are named "<department>/<source type>", e.g. "finance/tickets" (see `pool_key`). A pool
name is "in scope" for M3-05 if the user can read that department's source type at any
sensitivity (so a user with only public Finance tickets gets no denial notice for restricted
ones; M3-05 decides whether that is right).

Adapters (card M3-02) must turn model replies into `Plan` / `DraftAnswer` with `parse_plan` and
`parse_answer`, so a malformed reply always becomes `LLMBadOutput`, and must never put model
output or prompt text into exception messages (they reach the logs).

Citations: `chat/answering.py` (M3-04) parses the [n] markers from `DraftAnswer.text` and checks
each against the chunks actually sent. `cited` is only the model's own claim, a hint; never trust
it alone. What an adapter sends for `answer` is built by `llm/prompts.py` (`answer_prompt`).
"""

import re
from collections.abc import Iterable
from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field, ValidationError

from app.modules.retrieval.gateway import RetrievedChunk
from app.shared.types import SourceType

_DEPARTMENT = re.compile(r"^[a-z0-9][a-z0-9-]*$")  # the slug format departments.id enforces


def pool_key(department: str, source_type: SourceType | str) -> str:
    """The name the planner sees for one department's source type, e.g. "finance/tickets"."""
    if not _DEPARTMENT.fullmatch(department):
        raise ValueError(f"not a department id: {department!r}")
    return f"{department}/{SourceType(source_type).value}"


def split_pool_key(key: str) -> tuple[str, SourceType]:
    """The inverse of `pool_key`; raises ValueError for anything `pool_key` couldn't make."""
    department, sep, source_type = key.partition("/")
    if not sep or not _DEPARTMENT.fullmatch(department):
        raise ValueError(f"not a pool name: {key!r}")
    return department, SourceType(source_type)


class SubQuery(BaseModel):
    query: str = Field(pattern=r"\S")  # something to search for
    # None: anywhere in the user's scope. Otherwise a department id (slug), never free text.
    department: str | None = Field(default=None, pattern=_DEPARTMENT.pattern)
    source_type: SourceType | None = None  # None: every source type


class Plan(BaseModel):
    # At least one; at most three is the planner's rule to apply (card M3-03).
    sub_queries: list[SubQuery] = Field(min_length=1)
    metric: str | None = None  # name of a predefined ticket metric (card M4-08)
    metric_params: dict[str, str] = {}


class DraftAnswer(BaseModel):
    text: str  # cites chunks as [1], [2], ...; the source of truth for citations (M3-04)
    cited: list[int]  # the model's own list; a hint only


class Turn(BaseModel):
    """One earlier message in the same conversation (card M3-06)."""

    role: Literal["user", "assistant"]
    # A user turn: the question as typed. An assistant turn: the answer as stored, which is the
    # markdown of CheckedAnswer.text (card M3-04); prompts.answer_prompt turns it back into text.
    text: str


class LLMError(Exception):
    """Base class for every error a model adapter raises on purpose. Messages are fixed text:
    never include model output, prompts or document text."""


class LLMUnavailable(LLMError):
    """The provider could not answer: timeout, rate limit, server error or network failure.

    `RetryingLLM` retries these once. A second failure reaches the pipeline, which shows the
    user a clear error (card M5-03).
    """


class LLMBadOutput(LLMError):
    """The provider answered, but not in the expected shape (e.g. a plan naming an unknown
    source type). Not retried. The planner step (card M3-03) falls back to searching the raw
    question over the user's whole scope."""


def parse_plan(raw: str | dict[str, Any], pool_names: Iterable[str] | None = None) -> Plan:
    """A provider's reply (JSON text or a parsed dict) as a Plan, or LLMBadOutput.

    Pass `pool_names` (the keys of the `pool_descriptions` the model was given): a sub-query
    naming a department, or a department and source type, that isn't among them was invented
    by the model, so the plan is refused instead of becoming a spurious "no access" notice.
    """
    try:
        if isinstance(raw, str):
            plan = Plan.model_validate_json(raw)
        else:
            plan = Plan.model_validate(raw)
    except ValidationError:
        raise LLMBadOutput("the model's plan was not in the expected shape") from None
    if pool_names is not None:
        known = {split_pool_key(name) for name in pool_names}
        departments = {department for department, _ in known}
        for sub_query in plan.sub_queries:
            if sub_query.department is None:
                continue
            if sub_query.department not in departments or (
                sub_query.source_type is not None
                and (sub_query.department, sub_query.source_type) not in known
            ):
                raise LLMBadOutput("the model's plan named a pool it was not given")
    return plan


_JSON_FENCE = re.compile(r"```(?:json)?[ \t]*\n(.*)\n[ \t]*```", re.DOTALL | re.IGNORECASE)


def parse_answer(raw: str | dict[str, Any]) -> DraftAnswer:
    """A provider's reply (JSON text or a parsed dict) as a DraftAnswer, or LLMBadOutput.

    JSON text wrapped in one ```json code fence, as models often send it, is accepted."""
    try:
        if isinstance(raw, str):
            fenced = _JSON_FENCE.fullmatch(raw.strip())
            return DraftAnswer.model_validate_json(fenced.group(1) if fenced else raw)
        return DraftAnswer.model_validate(raw)
    except ValidationError:
        raise LLMBadOutput("the model's answer was not in the expected shape") from None


class LLM(Protocol):
    """Every implementation takes `deadline` (a `time.monotonic()` value, or None): a provider
    should cap its request timeout at the time left; the stub ignores it."""

    def plan(
        self,
        question: str,
        pool_descriptions: dict[str, str],
        metrics: dict[str, str],
        *,
        deadline: float | None = None,
    ) -> Plan:
        """`pool_descriptions` maps every pool name ("finance/tickets") to its fixed
        description. `metrics` maps metric names to descriptions (empty until card M4-08)."""
        ...

    def answer(
        self,
        question: str,
        chunks: list[RetrievedChunk],
        history: list[Turn],
        *,
        deadline: float | None = None,
    ) -> DraftAnswer:
        """`chunks[i]` is cited as [i + 1]. Chunk text is untrusted data, never instructions."""
        ...
