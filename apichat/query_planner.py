"""Lightweight search-query extraction and trusted local-time context."""

from __future__ import annotations

import re
from datetime import datetime

from .llm import LLMClient
from .models import Provider

_QUERY_PREFIXES = (
    "搜索词：",
    "搜索词:",
    "query:",
    "query：",
    "搜索：",
    "搜索:",
)
_QUERY_NOISE = re.compile(r"^[\s\"'“”‘’《》<>`*#-]+|[\s\"'“”‘’《》<>`*#-]+$")
_WHITESPACE = re.compile(r"\s+")


def latest_user_text(messages: list[dict]) -> str:
    for message in reversed(messages):
        if message.get("role") == "user":
            return str(message.get("content") or "").strip()
    return ""


def heuristic_query(text: str) -> str:
    """Conservative fallback when the small extraction call fails."""
    value = _WHITESPACE.sub(" ", (text or "").strip())
    for prefix in ("请帮我", "帮我", "请", "麻烦"):
        if value.startswith(prefix):
            value = value[len(prefix) :].lstrip("，,。. ")
    value = value.strip("？?！!。. ")
    return value[:200].strip()


def clean_query(value: str, fallback: str = "") -> str:
    value = (value or "").strip()
    if value.startswith("```"):
        value = value.strip("`")
        if value.lower().startswith("text"):
            value = value[4:].lstrip()
    lines = [line.strip() for line in value.splitlines() if line.strip()]
    value = lines[0] if lines else ""
    for prefix in _QUERY_PREFIXES:
        if value.lower().startswith(prefix.lower()):
            value = value[len(prefix) :].strip()
            break
    value = _QUERY_NOISE.sub("", value)
    value = _WHITESPACE.sub(" ", value).strip()
    if len(value) > 200:
        value = value[:200].rstrip()
    return value or fallback


def local_time_text() -> str:
    now = datetime.now().astimezone()
    return f"[本地系统时间｜可信] {now.strftime('%Y-%m-%d %H:%M:%S %Z%z')}"


def with_local_time(messages: list[dict]) -> list[dict]:
    """Prepend trusted local time to the latest user turn (not persisted)."""
    updated: list[dict] = []
    for index in range(len(messages) - 1, -1, -1):
        message = messages[index]
        if message.get("role") == "user":
            merged = dict(message)
            merged["content"] = f"{local_time_text()}\n\n{message.get('content') or ''}"
            updated = list(messages)
            updated[index] = merged
            return updated
    return list(messages)


def extract_search_query(
    provider: Provider,
    messages: list[dict],
) -> tuple[str, int, int]:
    """Use a tiny non-reasoning completion to turn chat text into a query.

    Returns (query, prompt_tokens, completion_tokens). The fallback is the
    cleaned original question, so a failed extraction never blocks search.
    """
    original = latest_user_text(messages)
    fallback = heuristic_query(original)
    if not original:
        return "", 0, 0
    instructions = (
        "你是搜索词提取器。把用户问题改写成一条适合搜索引擎的简短查询词。\n"
        "保留专有名词、日期、地点、语言、site: 限定等关键信息；"
        "删除“请帮我/请问/我想知道”等口语和回答要求。\n"
        "不要回答问题，不要解释，不要加引号，只输出一行查询词，最多 30 个汉字。\n"
        f"当前本地时间：{datetime.now().astimezone().strftime('%Y-%m-%d %H:%M:%S %Z%z')}\n"
        f"用户问题：{original[:1000]}"
    )
    try:
        result = LLMClient(provider).complete(
            [{"role": "user", "content": instructions}],
            max_tokens=80,
            temperature=0.0,
            reasoning_level=0,
        )
        query = clean_query(result.content, fallback)
        return query, result.prompt_tokens, result.completion_tokens
    except Exception:
        return fallback, 0, 0
