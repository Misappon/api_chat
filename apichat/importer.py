"""Import public web-share conversations into the local chat format.

The importer intentionally accepts three sources:

* a public share URL (fetched server-side and parsed)
* a saved HTML file
* pasted transcript text with User:/Assistant: markers

Share pages change frequently, so parsing combines embedded JSON, known DOM
selectors for ChatGPT/Claude and a conservative transcript fallback.
"""

from __future__ import annotations

import base64
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Optional
from urllib.parse import unquote, urlencode, urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from .models import Attachment

MAX_PAGE_BYTES = 20 * 1024 * 1024
MAX_IMPORTED_MESSAGES = 300
MAX_IMPORTED_IMAGES = 20
MAX_IMAGE_BYTES = 8 * 1024 * 1024
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
ROLE_MARKERS = {
    "you": "user",
    "user": "user",
    "human": "user",
    "me": "user",
    "我": "user",
    "用户": "user",
    "assistant": "assistant",
    "chatgpt": "assistant",
    "claude": "assistant",
    "gemini": "assistant",
    "deepseek": "assistant",
    "ai": "assistant",
    "bot": "assistant",
    "模型": "assistant",
    "助手": "assistant",
}
NOISE_LINES = {
    "copy",
    "copy code",
    "edit",
    "regenerate",
    "regenerate response",
    "share",
    "like",
    "dislike",
    "read aloud",
    "复制",
    "编辑",
    "重新生成",
    "分享",
}


class ImportError(RuntimeError):
    """Import failed with a user-facing explanation."""


@dataclass
class ImportedMessage:
    role: str
    content: str
    image_urls: list[str] = field(default_factory=list)
    attachments: list[Attachment] = field(default_factory=list)


@dataclass
class ImportedConversation:
    title: str
    messages: list[ImportedMessage]
    source: str = ""
    warnings: list[str] = field(default_factory=list)

    @property
    def image_count(self) -> int:
        return sum(len(message.attachments) for message in self.messages)


def _clean_title(value: str, fallback: str = "导入的对话") -> str:
    value = re.sub(r"\s+", " ", (value or "")).strip()
    value = re.sub(
        r"\s*[|·\-–—]\s*(ChatGPT|Claude|Gemini|Google Gemini|OpenAI|DeepSeek).*$",
        "",
        value,
        flags=re.IGNORECASE,
    )
    value = value.strip(" -_|·")
    if len(value) > 60:
        value = value[:58].rstrip() + "…"
    return value or fallback


def _clean_text(value: str) -> str:
    lines = [line.strip() for line in (value or "").replace("\r", "").split("\n")]
    cleaned = [line for line in lines if line.lower() not in NOISE_LINES]
    text = "\n".join(cleaned)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    text = re.sub(
        r"^(You said|ChatGPT said|Claude said|Gemini said|DeepSeek said)\s*[:：]\s*",
        "",
        text,
    )
    return text.strip()


