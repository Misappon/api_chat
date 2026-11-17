"""CRUD and aggregate queries for the chat database."""

from __future__ import annotations

import re
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Optional

import pymysql

from .db import Database
from .models import (
    ApiUsageRow,
    Conversation,
    DashboardRow,
    DashboardTotals,
    Message,
    Provider,
)
from .tokens import estimate_tokens, message_tokens, remaining_percent

EMAIL_LIKE = re.compile(r"\S+@\S+")


class RepositoryError(RuntimeError):
    pass


def _dt(value: Any) -> Optional[datetime]:
    return value if isinstance(value, datetime) else None


class Repository:
    def __init__(self, database: Database) -> None:
        self.db = database

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    @contextmanager
    def _transaction(self):
        conn = self.db.connection
        if conn is None:
            self.db.connect(create_database=False)
            conn = self.db.connection
        assert conn is not None
        try:
            conn.begin()
            with conn.cursor() as cursor:
                yield cursor
            conn.commit()
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            raise

    @staticmethod
    def _provider_from_row(row: dict[str, Any]) -> Provider:
        return Provider(
            id=int(row["id"]),
            alias=row["alias"],
            provider=row["provider"],
            base_url=row["base_url"],
            api_key=row["api_key"] or "",
            model=row["model"],
            context_window=int(row["context_window"] or 128_000),
            max_output_tokens=int(row["max_output_tokens"] or 4096),
            temperature=float(row["temperature"] or 0.7),
            system_prompt=row["system_prompt"] or "",
            is_default=bool(row["is_default"]),
            created_at=_dt(row.get("created_at")),
            updated_at=_dt(row.get("updated_at")),
        )

    @staticmethod
    def _conversation_from_row(row: dict[str, Any]) -> Conversation:
        return Conversation(
            id=int(row["id"]),
            title=row["title"],
            api_id=int(row["api_id"]) if row.get("api_id") is not None else None,
            title_auto=bool(row["title_auto"]),
            created_at=_dt(row.get("created_at")),
            updated_at=_dt(row.get("updated_at")),
            last_message_at=_dt(row.get("last_message_at")),
            api_alias=row.get("api_alias") or "",
            model=row.get("model") or "",
            context_window=int(row.get("context_window") or 128_000),
            system_prompt=row.get("system_prompt") or "",
            message_count=int(row.get("message_count") or 0),
            context_tokens=int(row.get("context_tokens") or 0),
            usage_total=int(row.get("usage_total") or 0),
            request_count=int(row.get("request_count") or 0),
        )

    @staticmethod
    def _message_from_row(row: dict[str, Any]) -> Message:
        return Message(
            id=int(row["id"]),
            conversation_id=int(row["conversation_id"]),
            role=row["role"],
            content=row["content"] or "",
            token_count=int(row["token_count"] or 0),
            model=row.get("model") or "",
            created_at=_dt(row.get("created_at")),
            updated_at=_dt(row.get("updated_at")),
            prompt_tokens=int(row.get("prompt_tokens") or 0),
            completion_tokens=int(row.get("completion_tokens") or 0),
            usage_total=int(row.get("usage_total") or 0),
        )

    # ------------------------------------------------------------------
    # providers
    # ------------------------------------------------------------------
    def list_providers(self) -> list[Provider]:
        try:
            with self.db.cursor() as cursor:
                cursor.execute(
                    "SELECT * FROM api_providers ORDER BY is_default DESC, alias ASC"
                )
                return [self._provider_from_row(row) for row in cursor.fetchall()]
        except Exception as exc:
            raise RepositoryError(f"读取 API 列表失败：{exc}") from exc

    def get_provider(self, provider_id: int) -> Optional[Provider]:
        with self.db.cursor() as cursor:
            cursor.execute("SELECT * FROM api_providers WHERE id=%s", (provider_id,))
            row = cursor.fetchone()
        return self._provider_from_row(row) if row else None

    def default_provider(self) -> Optional[Provider]:
        with self.db.cursor() as cursor:
            cursor.execute(
                "SELECT * FROM api_providers ORDER BY is_default DESC, id ASC LIMIT 1"
            )
            row = cursor.fetchone()
        return self._provider_from_row(row) if row else None

    def create_provider(self, provider: Provider) -> int:
        try:
            with self._transaction() as cursor:
                cursor.execute("SELECT COUNT(*) AS c FROM api_providers")
                first = int(cursor.fetchone()["c"]) == 0
                make_default = bool(provider.is_default or first)
                if make_default:
                    cursor.execute("UPDATE api_providers SET is_default=0")
                cursor.execute(
                    """
                    INSERT INTO api_providers
                        (alias, provider, base_url, api_key, model, context_window,
                         max_output_tokens, temperature, system_prompt, is_default)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    """,
                    (
                        provider.alias.strip(),
                        provider.provider,
                        provider.base_url.strip(),
                        provider.api_key,
                        provider.model.strip(),
                        max(256, int(provider.context_window)),
                        max(1, int(provider.max_output_tokens)),
                        float(provider.temperature),
                        provider.system_prompt or "",
                        1 if make_default else 0,
                    ),
                )
                return int(cursor.lastrowid)
        except pymysql.err.IntegrityError as exc:
            if exc.args and exc.args[0] == 1062:
                raise RepositoryError(f"别名「{provider.alias}」已存在，请换一个别名。") from exc
            raise RepositoryError(f"保存 API 失败：{exc}") from exc
        except Exception as exc:
            raise RepositoryError(f"保存 API 失败：{exc}") from exc

    def update_provider(self, provider: Provider) -> None:
        try:
            with self._transaction() as cursor:
                if provider.is_default:
                    cursor.execute("UPDATE api_providers SET is_default=0")
                cursor.execute(
                    """
                    UPDATE api_providers SET
                        alias=%s, provider=%s, base_url=%s, api_key=%s, model=%s,
                        context_window=%s, max_output_tokens=%s, temperature=%s,
                        system_prompt=%s, is_default=%s
                    WHERE id=%s
                    """,
                    (
                        provider.alias.strip(),
                        provider.provider,
                        provider.base_url.strip(),
                        provider.api_key,
                        provider.model.strip(),
                        max(256, int(provider.context_window)),
                        max(1, int(provider.max_output_tokens)),
                        float(provider.temperature),
                        provider.system_prompt or "",
                        1 if provider.is_default else 0,
                        provider.id,
                    ),
                )
                cursor.execute(
                    "UPDATE usage_events SET api_alias=%s WHERE api_id=%s",
                    (provider.alias.strip(), provider.id),
                )
        except pymysql.err.IntegrityError as exc:
            if exc.args and exc.args[0] == 1062:
                raise RepositoryError(f"别名「{provider.alias}」已存在，请换一个别名。") from exc
            raise RepositoryError(f"更新 API 失败：{exc}") from exc

    def delete_provider(self, provider_id: int) -> None:
        try:
            with self._transaction() as cursor:
                cursor.execute("SELECT is_default FROM api_providers WHERE id=%s", (provider_id,))
                row = cursor.fetchone()
                if not row:
                    return
                was_default = bool(row["is_default"])
                cursor.execute(
                    "SELECT id FROM api_providers WHERE id<>%s ORDER BY is_default DESC, id ASC LIMIT 1",
                    (provider_id,),
                )
                replacement = cursor.fetchone()
                replacement_id = int(replacement["id"]) if replacement else None
                cursor.execute(
                    "UPDATE conversations SET api_id=%s WHERE api_id=%s",
                    (replacement_id, provider_id),
                )
                cursor.execute("DELETE FROM api_providers WHERE id=%s", (provider_id,))
                if was_default and replacement_id is not None:
                    cursor.execute(
                        "UPDATE api_providers SET is_default=1 WHERE id=%s", (replacement_id,)
                    )
        except Exception as exc:
            raise RepositoryError(f"删除 API 失败：{exc}") from exc

    def set_default_provider(self, provider_id: int) -> None:
        try:
            with self._transaction() as cursor:
                cursor.execute("UPDATE api_providers SET is_default=0")
                cursor.execute(
                    "UPDATE api_providers SET is_default=1 WHERE id=%s", (provider_id,)
                )
        except Exception as exc:
            raise RepositoryError(f"设置默认 API 失败：{exc}") from exc

    # ------------------------------------------------------------------
    # conversations
    # ------------------------------------------------------------------
    def create_conversation(self, api_id: Optional[int] = None, title: str = "新对话") -> int:
        try:
            with self.db.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO conversations (title, api_id, title_auto) VALUES (%s,%s,1)",
                    (title[:200], api_id),
                )
                return int(cursor.lastrowid)
        except Exception as exc:
            raise RepositoryError(f"创建对话失败：{exc}") from exc

    def list_conversations(self, search: str = "") -> list[Conversation]:
        sql = """
            SELECT c.*,
                   COALESCE(p.alias, '') AS api_alias,
                   COALESCE(p.model, '') AS model,
                   COALESCE(p.context_window, 128000) AS context_window,
                   COALESCE(p.system_prompt, '') AS system_prompt,
                   (SELECT COUNT(*) FROM messages m WHERE m.conversation_id=c.id) AS message_count,
                   (SELECT COALESCE(SUM(m.token_count),0) FROM messages m
                     WHERE m.conversation_id=c.id) AS context_tokens,
                   (SELECT COALESCE(SUM(u.total_tokens),0) FROM usage_events u
                     WHERE u.conversation_id=c.id AND u.kind IN ('chat','title')) AS usage_total,
                   (SELECT COUNT(*) FROM usage_events u
                     WHERE u.conversation_id=c.id AND u.kind IN ('chat','title')) AS request_count
            FROM conversations c
            LEFT JOIN api_providers p ON p.id=c.api_id
        """
        params: list[Any] = []
        if search.strip():
            sql += " WHERE c.title LIKE %s"
            params.append(f"%{search.strip()}%")
        sql += " ORDER BY COALESCE(c.last_message_at, c.created_at) DESC, c.id DESC"
        try:
            with self.db.cursor() as cursor:
                cursor.execute(sql, params)
                return [self._conversation_from_row(row) for row in cursor.fetchall()]
        except Exception as exc:
            raise RepositoryError(f"读取对话列表失败：{exc}") from exc

    def get_conversation(self, conversation_id: int) -> Optional[Conversation]:
        sql = """
            SELECT c.*,
                   COALESCE(p.alias, '') AS api_alias,
                   COALESCE(p.model, '') AS model,
                   COALESCE(p.context_window, 128000) AS context_window,
                   COALESCE(p.system_prompt, '') AS system_prompt,
                   (SELECT COUNT(*) FROM messages m WHERE m.conversation_id=c.id) AS message_count,
                   (SELECT COALESCE(SUM(m.token_count),0) FROM messages m
                     WHERE m.conversation_id=c.id) AS context_tokens,
                   (SELECT COALESCE(SUM(u.total_tokens),0) FROM usage_events u
                     WHERE u.conversation_id=c.id AND u.kind IN ('chat','title')) AS usage_total,
                   (SELECT COUNT(*) FROM usage_events u
                     WHERE u.conversation_id=c.id AND u.kind IN ('chat','title')) AS request_count
            FROM conversations c
            LEFT JOIN api_providers p ON p.id=c.api_id
            WHERE c.id=%s
        """
        with self.db.cursor() as cursor:
            cursor.execute(sql, (conversation_id,))
            row = cursor.fetchone()
        return self._conversation_from_row(row) if row else None

    def rename_conversation(self, conversation_id: int, title: str, auto: bool = False) -> None:
        title = title.strip()[:200] or "新对话"
        try:
            with self.db.cursor() as cursor:
                cursor.execute(
                    "UPDATE conversations SET title=%s, title_auto=%s WHERE id=%s",
                    (title, 1 if auto else 0, conversation_id),
                )
        except Exception as exc:
            raise RepositoryError(f"重命名对话失败：{exc}") from exc

    def set_conversation_api(self, conversation_id: int, provider_id: Optional[int]) -> None:
        try:
            with self.db.cursor() as cursor:
                cursor.execute(
                    "UPDATE conversations SET api_id=%s WHERE id=%s",
                    (provider_id, conversation_id),
                )
        except Exception as exc:
            raise RepositoryError(f"切换 API 失败：{exc}") from exc

    def delete_conversation(self, conversation_id: int) -> None:
        try:
            with self.db.cursor() as cursor:
                cursor.execute("DELETE FROM conversations WHERE id=%s", (conversation_id,))
        except Exception as exc:
            raise RepositoryError(f"删除对话失败：{exc}") from exc

    def clear_messages(self, conversation_id: int) -> None:
        try:
            with self._transaction() as cursor:
                cursor.execute(
                    "DELETE FROM usage_events WHERE conversation_id=%s", (conversation_id,)
                )
                cursor.execute(
                    "DELETE FROM messages WHERE conversation_id=%s", (conversation_id,)
                )
                cursor.execute(
                    "UPDATE conversations SET last_message_at=NULL WHERE id=%s",
                    (conversation_id,),
                )
        except Exception as exc:
            raise RepositoryError(f"清空对话失败：{exc}") from exc

    # ------------------------------------------------------------------
    # messages
    # ------------------------------------------------------------------
    def list_messages(self, conversation_id: int) -> list[Message]:
        sql = """
            SELECT m.*,
                   COALESCE(u.prompt_tokens,0) AS prompt_tokens,
                   COALESCE(u.completion_tokens,0) AS completion_tokens,
                   COALESCE(u.total_tokens,0) AS usage_total
            FROM messages m
            LEFT JOIN (
                SELECT message_id,
                       SUM(prompt_tokens) AS prompt_tokens,
                       SUM(completion_tokens) AS completion_tokens,
                       SUM(total_tokens) AS total_tokens
                FROM usage_events
                WHERE message_id IS NOT NULL AND kind='chat'
                GROUP BY message_id
            ) u ON u.message_id=m.id
            WHERE m.conversation_id=%s
            ORDER BY m.id ASC
        """
        try:
            with self.db.cursor() as cursor:
                cursor.execute(sql, (conversation_id,))
                return [self._message_from_row(row) for row in cursor.fetchall()]
        except Exception as exc:
            raise RepositoryError(f"读取消息失败：{exc}") from exc

    def get_message(self, message_id: int) -> Optional[Message]:
        with self.db.cursor() as cursor:
            cursor.execute(
                """
                SELECT m.*, 0 AS prompt_tokens, 0 AS completion_tokens, 0 AS usage_total
                FROM messages m WHERE m.id=%s
                """,
                (message_id,),
            )
            row = cursor.fetchone()
        return self._message_from_row(row) if row else None

    def add_message(
        self,
        conversation_id: int,
        role: str,
        content: str,
        *,
        model: str = "",
        token_count: Optional[int] = None,
        usage: Optional[dict[str, Any]] = None,
    ) -> int:
        tokens = int(token_count) if token_count is not None else message_tokens(role, content)
        try:
            with self._transaction() as cursor:
                cursor.execute(
                    """
                    INSERT INTO messages (conversation_id, role, content, token_count, model)
                    VALUES (%s,%s,%s,%s,%s)
                    """,
                    (conversation_id, role, content, max(0, tokens), model or ""),
                )
                message_id = int(cursor.lastrowid)
                if usage:
                    prompt = int(usage.get("prompt_tokens") or 0)
                    completion = int(usage.get("completion_tokens") or 0)
                    total = int(usage.get("total_tokens") or prompt + completion)
                    cursor.execute(
                        """
                        INSERT INTO usage_events
                            (conversation_id, message_id, api_id, api_alias, model, kind,
                             prompt_tokens, completion_tokens, total_tokens)
                        VALUES (%s,%s,%s,%s,%s,'chat',%s,%s,%s)
                        """,
                        (
                            conversation_id,
                            message_id,
                            usage.get("api_id"),
                            usage.get("api_alias") or "",
                            usage.get("model") or model or "",
                            prompt,
                            completion,
                            total,
                        ),
                    )
                cursor.execute(
                    "UPDATE conversations SET last_message_at=NOW(6) WHERE id=%s",
                    (conversation_id,),
                )
                return message_id
        except Exception as exc:
            raise RepositoryError(f"保存消息失败：{exc}") from exc

    def update_message(
        self, message_id: int, content: str, *, token_count: Optional[int] = None
    ) -> None:
        tokens = int(token_count) if token_count is not None else estimate_tokens(content)
        try:
            with self.db.cursor() as cursor:
                cursor.execute(
                    "UPDATE messages SET content=%s, token_count=%s WHERE id=%s",
                    (content, max(0, tokens), message_id),
                )
        except Exception as exc:
            raise RepositoryError(f"修改消息失败：{exc}") from exc

    def edit_and_truncate(
        self,
        conversation_id: int,
        message_id: int,
        content: str,
        *,
        keep_target: bool = True,
    ) -> int:
        """Edit one message and remove everything after it.

        When keep_target is False the target itself is removed too, which is
        used to regenerate an assistant answer from preceding history.
        Returns the number of deleted messages.
        """
        try:
            with self._transaction() as cursor:
                cursor.execute(
                    "SELECT id, role FROM messages WHERE id=%s AND conversation_id=%s",
                    (message_id, conversation_id),
                )
                target = cursor.fetchone()
                if not target:
                    raise RepositoryError("要修改的消息已不存在，请刷新对话。")
                if keep_target:
                    cursor.execute(
                        "UPDATE messages SET content=%s, token_count=%s WHERE id=%s",
                        (content, message_tokens(target["role"], content), message_id),
                    )
                    cursor.execute(
                        "DELETE FROM messages WHERE conversation_id=%s AND id>%s",
                        (conversation_id, message_id),
                    )
                else:
                    cursor.execute(
                        "DELETE FROM messages WHERE conversation_id=%s AND id>=%s",
                        (conversation_id, message_id),
                    )
                deleted = int(cursor.rowcount or 0)
                cursor.execute(
                    """
                    UPDATE conversations SET last_message_at=(
                        SELECT MAX(created_at) FROM messages WHERE conversation_id=%s
                    ) WHERE id=%s
                    """,
                    (conversation_id, conversation_id),
                )
                return deleted
        except RepositoryError:
            raise
        except Exception as exc:
            raise RepositoryError(f"修改并重提交失败：{exc}") from exc

    def record_usage(
        self,
        conversation_id: int,
        provider: Provider,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        total_tokens: int = 0,
        *,
        kind: str = "title",
        message_id: Optional[int] = None,
    ) -> None:
        try:
            with self.db.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO usage_events
                        (conversation_id, message_id, api_id, api_alias, model, kind,
                         prompt_tokens, completion_tokens, total_tokens)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    """,
                    (
                        conversation_id,
                        message_id,
                        provider.id,
                        provider.alias,
                        model or provider.model,
                        kind,
                        int(prompt_tokens),
                        int(completion_tokens),
                        int(total_tokens or (prompt_tokens + completion_tokens)),
                    ),
                )
        except Exception as exc:
            raise RepositoryError(f"记录用量失败：{exc}") from exc

    # ------------------------------------------------------------------
    # dashboard
    # ------------------------------------------------------------------
    def dashboard(self) -> tuple[DashboardTotals, list[DashboardRow], list[ApiUsageRow]]:
        try:
            with self.db.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT COUNT(DISTINCT c.id) AS conversation_count,
                           COALESCE(SUM(u.prompt_tokens),0) AS prompt_tokens,
                           COALESCE(SUM(u.completion_tokens),0) AS completion_tokens,
                           COALESCE(SUM(u.total_tokens),0) AS total_tokens,
                           COUNT(u.id) AS request_count
                    FROM conversations c
                    LEFT JOIN usage_events u
                      ON u.conversation_id=c.id AND u.kind IN ('chat','title')
                    """
                )
                totals_row = cursor.fetchone()
                totals = DashboardTotals(
                    conversation_count=int(totals_row["conversation_count"] or 0),
                    request_count=int(totals_row["request_count"] or 0),
                    prompt_tokens=int(totals_row["prompt_tokens"] or 0),
                    completion_tokens=int(totals_row["completion_tokens"] or 0),
                    total_tokens=int(totals_row["total_tokens"] or 0),
                )

                cursor.execute(
                    """
                    SELECT c.id, c.title, c.last_message_at, c.updated_at,
                           COALESCE(p.alias,'') AS api_alias,
                           COALESCE(p.model,'') AS model,
                           COALESCE(p.context_window,128000) AS context_window,
                           COALESCE(p.system_prompt,'') AS system_prompt,
                           (SELECT COUNT(*) FROM messages m WHERE m.conversation_id=c.id) AS message_count,
                           (SELECT COALESCE(SUM(m.token_count),0) FROM messages m
                             WHERE m.conversation_id=c.id) AS context_tokens,
                           (SELECT COUNT(*) FROM usage_events u
                             WHERE u.conversation_id=c.id AND u.kind IN ('chat','title')) AS request_count,
                           (SELECT COALESCE(SUM(u.prompt_tokens),0) FROM usage_events u
                             WHERE u.conversation_id=c.id AND u.kind IN ('chat','title')) AS prompt_tokens,
                           (SELECT COALESCE(SUM(u.completion_tokens),0) FROM usage_events u
                             WHERE u.conversation_id=c.id AND u.kind IN ('chat','title')) AS completion_tokens,
                           (SELECT COALESCE(SUM(u.total_tokens),0) FROM usage_events u
                             WHERE u.conversation_id=c.id AND u.kind IN ('chat','title')) AS total_tokens
                    FROM conversations c
                    LEFT JOIN api_providers p ON p.id=c.api_id
                    ORDER BY COALESCE(c.last_message_at,c.created_at) DESC
                    """
                )
                rows: list[DashboardRow] = []
                for row in cursor.fetchall():
                    system_extra = estimate_tokens(row["system_prompt"] or "")
                    used = int(row["context_tokens"] or 0) + system_extra
                    window = int(row["context_window"] or 128_000)
                    rows.append(
                        DashboardRow(
                            conversation_id=int(row["id"]),
                            title=row["title"],
                            api_alias=row["api_alias"] or "未绑定 API",
                            model=row["model"] or "",
                            message_count=int(row["message_count"] or 0),
                            request_count=int(row["request_count"] or 0),
                            prompt_tokens=int(row["prompt_tokens"] or 0),
                            completion_tokens=int(row["completion_tokens"] or 0),
                            total_tokens=int(row["total_tokens"] or 0),
                            context_tokens=used,
                            context_window=window,
                            last_activity=_dt(row["last_message_at"]) or _dt(row["updated_at"]),
                            remaining_percent=remaining_percent(used, window),
                        )
                    )

                cursor.execute(
                    """
                    SELECT COALESCE(u.api_alias,'未知 API') AS api_alias,
                           COALESCE(u.model,'') AS model,
                           COUNT(*) AS request_count,
                           COALESCE(SUM(u.prompt_tokens),0) AS prompt_tokens,
                           COALESCE(SUM(u.completion_tokens),0) AS completion_tokens,
                           COALESCE(SUM(u.total_tokens),0) AS total_tokens
                    FROM usage_events u
                    INNER JOIN conversations c ON c.id=u.conversation_id
                    WHERE u.kind IN ('chat','title')
                    GROUP BY u.api_alias, u.model
                    ORDER BY total_tokens DESC
                    """
                )
                api_rows = [
                    ApiUsageRow(
                        api_alias=row["api_alias"],
                        model=row["model"],
                        request_count=int(row["request_count"] or 0),
                        prompt_tokens=int(row["prompt_tokens"] or 0),
                        completion_tokens=int(row["completion_tokens"] or 0),
                        total_tokens=int(row["total_tokens"] or 0),
                    )
                    for row in cursor.fetchall()
                ]
                return totals, rows, api_rows
        except Exception as exc:
            raise RepositoryError(f"读取用量统计失败：{exc}") from exc

    # ------------------------------------------------------------------
    # misc
    # ------------------------------------------------------------------
    def api_messages(self, conversation_id: int) -> list[dict[str, str]]:
        """Message payload for the model, without DB-only metadata."""
        return [
            {"role": message.role, "content": message.content}
            for message in self.list_messages(conversation_id)
            if message.role in ("user", "assistant") and message.content.strip()
        ]

    def database_summary(self) -> dict[str, int]:
        with self.db.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) AS c FROM conversations")
            conversations = int(cursor.fetchone()["c"])
            cursor.execute("SELECT COUNT(*) AS c FROM api_providers")
            providers = int(cursor.fetchone()["c"])
        return {"conversations": conversations, "providers": providers}
