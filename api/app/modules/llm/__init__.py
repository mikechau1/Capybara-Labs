"""llm: the only module that talks to a language model. Cards M3-01 (interface, stub), M3-02.

No other module imports a provider SDK. The model gets no tools.
"""

from app.config import Settings
from app.modules.llm.base import LLM


def get_llm(settings: Settings) -> LLM:
    # TODO(M3-01): return StubLLM for "stub"; card M3-02 adds the real provider.
    raise NotImplementedError("Card M3-01")
