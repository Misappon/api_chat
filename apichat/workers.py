"""QThread workers for streaming, title generation and API testing."""

from __future__ import annotations

import threading

from PySide6.QtCore import QThread, Signal

from .importer import import_from_html_file, import_from_url, parse_transcript
from .llm import LLMClient, LLMError, title_messages
from .models import CompletionResult, Provider
from .web_search import (
    WebSearchError,
    search_context,
    search_web,
    with_search_context,
)


class ChatStreamWorker(QThread):
    delta = Signal(str)
    reasoning_delta = Signal(str)
    status = Signal(str)
    succeeded = Signal(object)
    cancelled = Signal(object)
    failed = Signal(str)

    def __init__(
        self,
        provider: Provider,
        messages: list[dict],
        cancel_event: threading.Event,
        *,
        reasoning: bool = False,
        web_search: bool = False,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.provider = provider
        self.messages = messages
        self.cancel_event = cancel_event
        self.reasoning = reasoning
        self.web_search = web_search

    def _search_query(self) -> str:
        for message in reversed(self.messages):
            if message.get("role") == "user":
                return str(message.get("content") or "").strip()
        return ""

    def run(self) -> None:
        try:
            messages = self.messages
            if self.web_search:
                query = self._search_query()
                if not query:
                    self.failed.emit("在线搜索需要一条文字问题。")
                    return
                self.status.emit("正在搜索网页…")
                try:
                    results = search_web(query)
                except WebSearchError as exc:
                    self.failed.emit(f"在线搜索失败：{exc}")
                    return
                messages = with_search_context(
                    messages, query, search_context(query, results)
                )
                self.status.emit(f"已获取 {len(results)} 条搜索结果，正在请求模型…")
            if self.cancel_event.is_set():
                self.cancelled.emit(
                    CompletionResult(content="", finish_reason="cancelled")
                )
                return
            client = LLMClient(self.provider)
            result = client.stream_chat(
                messages,
                on_delta=self.delta.emit,
                cancel_event=self.cancel_event,
                reasoning=self.reasoning,
                on_reasoning=self.reasoning_delta.emit,
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


class ImportWorker(QThread):
    succeeded = Signal(object)
    failed = Signal(str)

    def __init__(
        self,
        mode: str,
        value: str,
        *,
        download_images: bool = True,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.mode = mode
        self.value = value
        self.download_images = download_images

    def run(self) -> None:
        try:
            if self.mode == "url":
                result = import_from_url(self.value, download_images=self.download_images)
            elif self.mode == "html":
                result = import_from_html_file(
                    self.value, download_images=self.download_images
                )
            else:
                result = parse_transcript(self.value)
            self.succeeded.emit(result)
        except Exception as exc:
            self.failed.emit(str(exc))


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
