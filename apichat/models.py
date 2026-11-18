"""Plain data objects shared by the data, API and UI layers."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class Provider:
    id: int
    alias: str
    provider: str = "openai"
    base_url: str = ""
    api_key: str = ""
    model: str = ""
    context_window: int = 128_000
    max_output_tokens: int = 4096
    temperature: float = 0.7
    system_prompt: str = ""
    is_default: bool = False
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    @property
    def provider_label(self) -> str:
        return {
            "openai": "OpenAI 兼容",
            "anthropic": "Anthropic",
            "gemini": "Google Gemini",
        }.get(self.provider, self.provider)


@dataclass
class Conversation:
    id: int
    title: str = "新对话"
    api_id: Optional[int] = None
    title_auto: bool = True
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    last_message_at: Optional[datetime] = None
    api_alias: str = ""
    model: str = ""
    context_window: int = 128_000
    system_prompt: str = ""
    message_count: int = 0
    context_tokens: int = 0
    usage_total: int = 0
    request_count: int = 0

    @property
    def remaining_percent(self) -> float:
        from .tokens import remaining_percent

        return remaining_percent(self.context_tokens, self.context_window)


@dataclass
class Attachment:
    id: int = 0
    message_id: int = 0
    filename: str = ""
    mime_type: str = ""
    kind: str = "file"
    size_bytes: int = 0
    width: int = 0
    height: int = 0
    token_count: int = 0
    data: bytes = b""
    thumbnail: bytes = b""
    created_at: Optional[datetime] = None

    @property
    def is_image(self) -> bool:
        return self.kind == "image" or self.mime_type.startswith("image/")


@dataclass
class Message:
    id: int
    conversation_id: int
    role: str
    content: str
    reasoning_content: str = ""
    token_count: int = 0
    model: str = ""
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    usage_total: int = 0
    attachments: list[Attachment] = field(default_factory=list)

    @property
    def is_user(self) -> bool:
        return self.role == "user"


@dataclass
class CompletionResult:
    content: str
    reasoning: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    model: str = ""
    finish_reason: str = ""
    raw_usage: dict = field(default_factory=dict)


@dataclass
class DashboardRow:
    conversation_id: int
    title: str
    api_alias: str
    model: str
    message_count: int
    request_count: int
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    context_tokens: int
    context_window: int
    last_activity: Optional[datetime]
    remaining_percent: float = 0.0


@dataclass
class DashboardTotals:
    conversation_count: int = 0
    request_count: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


@dataclass
class ApiUsageRow:
    api_alias: str
    model: str
    request_count: int
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
