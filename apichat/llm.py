"""Streaming clients for OpenAI-compatible, Anthropic and Gemini APIs."""

from __future__ import annotations

import json
import threading
from typing import Callable, Iterable
from urllib.parse import quote

import httpx

from .models import CompletionResult, Provider
from .tokens import estimate_tokens


class LLMError(RuntimeError):
    """An error suitable for showing directly in the UI."""


class LLMCancelled(LLMError):
    pass


DEFAULT_BASE_URLS = {
    "openai": "https://api.openai.com/v1",
    "anthropic": "https://api.anthropic.com/v1",
    "gemini": "https://generativelanguage.googleapis.com/v1beta",
}

TIMEOUT = httpx.Timeout(connect=20.0, read=300.0, write=60.0, pool=20.0)


def _join_url(base: str, suffix: str) -> str:
    return base.rstrip("/") + "/" + suffix.lstrip("/")


def _endpoint(provider: Provider) -> str:
    base = (provider.base_url or DEFAULT_BASE_URLS.get(provider.provider, "")).strip()
    if not base:
        raise LLMError("请先在 API 管理中填写接口地址（Base URL）。")
    if provider.provider == "anthropic":
        if base.rstrip("/").endswith("/messages"):
            return base.rstrip("/")
        return _join_url(base, "messages")
    if base.rstrip("/").endswith("/chat/completions"):
        return base.rstrip("/")
    return _join_url(base, "chat/completions")


def _normalise_usage(raw: dict | None) -> tuple[int, int, int]:
    if not raw:
        return 0, 0, 0
    prompt = raw.get("prompt_tokens")
    if prompt is None:
        prompt = raw.get("input_tokens")
    completion = raw.get("completion_tokens")
    if completion is None:
        completion = raw.get("output_tokens")
    total = raw.get("total_tokens")
    prompt = int(prompt or 0)
    completion = int(completion or 0)
    total = int(total or prompt + completion)
    return prompt, completion, total


def _extract_text(value) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        pieces: list[str] = []
        for item in value:
            if isinstance(item, str):
                pieces.append(item)
            elif isinstance(item, dict):
                if isinstance(item.get("text"), str):
                    pieces.append(item["text"])
                elif "content" in item:
                    pieces.append(_extract_text(item["content"]))
        return "".join(pieces)
    return ""


def _error_detail(response: httpx.Response) -> str:
    text = ""
    try:
        text = response.read().decode("utf-8", errors="replace")
    except Exception:
        try:
            text = response.text
        except Exception:
            pass
    message = ""
    if text:
        try:
            data = response.json()
            if isinstance(data, dict):
                error = data.get("error")
                if isinstance(error, dict):
                    message = str(error.get("message") or error.get("type") or "")
                elif isinstance(error, str):
                    message = error
                if not message:
                    message = str(data.get("message") or "")
        except Exception:
            message = text.strip()
    message = (message or "").strip()
    if len(message) > 900:
        message = message[:900] + "…"
    status = response.status_code
    hints = {
        400: "请求参数被服务端拒绝，请检查模型名称、接口地址或参数。",
        401: "认证失败，请检查 API Key。",
        403: "访问被拒绝，请检查 API Key 的权限或余额。",
        404: "接口或模型不存在，请检查 Base URL 和模型名称。",
        408: "服务端请求超时，请稍后重试。",
        413: "请求内容过长，超出服务端限制。",
        429: "请求过于频繁或额度不足，请稍后重试。",
    }
    hint = hints.get(status, "服务端返回错误。" if status < 500 else "服务端暂时不可用，请稍后重试。")
    parts = [f"{hint}（HTTP {status}）"]
    if message:
        parts.append(message)
    return "\n\n".join(parts)


def _raise_for_status(response: httpx.Response) -> None:
    if response.status_code >= 400:
        raise LLMError(_error_detail(response))


def _request_headers(provider: Provider) -> dict[str, str]:
    headers = {
        "Content-Type": "application/json",
        "Accept": "text/event-stream, application/json",
        "User-Agent": "API-Chat/1.0",
    }
    if provider.api_key:
        if provider.provider == "openai":
            headers["Authorization"] = f"Bearer {provider.api_key}"
            # Harmless for OpenAI/DeepSeek; useful for OpenRouter rankings.
            headers.setdefault("X-Title", "API Chat")
        elif provider.provider == "anthropic":
            headers["x-api-key"] = provider.api_key
            headers["anthropic-version"] = "2023-06-01"
        elif provider.provider == "gemini":
            headers["x-goog-api-key"] = provider.api_key
    elif provider.provider == "anthropic":
        headers["anthropic-version"] = "2023-06-01"
    return headers