def _role_from_value(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    key = value.strip().lower()
    if key in ROLE_MARKERS:
        return ROLE_MARKERS[key]
    return None


def _is_message_dict(node: dict) -> bool:
    if not isinstance(node, dict):
        return False
    if isinstance(node.get("message"), dict):
        node = node["message"]
    role = (
        node.get("role")
        or node.get("sender")
        or node.get("speaker")
        or (node.get("author") or {}).get("role")
    )
    if not _role_from_value(role):
        return False
    return any(
        key in node
        for key in ("content", "text", "parts", "message", "body", "markdown")
    )


def _normalise_message(node: dict) -> Optional[ImportedMessage]:
    if not isinstance(node, dict):
        return None
    if isinstance(node.get("message"), dict):
        node = node["message"]
    author = node.get("author") if isinstance(node.get("author"), dict) else {}
    role = _role_from_value(
        node.get("role")
        or node.get("sender")
        or node.get("speaker")
        or author.get("role")
    )
    if role not in ("user", "assistant"):
        return None
    text_parts: list[str] = []
    images: list[str] = []
    content = node.get("content", node.get("text", node.get("body", node.get("markdown", ""))))
    if isinstance(content, str):
        text_parts.append(content)
    elif isinstance(content, dict):
        parts = content.get("parts")
        if isinstance(parts, list):
            for part in parts:
                if isinstance(part, str):
                    text_parts.append(part)
                elif isinstance(part, dict):
                    if part.get("type") in ("image", "image_url"):
                        _collect_image_value(part, images)
                    elif isinstance(part.get("text"), str):
                        text_parts.append(part["text"])
        elif isinstance(content.get("text"), str):
            text_parts.append(content["text"])
        elif isinstance(content.get("content"), str):
            text_parts.append(content["content"])
    elif isinstance(content, list):
        for part in content:
            if isinstance(part, str):
                text_parts.append(part)
            elif isinstance(part, dict):
                if part.get("type") in ("image", "image_url", "input_image"):
                    _collect_image_value(part, images)
                elif isinstance(part.get("text"), str):
                    text_parts.append(part["text"])
                elif isinstance(part.get("content"), str):
                    text_parts.append(part["content"])
    if isinstance(node.get("parts"), list):
        for part in node["parts"]:
            if isinstance(part, str):
                text_parts.append(part)
            elif isinstance(part, dict) and isinstance(part.get("text"), str):
                text_parts.append(part["text"])
    for key in ("image_url", "image", "url"):
        value = node.get(key)
        if isinstance(value, str) and _looks_like_image_url(value):
            images.append(value)
    if isinstance(node.get("attachments"), list):
        for attachment in node["attachments"]:
            if isinstance(attachment, dict):
                _collect_image_value(attachment, images)
    text = _clean_text("\n".join(part for part in text_parts if part))
    images = list(dict.fromkeys(images))
    if not text and not images:
        return None
    return ImportedMessage(role=role, content=text, image_urls=images)


def _collect_image_value(value: dict, images: list[str]) -> None:
    for key in ("url", "src", "image_url", "imageUrl"):
        item = value.get(key)
        if isinstance(item, str) and _looks_like_image_url(item):
            images.append(item)
        elif isinstance(item, dict):
            nested = item.get("url") or item.get("src")
            if isinstance(nested, str) and _looks_like_image_url(nested):
                images.append(nested)
    source = value.get("source")
    if isinstance(source, dict) and source.get("type") == "base64":
        data = source.get("data")
        media_type = source.get("media_type") or "image/png"
        if isinstance(data, str):
            images.append(f"data:{media_type};base64,{data}")


def _looks_like_image_url(value: str) -> bool:
    if value.startswith("data:image/"):
        return True
    if not value.startswith(("http://", "https://", "/")):
        return False
    path = urlparse(value).path.lower()
    if path.endswith((".svg", ".ico")):
        return False
    return path.endswith((".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp")) or "/image" in path


def _dedupe(messages: Iterable[ImportedMessage]) -> list[ImportedMessage]:
    result: list[ImportedMessage] = []
    for message in messages:
        if not message.content and not message.image_urls:
            continue
        if result and result[-1].role == message.role and result[-1].content == message.content:
            if message.image_urls:
                result[-1].image_urls = list(
                    dict.fromkeys(result[-1].image_urls + message.image_urls)
                )
            continue
        result.append(message)
        if len(result) >= MAX_IMPORTED_MESSAGES:
            break
    return result


def _walk_lists(value: Any, depth: int = 0) -> Iterable[list]:
    if depth > 20:
        return
    if isinstance(value, list):
        if any(_is_message_dict(item) for item in value if isinstance(item, dict)):
            yield value
        for item in value:
            yield from _walk_lists(item, depth + 1)
    elif isinstance(value, dict):
        for item in value.values():
            yield from _walk_lists(item, depth + 1)


def _find_title(value: Any, depth: int = 0) -> str:
    if depth > 8:
        return ""
    if isinstance(value, dict):
        for key in ("title", "conversation_title", "name"):
            item = value.get(key)
            if isinstance(item, str) and 2 <= len(item.strip()) <= 120:
                candidate = _clean_title(item, "")
                if candidate and candidate.lower() not in {"chatgpt", "claude", "gemini"}:
                    return candidate
        for item in value.values():
            title = _find_title(item, depth + 1)
            if title:
                return title
    elif isinstance(value, list):
        for item in value[:20]:
            title = _find_title(item, depth + 1)
            if title:
                return title
    return ""


def _find_mapping(value: Any, depth: int = 0) -> Optional[dict]:
    if depth > 10:
        return None
    if isinstance(value, dict):
        mapping = value.get("mapping")
        if isinstance(mapping, dict):
            return mapping
        for item in value.values():
            found = _find_mapping(item, depth + 1)
            if found is not None:
                return found
    elif isinstance(value, list):
        for item in value[:50]:
            found = _find_mapping(item, depth + 1)
            if found is not None:
                return found
    return None


def _chatgpt_mapping_messages(data: dict) -> list[ImportedMessage]:
    mapping = _find_mapping(data)
    if not isinstance(mapping, dict):
        return []
    rows: list[tuple[float, ImportedMessage]] = []
    for node in mapping.values():
        if not isinstance(node, dict):
            continue
        message = node.get("message")
        if not isinstance(message, dict):
            continue
        normalised = _normalise_message(message)
        if normalised is None:
            continue
        created = message.get("create_time")
        try:
            order = float(created)
        except (TypeError, ValueError):
            order = 0.0
        rows.append((order, normalised))
    if not rows:
        return []
    if any(order for order, _ in rows):
        rows.sort(key=lambda item: item[0])
    return [message for _, message in rows]


def _parse_payload(data: Any, source: str) -> ImportedConversation | None:
    if isinstance(data, dict):
        mapping_messages = _chatgpt_mapping_messages(data)
        if mapping_messages:
            messages = _dedupe(mapping_messages)
            if messages:
                return ImportedConversation(
                    title=_find_title(data) or _fallback_title(messages),
                    messages=messages,
                    source=source,
                )
    candidates: list[tuple[int, list[ImportedMessage]]] = []
    for sequence in _walk_lists(data):
        normalised = [
            message
            for item in sequence
            if isinstance(item, dict)
            if (message := _normalise_message(item)) is not None
        ]
        messages = _dedupe(normalised)
        if not messages:
            continue
        roles = {message.role for message in messages}
        score = len(messages) + (20 if len(roles) == 2 else 0)
        candidates.append((score, messages))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0], reverse=True)
    messages = candidates[0][1]
    return ImportedConversation(
        title=_find_title(data) or _fallback_title(messages),
        messages=messages,
        source=source,
    )


