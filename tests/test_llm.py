"""Protocol tests for the LLM adapters against a local fake HTTP server."""

from __future__ import annotations

import json
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from apichat.llm import (
    LLMClient,
    LLMError,
    _anthropic_payload,
    _gemini_payload,
    _openai_messages,
    clean_title,
)
from apichat.models import Attachment, Provider


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, format, *args):  # noqa: A002
        return

    def _send_json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _start_sse(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Connection", "close")
        self.end_headers()

    def _sse(self, data: dict | str) -> None:
        raw = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False)
        self.wfile.write(f"data: {raw}\n\n".encode("utf-8"))
        self.wfile.flush()

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except Exception:
            body = {}
        path = urlparse(self.path).path
        if path.endswith("/unauthorized/chat/completions"):
            self._send_json(
                {"error": {"message": "invalid api key", "type": "authentication_error"}},
                status=401,
            )
            return
        if path.endswith("/chat/completions"):
            reasoning = body.get("model") == "mock-reasoning" or body.get("reasoning_effort")
            if body.get("stream"):
                self._start_sse()
                if reasoning:
                    self._sse(
                        {
                            "id": "mock",
                            "model": "mock-reasoning",
                            "choices": [{"delta": {"reasoning_content": "先思考。"}}],
                        }
                    )
                self._sse(
                    {
                        "id": "mock",
                        "model": "mock-openai",
                        "choices": [{"delta": {"content": "你好"}}],
                    }
                )
                self._sse(
                    {
                        "id": "mock",
                        "model": "mock-openai",
                        "choices": [{"delta": {"content": "，OpenAI 流式回复。"}}],
                    }
                )
                self._sse(
                    {
                        "id": "mock",
                        "model": "mock-openai",
                        "choices": [{"delta": {}, "finish_reason": "stop"}],
                        "usage": {
                            "prompt_tokens": 12,
                            "completion_tokens": 5,
                            "total_tokens": 17,
                        },
                    }
                )
                self._sse("[DONE]")
                return
            self._send_json(
                {
                    "model": "mock-openai",
                    "choices": [
                        {
                            "message": {
                                "role": "assistant",
                                "content": "非流式回复",
                                **({"reasoning_content": "先思考。"} if reasoning else {}),
                            },
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {
                        "prompt_tokens": 9,
                        "completion_tokens": 4,
                        "total_tokens": 13,
                    },
                }
            )
            return
        if path.endswith("/messages"):
            if body.get("stream"):
                self._start_sse()
                events = [
                    (
                        "message_start",
                        {
                            "type": "message_start",
                            "message": {
                                "model": "claude-mock",
                                "usage": {"input_tokens": 21},
                            },
                        },
                    ),
                    (
                        "content_block_delta",
                        {
                            "type": "content_block_delta",
                            "delta": {"type": "text_delta", "text": "你好"},
                        },
                    ),
                    (
                        "content_block_delta",
                        {
                            "type": "content_block_delta",
                            "delta": {"type": "text_delta", "text": "，Anthropic。"},
                        },
                    ),
                    (
                        "message_delta",
                        {
                            "type": "message_delta",
                            "delta": {"stop_reason": "end_turn"},
                            "usage": {"output_tokens": 7},
                        },
                    ),
                    ("message_stop", {"type": "message_stop"}),
                ]
                for name, payload in events:
                    self.wfile.write(f"event: {name}\n".encode("utf-8"))
                    self._sse(payload)
                return
            self._send_json(
                {
                    "model": "claude-mock",
                    "content": [{"type": "text", "text": "Anthropic 非流式回复"}],
                    "stop_reason": "end_turn",
                    "usage": {"input_tokens": 8, "output_tokens": 4},
                }
            )
            return
        if "streamGenerateContent" in path:
            self._start_sse()
            self._sse(
                {
                    "candidates": [
                        {
                            "content": {
                                "role": "model",
                                "parts": [{"text": "你好"}],
                            }
                        }
                    ],
                    "usageMetadata": {
                        "promptTokenCount": 7,
                        "candidatesTokenCount": 2,
                        "totalTokenCount": 9,
                    },
                }
            )
            self._sse(
                {
                    "candidates": [
                        {
                            "content": {
                                "role": "model",
                                "parts": [{"text": "，Gemini。"}],
                            },
                            "finishReason": "STOP",
                        }
                    ],
                    "usageMetadata": {
                        "promptTokenCount": 7,
                        "candidatesTokenCount": 5,
                        "totalTokenCount": 12,
                    },
                }
            )
            return
        if "generateContent" in path:
            self._send_json(
                {
                    "candidates": [
                        {
                            "content": {
                                "role": "model",
                                "parts": [{"text": "Gemini 非流式回复"}],
                            },
                            "finishReason": "STOP",
                        }
                    ],
                    "usageMetadata": {
                        "promptTokenCount": 6,
                        "candidatesTokenCount": 5,
                        "totalTokenCount": 11,
                    },
                }
            )
            return
        self._send_json({"error": {"message": "not found"}}, status=404)


class LiveServer:
    def __enter__(self):
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.server.server_address[1]
        return self

    def __exit__(self, *args):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)


class LLMTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.live = LiveServer().__enter__()
        cls.base = f"http://127.0.0.1:{cls.live.port}"

    @classmethod
    def tearDownClass(cls) -> None:
        cls.live.__exit__(None, None, None)

    def _provider(self, provider: str, model: str, suffix: str = "/v1") -> Provider:
        return Provider(
            id=1,
            alias="Mock",
            provider=provider,
            base_url=f"{self.base}{suffix}",
            api_key="test-key",
            model=model,
            context_window=1000,
            max_output_tokens=64,
            temperature=0.2,
        )

    def test_openai_stream(self) -> None:
        pieces: list[str] = []
        result = LLMClient(self._provider("openai", "mock-openai")).stream_chat(
            [{"role": "user", "content": "hi"}], pieces.append
        )
        self.assertEqual("".join(pieces), "你好，OpenAI 流式回复。")
        self.assertEqual(result.content, "".join(pieces))
        self.assertEqual(result.prompt_tokens, 12)
        self.assertEqual(result.completion_tokens, 5)
        self.assertEqual(result.total_tokens, 17)
        self.assertEqual(result.finish_reason, "stop")

    def test_openai_complete(self) -> None:
        result = LLMClient(self._provider("openai", "mock-openai")).complete(
            [{"role": "user", "content": "hi"}], max_tokens=8
        )
        self.assertEqual(result.content, "非流式回复")
        self.assertEqual(result.total_tokens, 13)

    def test_anthropic_stream(self) -> None:
        pieces: list[str] = []
        provider = self._provider("anthropic", "claude-mock", suffix="")
        result = LLMClient(provider).stream_chat(
            [{"role": "user", "content": "hi"}], pieces.append
        )
        self.assertEqual("".join(pieces), "你好，Anthropic。")
        self.assertEqual(result.prompt_tokens, 21)
        self.assertEqual(result.completion_tokens, 7)
        self.assertEqual(result.finish_reason, "end_turn")

    def test_gemini_stream(self) -> None:
        pieces: list[str] = []
        provider = self._provider("gemini", "gemini-mock", suffix="/v1beta")
        result = LLMClient(provider).stream_chat(
            [{"role": "user", "content": "hi"}], pieces.append
        )
        self.assertEqual("".join(pieces), "你好，Gemini。")
        self.assertEqual(result.prompt_tokens, 7)
        self.assertEqual(result.completion_tokens, 5)
        self.assertEqual(result.total_tokens, 12)

    def test_reasoning_stream_and_complete(self) -> None:
        provider = self._provider("openai", "mock-reasoning", suffix="")
        client = LLMClient(provider)
        reasoning_parts: list[str] = []
        result = client.stream_chat(
            [{"role": "user", "content": "think"}],
            on_delta=lambda _text: None,
            reasoning=True,
            on_reasoning=reasoning_parts.append,
        )
        self.assertEqual(result.reasoning, "先思考。")
        self.assertEqual("".join(reasoning_parts), "先思考。")
        self.assertIn("OpenAI", result.content)

        complete = client.complete(
            [{"role": "user", "content": "think"}], reasoning=True
        )
        self.assertEqual(complete.reasoning, "先思考。")
        self.assertEqual(complete.content, "非流式回复")

    def test_reasoning_payloads(self) -> None:
        provider = self._provider("openai", "gpt-5", suffix="")
        client = LLMClient(provider)
        client._reasoning = True
        client._reasoning_level = 2
        body = client._openai_body(
            [{"role": "user", "content": "think"}], False, 100, 0.2
        )
        self.assertEqual(body["reasoning_effort"], "medium")
        self.assertNotIn("temperature", body)

        deepseek = Provider(
            id=1,
            alias="DeepSeek",
            provider="openai",
            base_url="https://api.deepseek.com/v1",
            model="deepseek-chat",
        )
        deepseek_client = LLMClient(deepseek)
        deepseek_client._reasoning = True
        deepseek_client._reasoning_level = 3
        deepseek_body = deepseek_client._openai_body(
            [{"role": "user", "content": "think"}], False, 100, 0.2
        )
        self.assertEqual(deepseek_body["model"], "deepseek-reasoner")
        self.assertNotIn("reasoning_effort", deepseek_body)

        anthropic = _anthropic_payload(
            provider,
            [{"role": "user", "content": "think"}],
            False,
            4096,
            0.2,
            reasoning=True,
            reasoning_level=2,
        )
        self.assertEqual(anthropic["thinking"]["type"], "enabled")
        self.assertNotIn("temperature", anthropic)

        gemini = _gemini_payload(
            provider,
            [{"role": "user", "content": "think"}],
            100,
            0.2,
            reasoning=True,
            reasoning_level=2,
        )
        self.assertEqual(
            gemini["generationConfig"]["thinkingConfig"]["thinkingBudget"], 4096
        )

    def test_http_error_is_readable(self) -> None:
        provider = self._provider("openai", "mock-openai", suffix="/unauthorized")
        with self.assertRaises(LLMError) as ctx:
            LLMClient(provider).stream_chat(
                [{"role": "user", "content": "hi"}], lambda _: None
            )
        message = str(ctx.exception)
        self.assertIn("401", message)
        self.assertIn("API Key", message)
        self.assertIn("invalid api key", message)

    def test_title_cleanup(self) -> None:
        self.assertEqual(clean_title("标题：数据库设计。"), "数据库设计")
        self.assertEqual(clean_title('  "测试标题"  '), "测试标题")
        self.assertEqual(clean_title("", "新对话"), "新对话")

    def test_multimodal_payloads(self) -> None:
        image = Attachment(
            filename="screen.png",
            mime_type="image/png",
            kind="image",
            data=b"fake-png",
            token_count=850,
        )
        text_file = Attachment(
            filename="notes.py",
            mime_type="text/x-python",
            kind="text",
            data=b"print(1)",
            token_count=5,
        )
        messages = [
            {"role": "user", "content": "please look", "attachments": [image, text_file]}
        ]
        provider = self._provider("openai", "mock-openai")
        openai_messages = _openai_messages(provider, messages)
        content = openai_messages[-1]["content"]
        self.assertIsInstance(content, list)
        self.assertIn("notes.py", content[0]["text"])
        self.assertTrue(content[1]["image_url"]["url"].startswith("data:image/png;base64,"))

        anthropic = _anthropic_payload(provider, messages, False, 100, 0.2)
        anthropic_content = anthropic["messages"][-1]["content"]
        self.assertEqual(anthropic_content[1]["type"], "image")
        self.assertEqual(anthropic_content[1]["source"]["type"], "base64")

        gemini = _gemini_payload(provider, messages, 100, 0.2)
        gemini_parts = gemini["contents"][-1]["parts"]
        self.assertEqual(gemini_parts[1]["inline_data"]["mime_type"], "image/png")
        self.assertTrue(gemini_parts[1]["inline_data"]["data"])


if __name__ == "__main__":
    unittest.main()
