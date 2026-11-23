"""llm: the only module that talks to a language model. Cards M3-01 (interface, stub), M3-02.

No other module imports a provider SDK (tests/test_llm.py checks). The model gets no tools.

    from app.modules.llm import get_llm

    llm = get_llm(settings)
    plan = llm.plan(question, pool_descriptions, metrics={})
    draft = llm.answer(question, chunks, history)

Adding a provider (card M3-02): write `app/modules/llm/<provider>.py` with a class implementing
`LLM` whose constructor takes `Settings`; use `settings.llm_timeout_seconds` for every request;
raise `LLMUnavailable` for timeouts, rate limits and server errors; build replies with
`parse_plan` / `parse_answer` so a malformed one becomes `LLMBadOutput`; register it in
`_PROVIDERS` and in the `LLM_PROVIDER` setting.

Time budget: one question makes two calls, each tried at most twice, so the worst case is
4 x LLM_TIMEOUT_SECONDS + 2 x 0.5 s = 33 s with the defaults, under the UI's 60 s
API_TIMEOUT_SECONDS. The chat endpoint (card M3-05) should still enforce an overall deadline,
and must call these blocking methods from a normal `def` endpoint, never inside `async def`.
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
    """Wraps a provider; retries a call once, after a short pause, if it raises LLMUnavailable."""

    def __init__(self, inner: LLM, attempts: int = 2, pause_seconds: float = 0.5) -> None:
        if attempts < 1:
            raise ValueError("attempts must be at least 1")
        self.inner = inner
        self.attempts = attempts
        self.pause_seconds = pause_seconds

    def plan(
        self, question: str, pool_descriptions: dict[str, str], metrics: dict[str, str]
    ) -> Plan:
        return self._call("plan", lambda: self.inner.plan(question, pool_descriptions, metrics))

    def answer(
        self, question: str, chunks: list[RetrievedChunk], history: list[Turn]
    ) -> DraftAnswer:
        return self._call("answer", lambda: self.inner.answer(question, chunks, history))

    def _call(self, operation: str, call: Callable[[], T]) -> T:
        attempt = 1
        while True:
            try:
                return call()
            except LLMUnavailable as exc:
                if attempt >= self.attempts:
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
    return RetryingLLM(_PROVIDERS[settings.llm_provider](settings))