def _openai_messages(provider: Provider, messages: Iterable[dict]) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    if provider.system_prompt.strip():
        result.append({"role": "system", "content": provider.system_prompt.strip()})
    for message in messages:
        role = message.get("role")
        if role not in ("user", "assistant", "system"):
            continue
        content = message.get("content") or ""
        if content:
            result.append({"role": role, "content": content})
    return result


def _anthropic_payload(
    provider: Provider,
    messages: Iterable[dict],
    stream: bool,
    max_tokens: int,
    temperature: float,
) -> dict:
    converted: list[dict[str, str]] = []
    for message in messages:
        role = message.get("role")
        content = message.get("content") or ""
        if role in ("user", "assistant") and content:
            converted.append({"role": role, "content": content})
    payload: dict = {
        "model": provider.model,
        "max_tokens": max(1, max_tokens),
        "temperature": temperature,
        "messages": converted,
        "stream": stream,
    }
    if provider.system_prompt.strip():
        payload["system"] = provider.system_prompt.strip()
    return payload


def _gemini_url(provider: Provider, stream: bool) -> str:
    base = (provider.base_url or DEFAULT_BASE_URLS["gemini"]).strip().rstrip("/")
    model = provider.model.strip()
    if model.startswith("models/"):
        model = model[len("models/") :]
    if not model:
        raise LLMError("请先填写模型名称。")
    if "/models/" in base:
        endpoint = f"{base}:{'streamGenerateContent' if stream else 'generateContent'}"
    else:
        endpoint = f"{base}/models/{quote(model, safe='')}:{'streamGenerateContent' if stream else 'generateContent'}"
    if stream:
        endpoint += "?alt=sse"
    return endpoint


def _gemini_payload(
    provider: Provider, messages: Iterable[dict], max_tokens: int, temperature: float
) -> dict:
    contents: list[dict] = []
    for message in messages:
        role = message.get("role")
        content = message.get("content") or ""
        if role not in ("user", "assistant") or not content:
            continue
        contents.append(
            {"role": "model" if role == "assistant" else "user", "parts": [{"text": content}]}
        )
    payload: dict = {
        "contents": contents,
        "generationConfig": {
            "temperature": temperature,
            "maxOutputTokens": max(1, max_tokens),
        },
    }
    if provider.system_prompt.strip():
        payload["systemInstruction"] = {
            "parts": [{"text": provider.system_prompt.strip()}]
        }
    return payload