def _fallback_title(messages: list[ImportedMessage]) -> str:
    for message in messages:
        if message.role == "user" and message.content:
            first_line = message.content.splitlines()[0].strip()
            return _clean_title(first_line[:58], "导入的对话")
    return "导入的对话"


def _extract_json_payloads(soup: BeautifulSoup) -> list[Any]:
    payloads: list[Any] = []
    for script in soup.find_all("script"):
        text = script.string or script.get_text() or ""
        if not text.strip():
            continue
        script_id = script.get("id", "")
        script_type = (script.get("type") or "").lower()
        if script_id not in {
            "__NEXT_DATA__",
            "__NUXT_DATA__",
            "__INITIAL_STATE__",
            "__APOLLO_STATE__",
        } and script_type not in {"application/json", "application/ld+json"}:
            continue
        try:
            payloads.append(json.loads(text))
        except (ValueError, TypeError):
            continue
    # Some Remix share pages assign a JSON state inline.
    for script in soup.find_all("script"):
        text = script.string or ""
        if "__remixContext" not in text and "__INITIAL_STATE__" not in text:
            continue
        match = re.search(r"=\s*(\{.*\})\s*;?\s*$", text, re.DOTALL)
        if match:
            try:
                payloads.append(json.loads(match.group(1)))
            except ValueError:
                pass
    return payloads


