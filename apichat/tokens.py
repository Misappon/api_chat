"""Cheap, provider-independent token estimates for context indicators.

The numbers are deliberately conservative estimates: a CJK character is
counted as 0.72 tokens and other text as one token per four characters.
Providers report exact usage for billing, which is what the console uses.
"""

from __future__ import annotations

import math
import re

_CJK_RE = re.compile(
    r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff"
    r"\u3040-\u30ff\uac00-\ud7af]"
)


def estimate_tokens(text: str | None) -> int:
    if not text:
        return 0
    cjk = len(_CJK_RE.findall(text))
    rest = max(0, len(text) - cjk)
    # Whitespace and punctuation are far cheaper than prose.
    spaces = text.count(" ") + text.count("\n") + text.count("\t")
    rest = max(0, rest - spaces)
    value = cjk * 0.72 + spaces * 0.2 + rest / 3.8
    return max(1, int(math.ceil(value)))


def message_tokens(role: str, content: str) -> int:
    # Chat formats add a handful of structural tokens per message.
    return estimate_tokens(content) + (5 if role in ("user", "assistant") else 4)


def context_tokens(messages, system_prompt: str = "") -> int:
    total = estimate_tokens(system_prompt) + (6 if system_prompt else 0)
    for message in messages:
        role = getattr(message, "role", None) if not isinstance(message, dict) else message.get("role", "")
        content = getattr(message, "content", None) if not isinstance(message, dict) else message.get("content", "")
        total += message_tokens(role or "", content or "")
    return total


def remaining_percent(used: int, window: int) -> float:
    if not window or window <= 0:
        return 0.0
    return max(0.0, min(100.0, (1.0 - (used / float(window))) * 100.0))


def format_tokens(value: int | float | None) -> str:
    if value is None:
        return "0"
    value = int(value)
    if value >= 1_000_000:
        text = f"{value / 1_000_000:.2f}".rstrip("0").rstrip(".")
        return f"{text}M"
    if value >= 1_000:
        text = f"{value / 1_000:.1f}".rstrip("0").rstrip(".")
        return f"{text}K"
    return str(value)


def format_delta(value: int) -> str:
    return f"+{format_tokens(value)}" if value else "0"
