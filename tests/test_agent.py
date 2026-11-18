"""Tests for the bounded reason/search loop."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from apichat.agent import run_reason_search_loop
from apichat.models import CompletionResult, Provider
from apichat.web_search import SearchResult


class AgentTests(unittest.TestCase):
    def test_reason_search_loop_stops_at_confidence(self) -> None:
        provider = Provider(id=1, alias="Mock", provider="openai", model="mock")
        messages = [{"role": "user", "content": "What is OpenAI?"}]
        plans = [
            CompletionResult(
                content='{"need_search": true, "query": "OpenAI", "confidence": 0.3}'
            ),
            CompletionResult(
                content='{"need_search": false, "query": "", "confidence": 0.9}'
            ),
        ]
        statuses: list[str] = []

        class FakeClient:
            def __init__(self, _provider):
                pass

            def complete(self, *_args, **_kwargs):
                return plans.pop(0)

        with patch("apichat.agent.LLMClient", FakeClient), patch(
            "apichat.agent.search_configured",
            return_value=[
                SearchResult(
                    title="OpenAI",
                    url="https://example.com/openai",
                    snippet="AI research company",
                    source="Bing",
                )
            ],
        ) as search:
            result = run_reason_search_loop(
                provider,
                messages,
                reasoning_level=2,
                search_sources=[{"type": "bing"}],
                on_status=statuses.append,
            )
        self.assertFalse(plans)
        self.assertEqual(search.call_count, 1)
        self.assertEqual(len(result.rounds), 1)
        self.assertIn("不可信数据", result.messages[-1]["content"])
        self.assertIn("https://example.com/openai", result.messages[-1]["content"])
        self.assertTrue(any("置信度" in status for status in statuses))


if __name__ == "__main__":
    unittest.main()
