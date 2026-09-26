from typing import Literal

from pydantic import BaseModel, Field


class AssistantMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=4000)


class AssistantChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    # Earlier turns of this chat, oldest first; the server keeps only the
    # last few (assistant_service.MAX_HISTORY).
    history: list[AssistantMessage] = Field(default_factory=list, max_length=50)


class AssistantChatResponse(BaseModel):
    reply: str
    # True when served from the answer cache (no AI call was made).
    cached: bool = False


class AssistantSettingsOut(BaseModel):
    configured: bool
    provider: str | None = None
    # Last four characters only -- the key itself is never returned.
    key_hint: str | None = None


class AssistantSettingsUpdateRequest(BaseModel):
    # Empty or null removes the key (turns the assistant off).
    api_key: str | None = Field(default=None, max_length=500)
