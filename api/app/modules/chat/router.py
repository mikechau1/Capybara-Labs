from fastapi import APIRouter

from app.modules.auth.dependencies import CurrentUser
from app.modules.chat.schemas import ChatRequest, ChatResponse, Conversation, ConversationSummary
from app.shared.errors import not_implemented

router = APIRouter(tags=["chat"])

# ---- Ask a question: card M3-05 ------------------------------------------------------------


@router.post("/chat", response_model=ChatResponse)
def chat(body: ChatRequest, user: CurrentUser) -> ChatResponse:
    raise not_implemented("M3-05")


# ---- Conversations: card M3-06 -------------------------------------------------------------


@router.get("/conversations", response_model=list[ConversationSummary])
def list_conversations(user: CurrentUser) -> list[ConversationSummary]:
    raise not_implemented("M3-06")


@router.get("/conversations/{conversation_id}", response_model=Conversation)
def get_conversation(conversation_id: str, user: CurrentUser) -> Conversation:
    raise not_implemented("M3-06")
