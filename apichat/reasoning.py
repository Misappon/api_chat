"""Provider-aware reasoning levels.

The UI only exposes levels the selected provider/model category can plausibly
use. The backend maps a level to the provider's native parameter:

* OpenAI-compatible: reasoning_effort = low / medium / high
* DeepSeek: deepseek-reasoner (a single reasoning mode; we expose off/high)
* Anthropic: thinking budget 1024 / 4096 / 8192
* Gemini: thinkingBudget 1024 / 4096 / 8192
"""

from __future__ import annotations

from .models import Provider

LEVEL_LABELS = {1: "低", 2: "中", 3: "高"}
EFFORT_BY_LEVEL = {1: "low", 2: "medium", 3: "high"}
BUDGET_BY_LEVEL = {1: 1024, 2: 4096, 3: 8192}


def reasoning_levels(provider: Provider | None) -> list[tuple[int, str]]:
    if provider is None:
        return [(0, "关")]
    kind = (provider.provider or "openai").lower()
    if kind == "openai":
        text = ((provider.base_url or "") + " " + (provider.model or "")).lower()
        if "deepseek" in text:
            # DeepSeek reasoner has a single reasoning mode rather than effort
            # tiers.
            return [(0, "关"), (3, "高")]
        return [(0, "关"), (1, "低"), (2, "中"), (3, "高")]
    if kind in {"anthropic", "gemini"}:
        return [(0, "关"), (1, "低"), (2, "中"), (3, "高")]
    return [(0, "关"), (1, "低"), (2, "中"), (3, "高")]


def clamp_reasoning_level(provider: Provider | None, level: int) -> int:
    allowed = {value for value, _ in reasoning_levels(provider)}
    value = int(level or 0)
    if value in allowed:
        return value
    return max(allowed) if value > max(allowed) else 0


def reasoning_label(level: int) -> str:
    return LEVEL_LABELS.get(int(level or 0), "关")


def effort_for_level(level: int) -> str:
    return EFFORT_BY_LEVEL.get(max(1, min(3, int(level or 0))), "medium")


def budget_for_level(level: int) -> int:
    return BUDGET_BY_LEVEL.get(max(1, min(3, int(level or 0))), 4096)
