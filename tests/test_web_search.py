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
    _parse_results,
    _safe_url,
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