class LLMClient:
    """One-shot client bound to a provider configuration."""

    def __init__(self, provider: Provider) -> None:
        self.provider = provider

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------
    def stream_chat(
        self,
        messages: list[dict],
        on_delta: Callable[[str], None],
        cancel_event: threading.Event | None = None,
        *,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> CompletionResult:
        provider = self.provider
        if not provider.model.strip():
            raise LLMError("请先在 API 管理中填写模型名称。")
        max_tokens = int(max_tokens or provider.max_output_tokens or 4096)
        temperature = float(provider.temperature if temperature is None else temperature)

        if provider.provider == "anthropic":
            return self._stream_anthropic(messages, on_delta, cancel_event, max_tokens, temperature)
        if provider.provider == "gemini":
            return self._stream_gemini(messages, on_delta, cancel_event, max_tokens, temperature)
        return self._stream_openai(messages, on_delta, cancel_event, max_tokens, temperature)

    def complete(
        self,
        messages: list[dict],
        *,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> CompletionResult:
        provider = self.provider
        if not provider.model.strip():
            raise LLMError("请先在 API 管理中填写模型名称。")
        max_tokens = int(max_tokens or provider.max_output_tokens or 4096)
        temperature = float(provider.temperature if temperature is None else temperature)
        if provider.provider == "anthropic":
            return self._complete_anthropic(messages, max_tokens, temperature)
        if provider.provider == "gemini":
            return self._complete_gemini(messages, max_tokens, temperature)
        return self._complete_openai(messages, max_tokens, temperature)

    # ------------------------------------------------------------------
    # OpenAI-compatible
    # ------------------------------------------------------------------
    def _openai_body(
        self, messages: list[dict], stream: bool, max_tokens: int, temperature: float
    ) -> dict:
        body: dict = {
            "model": self.provider.model,
            "messages": _openai_messages(self.provider, messages),
            "temperature": temperature,
            "stream": stream,
        }
        if max_tokens:
            body["max_tokens"] = max(1, int(max_tokens))
        if stream:
            body["stream_options"] = {"include_usage": True}
        return body

    def _post_stream(self, url: str, body: dict) -> httpx.Response:
        client = httpx.Client(timeout=TIMEOUT, follow_redirects=True, trust_env=True)
        try:
            request = client.build_request(
                "POST", url, headers=_request_headers(self.provider), json=body
            )
            response = client.send(request, stream=True)
            _raise_for_status(response)
            return _StreamResponse(client, response)
        except LLMError:
            client.close()
            raise
        except httpx.TimeoutException as exc:
            client.close()
            raise LLMError("连接模型接口超时，请检查网络、代理或稍后重试。") from exc
        except httpx.HTTPError as exc:
            client.close()
            raise LLMError(f"无法连接模型接口：{exc}") from exc

    def _stream_openai(
        self,
        messages: list[dict],
        on_delta: Callable[[str], None],
        cancel_event: threading.Event | None,
        max_tokens: int,
        temperature: float,
    ) -> CompletionResult:
        url = _endpoint(self.provider)
        body = self._openai_body(messages, True, max_tokens, temperature)
        try:
            handle = self._post_stream(url, body)
        except LLMError as exc:
            # A few OpenAI-compatible servers reject stream_options. Retry
            # once without it so older gateways still work.
            detail = str(exc).lower()
            if "stream_options" in body and (
                "stream_options" in detail or "http 400" in detail or "http 422" in detail
            ):
                body.pop("stream_options", None)
                try:
                    handle = self._post_stream(url, body)
                except LLMError:
                    raise exc
            else:
                raise
        try:
            content_type = handle.response.headers.get("content-type", "").lower()
            if "application/json" in content_type and "event-stream" not in content_type:
                data = handle.response.read()
                payload = json.loads(data.decode("utf-8", errors="replace"))
                if payload.get("error"):
                    raise LLMError(_payload_error(payload))
                content = _openai_json_content(payload)
                prompt, completion, total = _normalise_usage(payload.get("usage"))
                if prompt == 0 and completion == 0:
                    prompt = _estimate_prompt(self.provider, messages)
                    completion = estimate_tokens(content)
                    total = prompt + completion
                return CompletionResult(
                    content=content,
                    prompt_tokens=prompt,
                    completion_tokens=completion,
                    total_tokens=total,
                    model=str(payload.get("model") or self.provider.model),
                    finish_reason=_openai_finish_reason(payload),
                    raw_usage=payload.get("usage") or {},
                )

            parts: list[str] = []
            usage_raw: dict = {}
            finish_reason = ""
            model = self.provider.model
            for line in handle.iter_lines():
                if cancel_event is not None and cancel_event.is_set():
                    return self._partial(parts, usage_raw, model, finish_reason, cancelled=True)
                line = line.strip()
                if not line or line.startswith(":"):
                    continue
                data = line[5:].strip() if line.startswith("data:") else line
                if data == "[DONE]":
                    break
                try:
                    payload = json.loads(data)
                except json.JSONDecodeError:
                    continue
                if not isinstance(payload, dict):
                    continue
                if payload.get("error"):
                    raise LLMError(_payload_error(payload))
                if payload.get("usage"):
                    usage_raw = payload["usage"]
                model = str(payload.get("model") or model)
                choices = payload.get("choices") or []
                for choice in choices:
                    finish_reason = str(choice.get("finish_reason") or finish_reason)
                    delta = choice.get("delta") or {}
                    text = _extract_text(delta.get("content"))
                    if not text and choice.get("text"):
                        text = str(choice["text"])
                    if text:
                        parts.append(text)
                        on_delta(text)
            content = "".join(parts)
            if not content:
                # Some gateways ignore stream=true and return a normal JSON body.
                if usage_raw:
                    pass
                raise LLMError("模型没有返回文本内容，请检查模型名称或稍后重试。")
            return self._partial(parts, usage_raw, model, finish_reason)
        finally:
            handle.close()

    def _complete_openai(
        self, messages: list[dict], max_tokens: int, temperature: float
    ) -> CompletionResult:
        url = _endpoint(self.provider)
        body = self._openai_body(messages, False, max_tokens, temperature)
        data = self._post_json(url, body)
        content = _openai_json_content(data)
        prompt, completion, total = _normalise_usage(data.get("usage"))
        if prompt == 0 and completion == 0:
            prompt = _estimate_prompt(self.provider, messages)
            completion = estimate_tokens(content)
            total = prompt + completion
        if not content and not (data.get("choices") or []):
            raise LLMError(_payload_error(data) if data.get("error") else "模型没有返回内容。")
        return CompletionResult(
            content=content,
            prompt_tokens=prompt,
            completion_tokens=completion,
            total_tokens=total,
            model=str(data.get("model") or self.provider.model),
            finish_reason=_openai_finish_reason(data),
            raw_usage=data.get("usage") or {},
        )

    # ------------------------------------------------------------------
    # Anthropic
    # ------------------------------------------------------------------
    def _stream_anthropic(
        self,
        messages: list[dict],
        on_delta: Callable[[str], None],
        cancel_event: threading.Event | None,
        max_tokens: int,
        temperature: float,
    ) -> CompletionResult:
        body = _anthropic_payload(self.provider, messages, True, max_tokens, temperature)
        handle = self._post_stream(_endpoint(self.provider), body)
        parts: list[str] = []
        usage: dict = {}
        finish_reason = ""
        model = self.provider.model
        try:
            for line in handle.iter_lines():
                if cancel_event is not None and cancel_event.is_set():
                    return self._partial(parts, usage, model, finish_reason, cancelled=True)
                line = line.strip()
                if not line or line.startswith("event:") or line.startswith(":"):
                    continue
                data = line[5:].strip() if line.startswith("data:") else line
                try:
                    payload = json.loads(data)
                except json.JSONDecodeError:
                    continue
                if not isinstance(payload, dict):
                    continue
                event_type = payload.get("type")
                if event_type == "error":
                    raise LLMError(_payload_error(payload))
                if event_type == "message_start":
                    message = payload.get("message") or {}
                    model = str(message.get("model") or model)
                    usage.update(message.get("usage") or {})
                elif event_type == "content_block_delta":
                    delta = payload.get("delta") or {}
                    text = delta.get("text") if delta.get("type") == "text_delta" else None
                    if text:
                        parts.append(text)
                        on_delta(text)
                elif event_type == "message_delta":
                    usage.update(payload.get("usage") or {})
                    finish_reason = str((payload.get("delta") or {}).get("stop_reason") or finish_reason)
                elif event_type == "message_stop":
                    break
            content = "".join(parts)
            if not content:
                raise LLMError("模型没有返回文本内容，请检查模型名称或稍后重试。")
            prompt = int(usage.get("input_tokens") or 0)
            completion = int(usage.get("output_tokens") or 0)
            if not prompt and not completion:
                prompt = _estimate_prompt(self.provider, messages)
                completion = estimate_tokens(content)
            return CompletionResult(
                content=content,
                prompt_tokens=prompt,
                completion_tokens=completion,
                total_tokens=prompt + completion,
                model=model,
                finish_reason=finish_reason,
                raw_usage=usage,
            )
        finally:
            handle.close()

    def _complete_anthropic(
        self, messages: list[dict], max_tokens: int, temperature: float
    ) -> CompletionResult:
        body = _anthropic_payload(self.provider, messages, False, max_tokens, temperature)
        data = self._post_json(_endpoint(self.provider), body)
        content = "".join(
            block.get("text", "")
            for block in (data.get("content") or [])
            if isinstance(block, dict) and block.get("type") == "text"
        )
        usage = data.get("usage") or {}
        prompt, completion, total = _normalise_usage(usage)
        if not prompt and not completion:
            prompt = _estimate_prompt(self.provider, messages)
            completion = estimate_tokens(content)
            total = prompt + completion
        return CompletionResult(
            content=content,
            prompt_tokens=prompt,
            completion_tokens=completion,
            total_tokens=total,
            model=str(data.get("model") or self.provider.model),
            finish_reason=str(data.get("stop_reason") or ""),
            raw_usage=usage,
        )

    # ------------------------------------------------------------------
    # Gemini
    # ------------------------------------------------------------------
    def _stream_gemini(
        self,
        messages: list[dict],
        on_delta: Callable[[str], None],
        cancel_event: threading.Event | None,
        max_tokens: int,
        temperature: float,
    ) -> CompletionResult:
        body = _gemini_payload(self.provider, messages, max_tokens, temperature)
        handle = self._post_stream(_gemini_url(self.provider, True), body)
        parts: list[str] = []
        usage: dict = {}
        finish_reason = ""
        model = self.provider.model
        try:
            content_type = handle.response.headers.get("content-type", "").lower()
            if "application/json" in content_type and "event-stream" not in content_type:
                raw = handle.response.read()
                payload = json.loads(raw.decode("utf-8", errors="replace"))
                chunks = payload if isinstance(payload, list) else [payload]
                for chunk in chunks:
                    text, usage, finish_reason = _consume_gemini_chunk(
                        chunk, usage, finish_reason
                    )
                    if text:
                        parts.append(text)
                        on_delta(text)
            else:
                for line in handle.iter_lines():
                    if cancel_event is not None and cancel_event.is_set():
                        return self._partial(parts, usage, model, finish_reason, cancelled=True)
                    line = line.strip()
                    if not line or line.startswith(":"):
                        continue
                    data = line[5:].strip() if line.startswith("data:") else line
                    if data == "[DONE]":
                        break
                    try:
                        payload = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    chunks = payload if isinstance(payload, list) else [payload]
                    for chunk in chunks:
                        if chunk.get("error"):
                            raise LLMError(_payload_error(chunk))
                        text, usage, finish_reason = _consume_gemini_chunk(
                            chunk, usage, finish_reason
                        )
                        if text:
                            parts.append(text)
                            on_delta(text)
            content = "".join(parts)
            if not content:
                raise LLMError("模型没有返回文本内容，请检查模型名称或稍后重试。")
            prompt = int(usage.get("promptTokenCount") or 0)
            completion = int(usage.get("candidatesTokenCount") or 0)
            total = int(usage.get("totalTokenCount") or prompt + completion)
            if not prompt and not completion:
                prompt = _estimate_prompt(self.provider, messages)
                completion = estimate_tokens(content)
                total = prompt + completion
            return CompletionResult(
                content=content,
                prompt_tokens=prompt,
                completion_tokens=completion,
                total_tokens=total,
                model=model,
                finish_reason=finish_reason,
                raw_usage=usage,
            )
        finally:
            handle.close()

    def _complete_gemini(
        self, messages: list[dict], max_tokens: int, temperature: float
    ) -> CompletionResult:
        body = _gemini_payload(self.provider, messages, max_tokens, temperature)
        data = self._post_json(_gemini_url(self.provider, False), body)
        text, usage, finish_reason = _consume_gemini_chunk(data, {}, "")
        if not text:
            prompt_feedback = data.get("promptFeedback") or {}
            if prompt_feedback.get("blockReason"):
                raise LLMError(f"Gemini 拒绝了该请求：{prompt_feedback['blockReason']}")
        prompt = int(usage.get("promptTokenCount") or 0)
        completion = int(usage.get("candidatesTokenCount") or 0)
        total = int(usage.get("totalTokenCount") or prompt + completion)
        if not prompt and not completion:
            prompt = _estimate_prompt(self.provider, messages)
            completion = estimate_tokens(text)
            total = prompt + completion
        return CompletionResult(
            content=text,
            prompt_tokens=prompt,
            completion_tokens=completion,
            total_tokens=total,
            model=self.provider.model,
            finish_reason=finish_reason,
            raw_usage=usage,
        )

    # ------------------------------------------------------------------
    # shared
    # ------------------------------------------------------------------
    def _post_json(self, url: str, body: dict) -> dict:
        try:
            with httpx.Client(timeout=TIMEOUT, follow_redirects=True, trust_env=True) as client:
                response = client.post(url, headers=_request_headers(self.provider), json=body)
                _raise_for_status(response)
                data = response.json()
        except LLMError:
            raise
        except httpx.TimeoutException as exc:
            raise LLMError("连接模型接口超时，请检查网络、代理或稍后重试。") from exc
        except httpx.HTTPError as exc:
            raise LLMError(f"无法连接模型接口：{exc}") from exc
        except ValueError as exc:
            raise LLMError("模型接口返回了无法解析的数据。") from exc
        if not isinstance(data, dict):
            raise LLMError("模型接口返回了意外的数据格式。")
        if data.get("error"):
            raise LLMError(_payload_error(data))
        return data

    def _partial(
        self,
        parts: list[str],
        usage: dict,
        model: str,
        finish_reason: str,
        *,
        cancelled: bool = False,
    ) -> CompletionResult:
        content = "".join(parts)
        prompt, completion, total = _normalise_usage(usage)
        if prompt == 0 and completion == 0:
            prompt = 0
            completion = estimate_tokens(content)
            total = completion
        result = CompletionResult(
            content=content,
            prompt_tokens=prompt,
            completion_tokens=completion,
            total_tokens=total,
            model=model or self.provider.model,
            finish_reason=finish_reason or ("cancelled" if cancelled else ""),
            raw_usage=usage,
        )
        # CompletionResult is a plain dataclass; cancellation is signalled
        # through finish_reason so the UI can label a partial answer.
        return result


class _StreamResponse:
    """Small wrapper that keeps the HTTP client alive with the response."""

    def __init__(self, client: httpx.Client, response: httpx.Response) -> None:
        self.client = client
        self.response = response

    def iter_lines(self):
        yield from self.response.iter_lines()

    def close(self) -> None:
        try:
            self.response.close()
        finally:
            self.client.close()


def _openai_json_content(payload: dict) -> str:
    choices = payload.get("choices") or []
    if not choices:
        return ""
    choice = choices[0] or {}
    message = choice.get("message") or {}
    content = _extract_text(message.get("content"))
    if not content:
        content = _extract_text(choice.get("text"))
    return content


def _openai_finish_reason(payload: dict) -> str:
    choices = payload.get("choices") or []
    if not choices:
        return ""
    return str((choices[0] or {}).get("finish_reason") or "")


def _consume_gemini_chunk(
    chunk: dict, usage: dict, finish_reason: str
) -> tuple[str, dict, str]:
    if not isinstance(chunk, dict):
        return "", usage, finish_reason
    if chunk.get("usageMetadata"):
        usage = chunk["usageMetadata"]
    candidates = chunk.get("candidates") or []
    pieces: list[str] = []
    for candidate in candidates:
        finish_reason = str(candidate.get("finishReason") or finish_reason)
        content = candidate.get("content") or {}
        for part in content.get("parts") or []:
            if not isinstance(part, dict) or part.get("thought"):
                continue
            text = part.get("text")
            if isinstance(text, str):
                pieces.append(text)
    return "".join(pieces), usage, finish_reason


def _estimate_prompt(provider: Provider, messages: list[dict]) -> int:
    total = estimate_tokens(provider.system_prompt)
    for message in messages:
        total += estimate_tokens(message.get("content") or "") + 5
    return total


def _payload_error(payload: dict) -> str:
    error = payload.get("error")
    if isinstance(error, dict):
        message = error.get("message") or error.get("type") or json.dumps(error, ensure_ascii=False)
        return f"模型接口返回错误：{message}"
    if isinstance(error, str):
        return f"模型接口返回错误：{error}"
    message = payload.get("message")
    if message:
        return f"模型接口返回错误：{message}"
    return "模型接口返回错误。"


def title_messages(conversation_messages: list[dict]) -> list[dict]:
    """Build a compact title-generation request from the first exchanges."""
    lines: list[str] = []
    for message in conversation_messages[:6]:
        role = "用户" if message.get("role") == "user" else "助手"
        content = (message.get("content") or "").strip()
        if content:
            lines.append(f"{role}：{content[:600]}")
    transcript = "\n\n".join(lines)
    system = (
        "你是对话标题生成器。请根据对话内容生成一个简洁、具体的中文标题，"
        "概括主题，不超过 18 个汉字；如果对话主要是英文，可以用英文。"
        "只输出标题本身，不要引号、不要标点结尾、不要解释。"
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": f"对话内容：\n{transcript}\n\n请只输出标题。"},
    ]


def clean_title(raw: str, fallback: str = "新对话") -> str:
    title = (raw or "").strip().splitlines()[0] if (raw or "").strip() else ""
    for prefix in ("标题：", "标题:", "Title:", "title:"):
        if title.startswith(prefix):
            title = title[len(prefix) :].strip()
    title = title.strip(" \t\"'“”‘’《》<>#*-—")
    title = title.rstrip("。！？!?；;，,.")
    if len(title) > 40:
        title = title[:38].rstrip() + "…"
    return title or fallback