def _dom_messages(soup: BeautifulSoup, base_url: str) -> list[ImportedMessage]:
    selectors: list[tuple[str, Optional[str]]] = [
        ("[data-message-author-role]", None),
        ('[data-testid="user-message"]', "user"),
        ('[data-testid="assistant-message"]', "assistant"),
        (".font-claude-message", "assistant"),
        (".font-claude-response", "assistant"),
        ('[data-testid^="conversation-turn"]', None),
    ]
    for selector, fixed_role in selectors:
        elements = soup.select(selector)
        if not elements:
            continue
        messages: list[ImportedMessage] = []
        for element in elements:
            role = fixed_role
            if role is None:
                role = _role_from_value(element.get("data-message-author-role"))
            if role is None:
                nested = element.select_one("[data-message-author-role]")
                if nested is not None:
                    role = _role_from_value(nested.get("data-message-author-role"))
            if role is None:
                class_text = " ".join(element.get("class", [])).lower()
                if "user" in class_text:
                    role = "user"
                elif "assistant" in class_text or "claude" in class_text:
                    role = "assistant"
            if role not in ("user", "assistant"):
                continue
            text = _clean_text(element.get_text("\n", strip=True))
            image_urls: list[str] = []
            for image in element.select("img"):
                src = image.get("src") or image.get("data-src") or ""
                if not src:
                    continue
                if src.startswith("data:image/svg"):
                    continue
                class_text = " ".join(image.get("class", [])).lower()
                alt_text = (image.get("alt") or "").lower()
                if any(token in class_text or token in alt_text for token in ("avatar", "emoji", "icon")):
                    continue
                try:
                    width = int(str(image.get("width") or "0").replace("px", ""))
                    height = int(str(image.get("height") or "0").replace("px", ""))
                except ValueError:
                    width = height = 0
                if (width and width < 80) or (height and height < 80):
                    continue
                if not _looks_like_image_url(src) and not src.startswith("data:image/"):
                    if width < 100 or height < 100:
                        continue
                image_urls.append(urljoin(base_url, src) if not src.startswith("data:") else src)
            if text or image_urls:
                messages.append(
                    ImportedMessage(
                        role=role,
                        content=text,
                        image_urls=list(dict.fromkeys(image_urls)),
                    )
                )
        messages = _dedupe(messages)
        if messages:
            return messages
    return []


def _transcript_messages(text: str) -> list[ImportedMessage]:
    pattern = re.compile(
        r"^(You|User|Human|Me|Assistant|ChatGPT|Claude|Gemini|DeepSeek|AI|Bot|"
        r"用户|我|助手|模型)\s*(?:said|说)?\s*[:：]\s*(.*)$",
        re.IGNORECASE,
    )
    messages: list[ImportedMessage] = []
    current_role: Optional[str] = None
    current: list[str] = []

    def flush() -> None:
        nonlocal current_role, current
        if current_role and current:
            content = _clean_text("\n".join(current))
            if content:
                messages.append(ImportedMessage(role=current_role, content=content))
        current = []

    for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        match = pattern.match(line.strip())
        if match and _role_from_value(match.group(1)):
            flush()
            current_role = _role_from_value(match.group(1))
            first = match.group(2).strip()
            current = [first] if first else []
        elif current_role is not None:
            current.append(line)
    flush()
    return _dedupe(messages)


def _title_from_soup(soup: BeautifulSoup) -> str:
    for selector in ("h1", "title", "meta[property='og:title']"):
        element = soup.select_one(selector)
        if element is None:
            continue
        value = element.get("content") if element.name == "meta" else element.get_text(" ", strip=True)
        if value:
            title = _clean_title(str(value), "")
            if title:
                return title
    return ""


