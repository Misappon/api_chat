"""HTTP tests for the authenticated LAN mobile interface."""

from __future__ import annotations

import os
import socket
import sys
import unittest
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx
import pymysql

from apichat.db import Database
from apichat.lan_server import LanShareServer
from apichat.models import Attachment, Provider
from apichat.repository import Repository
from tests.test_llm import LiveServer


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class LanServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.db_name = f"api_chat_lan_{os.getpid()}_{uuid.uuid4().hex[:6]}"
        cls.config = {
            "host": "127.0.0.1",
            "port": 3306,
            "user": "root",
            "password": "",
            "name": cls.db_name,
        }
        cls.db = Database(cls.config).connect()
        cls.repo = Repository(cls.db)
        cls.live = LiveServer().__enter__()
        base = f"http://127.0.0.1:{cls.live.port}/v1"
        cls.provider_id = cls.repo.create_provider(
            Provider(
                id=0,
                alias="LAN Mock",
                provider="openai",
                base_url=base,
                api_key="test",
                model="mock-openai",
                context_window=10_000,
                max_output_tokens=100,
                temperature=0.2,
                is_default=True,
            )
        )
        cls.conversation_id = cls.repo.create_conversation(cls.provider_id)
        cls.repo.rename_conversation(cls.conversation_id, "LAN 测试对话", auto=False)
        cls.repo.add_message(
            cls.conversation_id,
            "user",
            "hello",
            attachments=[
                Attachment(
                    filename="notes.txt",
                    mime_type="text/plain",
                    kind="text",
                    size_bytes=5,
                    token_count=2,
                    data=b"hello",
                )
            ],
        )
        cls.repo.add_message(cls.conversation_id, "assistant", "**hi** there")

    @classmethod
    def tearDownClass(cls) -> None:
        cls.db.close()
        cls.live.__exit__(None, None, None)
        conn = pymysql.connect(
            host="127.0.0.1",
            port=3306,
            user="root",
            password="",
            autocommit=True,
        )
        try:
            with conn.cursor() as cursor:
                cursor.execute(f"DROP DATABASE IF EXISTS `{cls.db_name}`")
        finally:
            conn.close()

    def setUp(self) -> None:
        self.port = _free_port()
        self.changes: list[int] = []
        self.server = LanShareServer(
            lambda: self.config,
            on_change=self.changes.append,
            port=self.port,
            token="testtoken",
        )
        self.server.start()
        self.base = f"http://127.0.0.1:{self.port}"

    def tearDown(self) -> None:
        self.server.stop()

    def test_authentication_and_mobile_page(self) -> None:
        with httpx.Client(timeout=10) as client:
            login = client.get(self.base + "/")
            self.assertEqual(login.status_code, 200)
            self.assertIn("访问码", login.text)
            wrong = client.get(self.base + "/?token=wrong")
            self.assertEqual(wrong.status_code, 403)
            page = client.get(self.base + "/?token=testtoken")
            self.assertEqual(page.status_code, 200)
            self.assertIn("API Chat", page.text)
            unauthorized = client.get(self.base + "/api/conversations")
            self.assertEqual(unauthorized.status_code, 401)

    def test_list_and_messages_with_attachment(self) -> None:
        with httpx.Client(timeout=10) as client:
            response = client.get(self.base + "/api/conversations?token=testtoken")
            self.assertEqual(response.status_code, 200)
            conversations = response.json()["conversations"]
            self.assertTrue(any(item["id"] == self.conversation_id for item in conversations))
            response = client.get(
                self.base + f"/api/conversations/{self.conversation_id}?token=testtoken"
            )
            self.assertEqual(response.status_code, 200)
            messages = response.json()["messages"]
            self.assertEqual(len(messages), 2)
            self.assertIn("<strong>hi</strong>", messages[1]["html"])
            self.assertNotIn("<script>", messages[1]["html"])
            attachment_id = messages[0]["attachments"][0]["id"]
            attachment = client.get(
                self.base + f"/api/attachments/{attachment_id}?token=testtoken"
            )
            self.assertEqual(attachment.status_code, 200)
            self.assertEqual(attachment.content, b"hello")

    def test_create_and_send_message(self) -> None:
        with httpx.Client(timeout=30) as client:
            created = client.post(self.base + "/api/conversations?token=testtoken", json={})
            self.assertEqual(created.status_code, 201)
            conversation_id = created.json()["conversation"]["id"]
            response = client.post(
                self.base + f"/api/conversations/{conversation_id}/messages?token=testtoken",
                json={"content": "来自手机的消息"},
            )
            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertTrue(payload["reply"]["content"])
            self.assertGreater(payload["usage"]["total_tokens"], 0)
        self.assertIn(conversation_id, self.changes)
        messages = self.repo.list_messages(conversation_id)
        self.assertEqual([message.role for message in messages], ["user", "assistant"])

    def test_stop_sharing_closes_listener_and_connections(self) -> None:
        with httpx.Client(timeout=5, trust_env=False) as client:
            first = client.get(self.base + "/?token=testtoken")
            self.assertEqual(first.status_code, 200)
            self.server.stop()
            self.assertFalse(self.server.running)
            with self.assertRaises(httpx.HTTPError):
                client.get(self.base + "/?token=testtoken")

        # The same port can be used again immediately after stopping.
        restarted = LanShareServer(
            lambda: self.config,
            port=self.port,
            token="testtoken",
        )
        restarted.start()
        try:
            with httpx.Client(timeout=5, trust_env=False) as client:
                self.assertEqual(
                    client.get(self.base + "/?token=testtoken").status_code, 200
                )
        finally:
            restarted.stop()


if __name__ == "__main__":
    unittest.main()
