"""llm: the only module that talks to a language model. Cards M3-01 (interface, stub), M3-02.

No other module imports a provider SDK (tests/test_llm.py checks). The model gets no tools.

    from app.modules.llm import get_llm

    llm = get_llm(settings)
    plan = llm.plan(question, pool_descriptions, metrics={})
    draft = llm.answer(question, chunks, history)

Adding a provider (card M3-02): write `app/modules/llm/<provider>.py` with a class implementing
`LLM` whose constructor takes `Settings`, and register it in `_PROVIDERS` and in the
`LLM_PROVIDER` setting. In it:
- pass `settings.llm_timeout_seconds` as the timeout of every request, as a total for the
  request (provider SDKs time each phase separately by default);
- turn off the SDK's own retries (`max_retries=0` for the OpenAI and Anthropic SDKs, which
  otherwise retry twice): `RetryingLLM` is the only retry, or one call becomes up to 6
  requests and the time budget below no longer holds;
- raise `LLMUnavailable` for timeouts, rate limits and server errors;
- build replies with `parse_plan(raw, pool_descriptions)` / `parse_answer` so a malformed one
  becomes `LLMBadOutput`.

Time budget: one question makes two calls, each tried at most twice, so the worst case is
4 x LLM_TIMEOUT_SECONDS + 2 x 0.5 s = 33 s with the defaults, under the UI's 60 s
API_TIMEOUT_SECONDS. The chat endpoint (card M3-05) passes `deadline=` (a `time.monotonic()`
value) to both calls: a retry, or a call, that couldn't finish in time is skipped and raises
LLMUnavailable instead. It must call these blocking methods from a normal `def` endpoint,
never inside `async def`, and should get the model through a FastAPI dependency that tests
override with a `StubLLM`, or `RetryingLLM(StubLLM())` to keep the retry behaviour (one per
test: a stub keeps every call it receives).
"""

import logging
import time
from collections.abc import Callable
from typing import TypeVar

from app.config import Settings
from app.modules.llm.base import (
    LLM,
    DraftAnswer,
    LLMBadOutput,
    LLMError,
    LLMUnavailable,
    Plan,
    Turn,
)
from app.modules.llm.stub import StubLLM
from app.modules.retrieval.gateway import RetrievedChunk

__all__ = ["LLM", "LLMBadOutput", "LLMError", "LLMUnavailable", "RetryingLLM", "Turn", "get_llm"]

log = logging.getLogger(__name__)
T = TypeVar("T")


class RetryingLLM:
    """Wraps a provider; retries a call once, after a short pause, if it raises LLMUnavailable.

    With `deadline` (a `time.monotonic()` value), an attempt is only started if a whole request
    (`timeout_seconds`) still fits before it; otherwise LLMUnavailable is raised without calling
    the provider, so the chat request can give up in time instead of overrunning the UI.
    """

    def __init__(
        self,
        inner: LLM,
        attempts: int = 2,
        pause_seconds: float = 0.5,
        timeout_seconds: float = 8.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if attempts < 1:
            raise ValueError("attempts must be at least 1")
        self.inner = inner
        self.attempts = attempts
        self.pause_seconds = pause_seconds
        self.timeout_seconds = timeout_seconds
        self._clock = clock

    def plan(
        self,
        question: str,
        pool_descriptions: dict[str, str],
        metrics: dict[str, str],
        *,
        deadline: float | None = None,
    ) -> Plan:
        return self._call(
            "plan",
            lambda: self.inner.plan(question, pool_descriptions, metrics, deadline=deadline),
            deadline,
        )

    def answer(
        self,
        question: str,
        chunks: list[RetrievedChunk],
        history: list[Turn],
        *,
        deadline: float | None = None,
    ) -> DraftAnswer:
        return self._call(
            "answer",
            lambda: self.inner.answer(question, chunks, history, deadline=deadline),
            deadline,
        )

    def _fits(self, deadline: float | None, wait: float = 0.0) -> bool:
        return deadline is None or self._clock() + wait + self.timeout_seconds <= deadline

    def _call(self, operation: str, call: Callable[[], T], deadline: float | None) -> T:
        if not self._fits(deadline):
            raise LLMUnavailable(f"no time left for the LLM {operation} call")
        attempt = 1
        while True:
            try:
                return call()
            except LLMUnavailable as exc:
                if attempt >= self.attempts or not self._fits(deadline, self.pause_seconds):
                    raise
                # Never log the question, chunks or error text: they may contain document text.
                log.warning(
                    "LLM %s unavailable, retrying",
                    operation,
                    extra={"attempt": attempt, "error": type(exc).__name__},
                )
                time.sleep(self.pause_seconds)
                attempt += 1


_PROVIDERS: dict[str, Callable[[Settings], LLM]] = {
    "stub": lambda settings: StubLLM(),
}


def get_llm(settings: Settings) -> LLM:
    """The model chosen by LLM_PROVIDER, wrapped so each call is retried once."""
    return RetryingLLM(
        _PROVIDERS[settings.llm_provider](settings), timeout_seconds=settings.llm_timeout_seconds
    )