def parse_html(html_text: str, *, source: str = "", base_url: str = "") -> ImportedConversation:
    soup = BeautifulSoup(html_text, "html.parser")
    best: ImportedConversation | None = None
    for payload in _extract_json_payloads(soup):
        candidate = _parse_payload(payload, source)
        if candidate and candidate.messages and (best is None or len(candidate.messages) > len(best.messages)):
            best = candidate
    dom_messages = _dom_messages(soup, base_url)
    if dom_messages and (best is None or len(dom_messages) > len(best.messages)):
        best = ImportedConversation(
            title=_title_from_soup(soup) or _fallback_title(dom_messages),
            messages=dom_messages,
            source=source,
        )
    if best is None:
        body_text = soup.get_text("\n", strip=True)
        messages = _transcript_messages(body_text)
        if messages:
            best = ImportedConversation(
                title=_title_from_soup(soup) or _fallback_title(messages),
                messages=messages,
                source=source,
            )
    if best is None or not best.messages:
        raise ImportError(
            "没有从网页中识别出对话。该分享页可能需要登录或由浏览器动态渲染。\n\n"
            "请用浏览器打开分享页，另存为 HTML 文件后使用“HTML 文件”导入，"
            "或复制对话文本使用“粘贴文本”导入。"
        )
    best.title = _clean_title(best.title, _fallback_title(best.messages))
    if len(best.messages) > MAX_IMPORTED_MESSAGES:
        best.warnings.append(f"消息过多，仅导入前 {MAX_IMPORTED_MESSAGES} 条")
        best.messages = best.messages[:MAX_IMPORTED_MESSAGES]
    return best


def parse_json(data: Any, *, source: str = "") -> ImportedConversation:
    result = _parse_payload(data, source)
    if result is None or not result.messages:
        raise ImportError("JSON 中未找到可识别的对话消息。")
    result.title = _clean_title(result.title, _fallback_title(result.messages))
    return result


def parse_transcript(text: str, *, source: str = "") -> ImportedConversation:
    messages = _transcript_messages(text)
    if not messages:
        raise ImportError(
            "没有识别到对话。请使用类似下面的格式：\n\n"
            "User: 你好\nAssistant: 你好，有什么可以帮你？"
        )
    return ImportedConversation(
        title=_fallback_title(messages),
        messages=messages,
        source=source,
    )


def _fetch(url: str) -> tuple[bytes, str, str]:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ImportError("只支持 http/https 分享链接。")
    try:
        with httpx.Client(
            follow_redirects=True,
            timeout=httpx.Timeout(connect=20.0, read=60.0, write=20.0, pool=20.0),
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            },
            trust_env=True,
        ) as client:
            response = client.get(url)
            response.raise_for_status()
            if len(response.content) > MAX_PAGE_BYTES:
                raise ImportError("分享页内容超过 20 MB，已停止读取。")
            return response.content, response.headers.get("content-type", ""), str(response.url)
    except httpx.HTTPStatusError as exc:
        code = exc.response.status_code
        hints = {
            401: "该分享页需要登录，无法直接读取。",
            403: "该分享页禁止匿名访问。",
            404: "分享链接不存在或已失效。",
            429: "请求过于频繁，请稍后再试。",
        }
        hint = hints.get(code, f"分享页返回 HTTP {code}。")
        raise ImportError(
            f"{hint}\n\n请在浏览器中打开并另存为 HTML 后导入，或粘贴对话文本。"
        ) from exc
    except httpx.HTTPError as exc:
        raise ImportError(
            f"无法读取分享页：{exc}\n\n请检查网络，或改用 HTML 文件 / 粘贴文本导入。"
        ) from exc


