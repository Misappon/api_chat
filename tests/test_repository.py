"""Integration tests for the MySQL repository (temporary database)."""

from __future__ import annotations

import os
import sys
import unittest
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pymysql

from apichat.db import Database
from apichat.models import Attachment, Provider
from apichat.repository import Repository, RepositoryError
from apichat.tokens import message_tokens


class RepositoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.db_name = f"api_chat_test_{os.getpid()}_{uuid.uuid4().hex[:6]}"
        cls.db = Database(
            {
                "host": "127.0.0.1",
                "port": 3306,
                "user": "root",
                "password": "",
                "name": cls.db_name,
            }
        ).connect()
        cls.repo = Repository(cls.db)

    @classmethod
    def tearDownClass(cls) -> None:
        try:
            cls.db.close()
        finally:
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
        with self.db.cursor() as cursor:
            cursor.execute("SET FOREIGN_KEY_CHECKS=0")
            for table in ("usage_events", "messages", "conversations", "api_providers"):
                cursor.execute(f"DELETE FROM `{table}`")
            cursor.execute("SET FOREIGN_KEY_CHECKS=1")

    def _provider(self, alias: str, model: str = "test-model") -> Provider:
        provider_id = self.repo.create_provider(
            Provider(
                id=0,
                alias=alias,
                provider="openai",
                base_url="http://127.0.0.1:9999/v1",
                api_key="test",
                model=model,
                context_window=1000,
                max_output_tokens=100,
                temperature=0.5,
            )
        )
        provider = self.repo.get_provider(provider_id)
        assert provider is not None
        return provider

    def test_provider_crud_and_alias_uniqueness(self) -> None:
        first = self._provider("First")
        second = self._provider("Second")
        self.assertTrue(first.is_default)
        self.assertFalse(second.is_default)
        self.assertEqual(len(self.repo.list_providers()), 2)
        with self.assertRaises(RepositoryError):
            self._provider("First")
        self.repo.set_default_provider(second.id)
        self.assertTrue(self.repo.get_provider(second.id).is_default)
        second.alias = "Renamed"
        second.is_default = True
        self.repo.update_provider(second)
        self.assertEqual(self.repo.get_provider(second.id).alias, "Renamed")
        self.repo.delete_provider(second.id)
        remaining = self.repo.list_providers()
        self.assertEqual(len(remaining), 1)
        self.assertTrue(remaining[0].is_default)

    def test_conversation_usage_and_truncation(self) -> None:
        provider = self._provider("ChatAPI")
        conv_id = self.repo.create_conversation(provider.id)
        self.repo.rename_conversation(conv_id, "测试对话", auto=True)
        user_id = self.repo.add_message(conv_id, "user", "你好，介绍一下自己。")
        assistant_id = self.repo.add_message(
            conv_id,
            "assistant",
            "你好，我是一个测试助手。",
            model="test-model",
            usage={
                "api_id": provider.id,
                "api_alias": provider.alias,
                "model": "test-model",
                "prompt_tokens": 20,
                "completion_tokens": 10,
                "total_tokens": 30,
            },
        )
        user2 = self.repo.add_message(conv_id, "user", "再详细一点。")
        self.repo.add_message(
            conv_id,
            "assistant",
            "这是更详细的回答。",
            model="test-model",
            usage={
                "api_id": provider.id,
                "api_alias": provider.alias,
                "model": "test-model",
                "prompt_tokens": 40,
                "completion_tokens": 15,
                "total_tokens": 55,
            },
        )
        self.repo.record_usage(
            conv_id, provider, "test-model", 8, 2, 10, kind="title"
        )
        messages = self.repo.list_messages(conv_id)
        self.assertEqual(len(messages), 4)
        self.assertEqual(messages[1].prompt_tokens, 20)
        self.assertEqual(messages[1].completion_tokens, 10)
        conversation = self.repo.get_conversation(conv_id)
        self.assertEqual(conversation.request_count, 3)
        self.assertEqual(conversation.usage_total, 95)
        self.assertEqual(conversation.context_tokens, sum(m.token_count for m in messages))

        totals, rows, api_rows = self.repo.dashboard()
        self.assertEqual(totals.conversation_count, 1)
        self.assertEqual(totals.request_count, 3)
        self.assertEqual(totals.total_tokens, 95)
        self.assertEqual(rows[0].total_tokens, 95)
        self.assertGreaterEqual(rows[0].remaining_percent, 0)
        self.assertEqual(len(api_rows), 1)

        # Editing the first user message must remove messages after it and
        # cascade their usage events.
        self.repo.edit_and_truncate(conv_id, user_id, "你好，请只介绍名字。")
        remaining = self.repo.list_messages(conv_id)
        self.assertEqual(len(remaining), 1)
        self.assertEqual(remaining[0].content, "你好，请只介绍名字。")
        totals, _, _ = self.repo.dashboard()
        self.assertEqual(totals.request_count, 1)  # only the title usage remains
        self.assertEqual(totals.total_tokens, 10)
        self.assertNotIn(assistant_id, [m.id for m in remaining])
        self.assertNotIn(user2, [m.id for m in remaining])

        self.repo.clear_messages(conv_id)
        totals, _, _ = self.repo.dashboard()
        self.assertEqual(totals.request_count, 0)
        self.assertEqual(totals.total_tokens, 0)
        self.assertEqual(self.repo.list_messages(conv_id), [])

    def test_delete_provider_moves_conversations(self) -> None:
        first = self._provider("Primary")
        second = self._provider("Backup")
        conv_id = self.repo.create_conversation(first.id)
        self.repo.delete_provider(first.id)
        conversation = self.repo.get_conversation(conv_id)
        self.assertEqual(conversation.api_id, second.id)
        self.assertEqual(conversation.api_alias, "Backup")

    def test_reasoning_content_roundtrip(self) -> None:
        provider = self._provider("ReasoningAPI")
        conv_id = self.repo.create_conversation(provider.id)
        self.repo.add_message(
            conv_id,
            "assistant",
            "final answer",
            reasoning="private chain of thought",
            model="reasoner",
        )
        messages = self.repo.list_messages(conv_id)
        self.assertEqual(messages[0].reasoning_content, "private chain of thought")
        api_messages = self.repo.api_messages(conv_id)
        self.assertNotIn("reasoning_content", api_messages[0])

    def test_message_token_estimates_are_positive(self) -> None:
        self.assertGreater(message_tokens("user", "你好 hello"), 0)

    def test_attachment_roundtrip_and_token_preservation(self) -> None:
        provider = self._provider("AttachAPI")
        conv_id = self.repo.create_conversation(provider.id)
        attachment = Attachment(
            filename="notes.txt",
            mime_type="text/plain",
            kind="text",
            size_bytes=5,
            token_count=8,
            data=b"hello",
        )
        message_id = self.repo.add_message(
            conv_id,
            "user",
            "read this",
            model=provider.model,
            attachments=[attachment],
        )
        messages = self.repo.list_messages(conv_id)
        self.assertEqual(len(messages[0].attachments), 1)
        self.assertEqual(messages[0].attachments[0].filename, "notes.txt")
        self.assertEqual(messages[0].token_count, message_tokens("user", "read this") + 8)
        api_messages = self.repo.api_messages(conv_id)
        self.assertEqual(api_messages[0]["attachments"][0].data, b"hello")
        self.repo.update_message(message_id, "changed")
        self.assertEqual(
            self.repo.get_message(message_id).token_count,
            message_tokens("user", "changed") + 8,
        )
        fetched = self.repo.get_attachment(messages[0].attachments[0].id)
        self.assertEqual(fetched.data, b"hello")


if __name__ == "__main__":
    unittest.main()
