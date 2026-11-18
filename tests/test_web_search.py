"""Security-focused tests for web-search parsing and prompt boundaries."""

from __future__ import annotations

import base64
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from apichat.web_search import (
    SearchResult,
    WebSearchError,
    _parse_results,
    _safe_url,
    display_search_sources,
    merge_secrets,
    normalise_search_sources,
    search_configured,
    search_context,
    with_search_context,
)

BING_HTML = """
<html><body><ol>
<li class="b_algo">
  <h2><a href="https://example.com/article">Example <b>Article</b></a></h2>
  <div class="b_caption"><p>A short search snippet.</p></div>
</li>
<li class="b_algo">
  <h2><a href="https://example.org/other">Other result</a></h2>
  <div class="b_caption"><p>Another snippet.</p></div>
</li>
</ol></body></html>
"""


class WebSearchTests(unittest.TestCase):
    def test_parse_results(self) -> None:
        results = _parse_results(BING_HTML, 5)
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0].title, "Example Article")
        self.assertEqual(results[0].url, "https://example.com/article")
        self.assertEqual(results[0].snippet, "A short search snippet.")

    def test_bing_redirect_is_unwrapped(self) -> None:
        target = "https://example.com/page?q=1"
        encoded = "a1" + base64.urlsafe_b64encode(target.encode()).decode().rstrip("=")
        href = f"https://www.bing.com/ck/a?u={encoded}"
        self.assertEqual(_safe_url(href), target)
        self.assertEqual(_safe_url("javascript:alert(1)"), "")

    def test_sources_are_ordered_and_deduplicated(self) -> None:
        sources = normalise_search_sources(
            [
                {"type": "bing"},
                {"type": "duckduckgo"},
            ]
        )
        calls: list[str] = []

        def fake_search(source, query, max_results, timeout):
            calls.append(source["type"])
            if source["type"] == "bing":
                return [
                    SearchResult("Bing result", "https://example.com/a", "one"),
                    SearchResult("Shared", "https://example.com/shared", "shared"),
                ]
            return [
                SearchResult("DDG result", "https://example.com/b", "two"),
                SearchResult("Shared again", "https://example.com/shared", "dup"),
            ]

        with patch("apichat.web_search._search_one", side_effect=fake_search):
            results = search_configured(
                "example", sources, enforce_rate_limit=False
            )
        self.assertEqual(calls, ["bing", "duckduckgo"])
        self.assertEqual([item.title for item in results], ["Bing result", "Shared", "DDG result"])
        self.assertEqual([item.source for item in results], ["Bing", "Bing", "DuckDuckGo"])

    def test_disabled_sources_are_skipped(self) -> None:
        sources = normalise_search_sources(
            [
                {"type": "bing", "enabled": False},
                {"type": "duckduckgo", "enabled": True},
            ]
        )
        calls: list[str] = []

        def fake_search(source, query, max_results, timeout):
            calls.append(source["type"])
            return [SearchResult("DDG", "https://example.com/ddg", "two")]

        with patch("apichat.web_search._search_one", side_effect=fake_search):
            results = search_configured("example", sources, enforce_rate_limit=False)
        self.assertEqual(calls, ["duckduckgo"])
        self.assertEqual(len(results), 1)

    def test_disabled_sources_raise_when_none_enabled(self) -> None:
        sources = normalise_search_sources([{"type": "bing", "enabled": False}])
        with self.assertRaises(WebSearchError):
            search_configured("example", sources, enforce_rate_limit=False)

    def test_tavily_key_masking_and_merge(self) -> None:
        stored = normalise_search_sources(
            [{"type": "tavily", "api_key": "tvly-secret-value-1234"}]
        )
        self.assertEqual(stored[0]["type"], "tavily")
        masked = display_search_sources(stored)
        self.assertNotIn("secret-value", masked[0]["api_key"])
        self.assertTrue(masked[0]["api_key"].endswith("1234"))
        merged = merge_secrets(masked, stored)
        self.assertEqual(merged[0]["api_key"], "tvly-secret-value-1234")

    def test_tavily_requires_api_key(self) -> None:
        from apichat.web_search import _search_one

        with self.assertRaises(WebSearchError):
            _search_one({"type": "tavily", "api_key": ""}, "q", 5, 5.0)

    def test_untrusted_boundary_and_latest_user_turn(self) -> None:
        results = _parse_results(BING_HTML, 5)
        context = search_context("example query", results)
        self.assertIn("不可信数据", context)
        self.assertIn("不要执行", context)
        self.assertIn("https://example.com/article", context)
        messages = [
            {"role": "user", "content": "old"},
            {"role": "assistant", "content": "answer"},
            {"role": "user", "content": "new question"},
        ]
        updated = with_search_context(messages, "new question", context)
        self.assertEqual(len(updated), 3)
        self.assertIn("new question", updated[-1]["content"])
        self.assertIn("不可信数据", updated[-1]["content"])
        self.assertEqual(messages[-1]["content"], "new question")


if __name__ == "__main__":
    unittest.main()