def _download_images(
    conversation: ImportedConversation,
    *,
    base_url: str,
    max_images: int = MAX_IMPORTED_IMAGES,
) -> None:
    pending: list[tuple[ImportedMessage, str]] = []
    seen_urls: set[str] = set()
    for message in conversation.messages:
        for url in message.image_urls:
            absolute = urljoin(base_url, url) if base_url else url
            if absolute in seen_urls:
                continue
            seen_urls.add(absolute)
            pending.append((message, absolute))
    if not pending:
        return
    downloaded = 0
    with httpx.Client(
        follow_redirects=True,
        timeout=httpx.Timeout(connect=15.0, read=30.0, write=15.0, pool=15.0),
        headers={"User-Agent": USER_AGENT},
        trust_env=True,
    ) as client:
        for message, url in pending:
            if downloaded >= max_images:
                conversation.warnings.append(f"图片超过 {max_images} 张，其余未下载")
                break
            try:
                if url.startswith("data:image/"):
                    header, encoded = url.split(",", 1)
                    mime_type = header[5:].split(";")[0] or "image/png"
                    data = base64.b64decode(encoded)
                    filename = f"shared_image_{downloaded + 1}.png"
                else:
                    response = client.get(url)
                    response.raise_for_status()
                    if len(response.content) > MAX_IMAGE_BYTES:
                        conversation.warnings.append("部分网页图片过大，已跳过")
                        continue
                    mime_type = response.headers.get("content-type", "").split(";")[0]
                    if not mime_type.startswith("image/") or mime_type == "image/svg+xml":
                        continue
                    data = response.content
                    suffix = {
                        "image/jpeg": ".jpg",
                        "image/webp": ".webp",
                        "image/gif": ".gif",
                        "image/bmp": ".bmp",
                    }.get(mime_type, ".png")
                    raw_name = Path(unquote(urlparse(url).path)).name
                    filename = raw_name or f"shared_image_{downloaded + 1}{suffix}"
                    if "." not in filename:
                        filename += suffix
                if len(data) < 80:
                    continue
                message.attachments.append(
                    Attachment(
                        filename=filename[:255],
                        mime_type=mime_type,
                        kind="image",
                        size_bytes=len(data),
                        data=data,
                        token_count=850,
                    )
                )
                downloaded += 1
            except Exception:
                conversation.warnings.append("部分网页图片下载失败，已跳过")
    conversation.messages = [
        ImportedMessage(
            role=message.role,
            content=message.content,
            image_urls=[],
            attachments=message.attachments,
        )
        for message in conversation.messages
        if message.content or message.attachments
    ]


def deepseek_share_id(url: str) -> Optional[str]:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if host != "chat.deepseek.com" and not host.endswith(".deepseek.com"):
        return None
    match = re.search(r"/share/([^/?#]+)", parsed.path)
    return unquote(match.group(1)) if match else None


def parse_deepseek_payload(payload: Any, *, source: str = "") -> ImportedConversation:
    if not isinstance(payload, dict):
        raise ImportError("DeepSeek 分享接口返回了无法识别的数据。")
    data = payload.get("data", payload)
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except ValueError as exc:
            raise ImportError("DeepSeek 分享接口返回了无法识别的数据。") from exc
    if not isinstance(data, dict):
        raise ImportError("DeepSeek 分享接口没有返回对话数据。")
    biz = data.get("biz_data")
    if isinstance(biz, str):
        try:
            biz = json.loads(biz)
        except ValueError:
            biz = {}
    if not isinstance(biz, dict):
        biz = {}
    raw_messages = biz.get("messages") or data.get("messages") or payload.get("messages")
    if not isinstance(raw_messages, list) or not raw_messages:
        raise ImportError("DeepSeek 分享接口没有返回可读取的消息。")
    messages: list[ImportedMessage] = []
    for item in raw_messages:
        if not isinstance(item, dict):
            continue
        role = _role_from_value(item.get("role") or item.get("sender"))
        fragments = item.get("fragments")
        fragment_texts: list[str] = []
        if isinstance(fragments, list):
            for fragment in fragments:
                if not isinstance(fragment, dict):
                    continue
                if str(fragment.get("type") or "").upper() not in {"REQUEST", "RESPONSE"}:
                    continue
                value = fragment.get("content")
                if isinstance(value, str) and value.strip():
                    fragment_texts.append(value)
        # DeepSeek currently stores visible text in `fragments`; search/thinking
        # fragments are intentionally skipped so they don't become chat turns.
        message = None
        if role in ("user", "assistant") and fragment_texts:
            message = ImportedMessage(
                role=role,
                content=_clean_text("\n\n".join(fragment_texts)),
            )
        if message is None:
            message = _normalise_message(item)
        if message is None:
            content = item.get("content")
            text = content if isinstance(content, str) else ""
            if role in ("user", "assistant") and text.strip():
                message = ImportedMessage(role=role, content=_clean_text(text))
        if message and (message.content or message.image_urls):
            messages.append(message)
    messages = _dedupe(messages)
    if not messages:
        raise ImportError("DeepSeek 分享接口没有返回可读取的消息。")
    title = str(biz.get("title") or data.get("title") or "").strip()
    if not title or title.lower() in {"shared conversation", "shared chat"}:
        title = _fallback_title(messages)
    return ImportedConversation(
        title=_clean_title(title, _fallback_title(messages)),
        messages=messages[:MAX_IMPORTED_MESSAGES],
        source=source or "https://chat.deepseek.com",
    )


