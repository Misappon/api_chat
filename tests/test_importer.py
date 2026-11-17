"""Tests for shared-conversation parsing and export formatting."""

from __future__ import annotations

import json
import sys
import tempfile
import threading
import unittest
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from apichat.exporter import conversation_to_text
from apichat.importer import ImportError, parse_html, parse_json, parse_transcript
from apichat.models import Attachment, Conversation, Message


class ImporterTests(unittest.TestCase):
    def test_chatgpt_next_data_mapping(self) -> None:
        payload = {
            "props": {
                "pageProps": {
                    "title": "Python 讨论",
                    "mapping": {
                        "a": {
                            "message": {
                                "author": {"role": "user"},
                                "content": {"parts": ["介绍一下 Python。"]},
                                "create_time": 1,
                            }
                        },
                        "b": {
                            "message": {
                                "author": {"role": "assistant"},
                                "content": {"parts": ["Python 是一门通用语言。"]},
                                "create_time": 2,
                            }
                        },
                        "c": {
                            "message": {
                                "author": {"role": "system"},
                                "content": {"parts": ["ignored"]},
                                "create_time": 0,
                            }
                        },
                    },
                }
            }
        }
        html = (
            "<html><head><title>fallback</title></head><body>"
            '<script id="__NEXT_DATA__" type="application/json">'
            + json.dumps(payload, ensure_ascii=False)
            + "</script></body></html>"
        )
        result = parse_html(html, source="test")
        self.assertEqual(result.title, "Python 讨论")
        self.assertEqual([m.role for m in result.messages], ["user", "assistant"])
        self.assertIn("通用语言", result.messages[1].content)

    def test_claude_json(self) -> None:
        payload = {
            "props": {
                "pageProps": {
                    "conversation": {
                        "title": "Claude 分享",
                        "chat_messages": [
                            {"sender": "human", "text": "你好"},
                            {"sender": "assistant", "text": "你好，有什么可以帮你？"},
                        ],
                    }
                }
            }
        }
        result = parse_json(payload)
        self.assertEqual(result.title, "Claude 分享")
        self.assertEqual(len(result.messages), 2)

    def test_dom_fallback(self) -> None:
        html = """
        <html><body><h1>DOM 对话</h1>
          <div data-message-author-role="user"><p>问题一</p></div>
          <div data-message-author-role="assistant"><p>回答一</p>
            <img src="data:image/png;base64,iVBORw0KGgo=" /></div>
        </body></html>
        """
        result = parse_html(html)
        self.assertEqual(result.title, "DOM 对话")
        self.assertEqual(len(result.messages), 2)
        self.assertTrue(result.messages[1].image_urls)

    def test_html_file_can_capture_data_image(self) -> None:
        import base64

        from apichat.importer import import_from_html_file

        encoded = base64.b64encode(b"x" * 100).decode("ascii")
        html = f"""
        <html><body><h1>图片对话</h1>
          <div data-message-author-role="user"><p>看图</p>
            <img src="data:image/png;base64,{encoded}" /></div>
          <div data-message-author-role="assistant"><p>看到了</p></div>
        </body></html>
        """
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "share.html"
            path.write_text(html, encoding="utf-8")
            result = import_from_html_file(path, download_images=True)
        self.assertEqual(len(result.messages), 2)
        self.assertEqual(len(result.messages[0].attachments), 1)
        self.assertEqual(result.messages[0].attachments[0].kind, "image")

    def test_import_from_public_url(self) -> None:
        from apichat.importer import import_from_url

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                return

            def do_GET(self):
                body = (
                    "<html><head><title>网址分享</title></head><body>"
                    '<div data-message-author-role="user">你好</div>'
                    '<div data-message-author-role="assistant">你好，这是回答。</div>'
                    "</body></html>"
                ).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            result = import_from_url(
                f"http://127.0.0.1:{server.server_address[1]}/share", download_images=False
            )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
        self.assertEqual(result.title, "网址分享")
        self.assertEqual(len(result.messages), 2)

    def test_text_fallback(self) -> None:
        result = parse_transcript(
            "User: 第一问\nAssistant: 第一答\nUser: 第二问\nAssistant: 第二答"
        )
        self.assertEqual([m.role for m in result.messages], ["user", "assistant", "user", "assistant"])
        self.assertEqual(result.messages[0].content, "第一问")

    def test_invalid_page_has_actionable_error(self) -> None:
        with self.assertRaises(ImportError) as ctx:
            parse_html("<html><body><p>not a conversation</p></body></html>")
        self.assertIn("HTML", str(ctx.exception))


class ExporterTests(unittest.TestCase):
    def test_text_export_contains_metadata_and_attachments(self) -> None:
        conversation = Conversation(
            id=1,
            title="导出测试",
            api_alias="Mock",
            model="mock-model",
            created_at=datetime(2026, 1, 2, 3, 4, 5),
        )
        messages = [
            Message(
                id=1,
                conversation_id=1,
                role="user",
                content="请查看附件",
                created_at=datetime(2026, 1, 2, 3, 5, 0),
                attachments=[
                    Attachment(
                        id=1,
                        message_id=1,
                        filename="图片.png",
                        mime_type="image/png",
                        kind="image",
                        size_bytes=1024,
                        width=100,
                        height=80,
                    )
                ],
            ),
            Message(
                id=2,
                conversation_id=1,
                role="assistant",
                content="收到了。",
                created_at=datetime(2026, 1, 2, 3, 6, 0),
            ),
        ]
        text = conversation_to_text(conversation, messages)
        self.assertIn("导出测试", text)
        self.assertIn("Mock", text)
        self.assertIn("请查看附件", text)
        self.assertIn("[图片] 图片.png", text)
        self.assertIn("收到了", text)


if __name__ == "__main__":
    unittest.main()
