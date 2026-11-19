"""The fixed question-answering pipeline. Card M3-05 owns this file.

Each step is its own function so the planner (M3-03) and answer step (M3-04) can be built
separately. The LLM never chooses what runs next.
"""

from app.modules.chat.schemas import ChatRequest, ChatResponse
from app.shared.types import Principal


def answer_question(principal: Principal, request: ChatRequest) -> ChatResponse:
    # 1. Resolve scope                  policies.scope.resolve_scope      (M2-02)
    # 2. Plan                           llm.plan, then validate           (M3-03)
    # 3. Intersect plan with scope; anything outside becomes `denied`     (M3-05)
    # 4. Retrieve                       retrieval.gateway.search          (M2-07)
    # 5. Answer, verify citations       llm.answer                        (M3-04)
    # 6. Write the audit event in the same transaction                    (M3-07)
    raise NotImplementedError("Card M3-05")