def import_deepseek_share(url: str, *, download_images: bool = True) -> ImportedConversation:
    share_id = deepseek_share_id(url)
    if not share_id:
        raise ImportError("不是有效的 DeepSeek 分享链接。")
    endpoint = "https://chat.deepseek.com/api/v0/share/content?" + urlencode(
        {"share_id": share_id}
    )
    try:
        with httpx.Client(
            follow_redirects=True,
            timeout=httpx.Timeout(connect=20.0, read=60.0, write=20.0, pool=20.0),
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "application/json",
                "Referer": url,
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            },
            trust_env=True,
        ) as client:
            response = client.get(endpoint)
            response.raise_for_status()
            if len(response.content) > MAX_PAGE_BYTES:
                raise ImportError("DeepSeek 分享内容超过 20 MB，已停止读取。")
            payload = response.json()
    except httpx.HTTPStatusError as exc:
        code = exc.response.status_code
        hints = {
            401: "DeepSeek 分享接口需要登录。",
            403: "DeepSeek 分享接口禁止匿名读取。",
            404: "DeepSeek 分享链接不存在或已失效。",
            429: "DeepSeek 请求过于频繁，请稍后再试。",
        }
        hint = hints.get(code, f"DeepSeek 分享接口返回 HTTP {code}。")
        raise ImportError(
            f"{hint}\n\n请在浏览器中打开分享页并另存为 HTML 后导入，或粘贴对话文本。"
        ) from exc
    except (httpx.HTTPError, ValueError) as exc:
        raise ImportError(
            f"无法读取 DeepSeek 分享链接：{exc}\n\n"
            "请检查网络，或改用 HTML 文件 / 粘贴文本导入。"
        ) from exc
    conversation = parse_deepseek_payload(payload, source=url)
    if download_images:
        _download_images(conversation, base_url=url)
    return conversation


def import_from_url(url: str, *, download_images: bool = True) -> ImportedConversation:
    if deepseek_share_id(url):
        return import_deepseek_share(url, download_images=download_images)
    content, content_type, final_url = _fetch(url)
    text = content.decode("utf-8", errors="replace")
    if "json" in content_type.lower() or text.lstrip().startswith(("{", "[")):
        try:
            data = json.loads(text)
        except ValueError:
            data = None
        if data is not None:
            conversation = parse_json(data, source=final_url)
        else:
            conversation = parse_html(text, source=final_url, base_url=final_url)
    else:
        conversation = parse_html(text, source=final_url, base_url=final_url)
    if download_images:
        _download_images(conversation, base_url=final_url)
    return conversation


def import_from_html_file(path: str | Path, *, download_images: bool = False) -> ImportedConversation:
    file_path = Path(path)
    if not file_path.is_file():
        raise ImportError(f"文件不存在：{file_path}")
    if file_path.stat().st_size > MAX_PAGE_BYTES:
        raise ImportError("HTML 文件超过 20 MB。")
    text = file_path.read_text(encoding="utf-8", errors="replace")
    conversation = parse_html(text, source=str(file_path), base_url="")
    if download_images:
        _download_images(conversation, base_url="", max_images=MAX_IMPORTED_IMAGES)
    return conversation
