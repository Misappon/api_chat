"""Tests for provider-aware reasoning level options."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from apichat.models import Provider
from apichat.reasoning import (
    budget_for_level,
    clamp_reasoning_level,
    effort_for_level,
    reasoning_levels,
)


class ReasoningTests(unittest.TestCase):
    def test_levels_depend_on_provider_category(self) -> None:
        openai = Provider(id=1, alias="O", provider="openai", model="gpt-5")
        deepseek = Provider(
            id=2,
            alias="D",
            provider="openai",
            base_url="https://api.deepseek.com/v1",
            model="deepseek-chat",
        )
        anthropic = Provider(id=3, alias="A", provider="anthropic", model="claude")
        self.assertEqual([value for value, _ in reasoning_levels(openai)], [0, 1, 2, 3])
        self.assertEqual([value for value, _ in reasoning_levels(deepseek)], [0, 3])
        self.assertEqual([value for value, _ in reasoning_levels(anthropic)], [0, 1, 2, 3])
        self.assertEqual(clamp_reasoning_level(deepseek, 1), 0)
        self.assertEqual(clamp_reasoning_level(deepseek, 3), 3)
        self.assertEqual(effort_for_level(1), "low")
        self.assertEqual(budget_for_level(3), 8192)


if __name__ == "__main__":
    unittest.main()
