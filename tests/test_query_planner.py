"""Tests for search-query extraction and local-time context."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from apichat.models import CompletionResult, Provider
from apichat.query_planner import (
    clean_query,
    extract_search_query,
    heuristic_query,
    with_local_time,
)


class QueryPlannerTests(unittest.TestCase):
    def test_clean_query(self) -> None:
        self.assertEqual(clean_query("搜索词：“OpenAI 最新模型”"), "OpenAI 最新模型")
        self.assertEqual(clean_query("```\nPython 日期时间\n```"), "Python 日期时间")

    def test_heuristic_query(self) -> None:
        self.assertEqual(heuristic_query("请帮我查一下 OpenAI 的最新模型？"), "查一下 OpenAI 的最新模型")

    def test_extract_query_uses_model(self) -> None:
        provider = Provider(id=1, alias="x", provider="openai", model="mock")

        class FakeClient:
            def __init__(self, _provider):
                pass

            def complete(self, *_args, **_kwargs):
                return CompletionResult(
                    content="搜索词：2026年11月18日 当前时间",
                    prompt_tokens=12,
                    completion_tokens=8,
                )

        with patch("apichat.query_planner.LLMClient", FakeClient):
            query, prompt, completion = extract_search_query(
                provider, [{"role": "user", "content": "请告诉我当前日期时间"}]
            )
        self.assertEqual(query, "2026年11月18日 当前时间")
        self.assertEqual((prompt, completion), (12, 8))

    def test_extract_query_falls_back(self) -> None:
        provider = Provider(id=1, alias="x", provider="openai", model="mock")

        class BrokenClient:
            def __init__(self, _provider):
                pass

            def complete(self, *_args, **_kwargs):
                raise RuntimeError("offline")

        with patch("apichat.query_planner.LLMClient", BrokenClient):
            query, _, _ = extract_search_query(
                provider, [{"role": "user", "content": "请查一下当前日期时间"}]
            )
        self.assertIn("当前日期时间", query)

    def test_local_time_context_is_prepended(self) -> None:
        messages = [{"role": "user", "content": "现在几点"}]
        updated = with_local_time(messages)
        self.assertIn("本地系统时间", updated[0]["content"])
        self.assertIn("现在几点", updated[0]["content"])
        self.assertEqual(messages[0]["content"], "现在几点")


if __name__ == "__main__":
    unittest.main()
