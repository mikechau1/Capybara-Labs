"""What the chat page receives. Shared contract with the UI: change both sides in one PR."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from app.shared.types import SourceType


class ChatRequest(BaseModel):
    question: str
    conversation_id: str | None = None  # None starts a new conversation


class Source(BaseModel):
    number: int  # matches [n] in the answer text
    title: str
    department: str
    source_type: SourceType
    link: str
    snippet: str


class DeniedPool(BaseModel):
    department: str
    source_type: SourceType


class ChatResponse(BaseModel):
    conversation_id: str
    # Markdown, safe to render as it is with st.markdown (chat/answering.py, card M3-04). It is
    # full of escapes and word joiners: anything else that needs the words uses
    # app.shared.answer_text.plain_text.
    answer: str
    sources: list[Source]
    denied: list[DeniedPool]  # drives "You don't have access to ..." and Request access
    status: Literal["answered", "no_access", "nothing_found"]


class ConversationSummary(BaseModel):
    id: str
    title: str
    updated_at: datetime


class Message(BaseModel):
    role: Literal["user", "assistant"]
    text: str
    sources: list[Source] = []
    denied: list[DeniedPool] = []


class Conversation(ConversationSummary):
    messages: list[Message]
