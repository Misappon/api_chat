"""QThread workers for streaming, title generation and API testing."""

from __future__ import annotations

import threading

from PySide6.QtCore import QThread, Signal

from .llm import LLMClient, LLMError, title_messages
from .models import Provider


class ChatStreamWorker(QThread):
    delta = Signal(str)
    succeeded = Signal(object)
    cancelled = Signal(object)
    failed = Signal(str)

    def __init__(
        self,
        provider: Provider,
        messages: list[dict],
        cancel_event: threading.Event,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.provider = provider
        self.messages = messages
        self.cancel_event = cancel_event

    def run(self) -> None:
        try:
            client = LLMClient(self.provider)
            result = client.stream_chat(
                self.messages,
                on_delta=self.delta.emit,
                cancel_event=self.cancel_event,
            )
            if result.finish_reason == "cancelled":
                self.cancelled.emit(result)
            else:
                self.succeeded.emit(result)
        except LLMError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:
            self.failed.emit(f"生成回复时发生未预期的错误：{exc}")


class TitleWorker(QThread):
    succeeded = Signal(int, object)
    failed = Signal(int, str)

    def __init__(self, conversation_id: int, provider: Provider, messages: list[dict], parent=None) -> None:
        super().__init__(parent)
        self.conversation_id = conversation_id
        self.provider = provider
        self.messages = messages

    def run(self) -> None:
        try:
            client = LLMClient(self.provider)
            request = title_messages(self.messages)
            result = client.complete(request, max_tokens=80, temperature=0.2)
            self.succeeded.emit(self.conversation_id, result)
        except Exception as exc:
            self.failed.emit(self.conversation_id, str(exc))


class ApiTestWorker(QThread):
    succeeded = Signal(str)
    failed = Signal(str)

    def __init__(self, provider: Provider, parent=None) -> None:
        super().__init__(parent)
        self.provider = provider

    def run(self) -> None:
        try:
            client = LLMClient(self.provider)
            result = client.complete(
                [{"role": "user", "content": "Reply with exactly: OK"}],
                max_tokens=12,
                temperature=0.0,
            )
            text = (result.content or "").strip()
            self.succeeded.emit(
                f"连接成功 · {result.model or self.provider.model}"
                + (f"\n模型回复：{text[:120]}" if text else "")
            )
        except Exception as exc:
            self.failed.emit(str(exc))
