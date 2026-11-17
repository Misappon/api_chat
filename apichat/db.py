"""MySQL connection handling and schema bootstrap."""

from __future__ import annotations

import re
from typing import Any

import pymysql
from pymysql.cursors import DictCursor

DB_NAME_RE = re.compile(r"^[A-Za-z0-9_]{1,64}$")

SCHEMA_VERSION = 1

SCHEMA_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS api_providers (
        id                 INT AUTO_INCREMENT PRIMARY KEY,
        alias              VARCHAR(80)  NOT NULL,
        provider           VARCHAR(32)  NOT NULL DEFAULT 'openai',
        base_url           VARCHAR(500) NOT NULL,
        api_key            TEXT         NOT NULL,
        model              VARCHAR(160) NOT NULL,
        context_window     INT          NOT NULL DEFAULT 128000,
        max_output_tokens  INT          NOT NULL DEFAULT 4096,
        temperature        DECIMAL(3,2) NOT NULL DEFAULT 0.70,
        system_prompt      TEXT         NOT NULL,
        is_default         TINYINT(1)   NOT NULL DEFAULT 0,
        created_at         DATETIME(6)  NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
        updated_at         DATETIME(6)  NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
                                        ON UPDATE CURRENT_TIMESTAMP(6),
        UNIQUE KEY uq_api_alias (alias)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS conversations (
        id               BIGINT AUTO_INCREMENT PRIMARY KEY,
        title            VARCHAR(200) NOT NULL DEFAULT '新对话',
        api_id           INT NULL,
        title_auto       TINYINT(1) NOT NULL DEFAULT 1,
        created_at       DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
        updated_at       DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
                                    ON UPDATE CURRENT_TIMESTAMP(6),
        last_message_at  DATETIME(6) NULL,
        KEY idx_conversations_recent (last_message_at, updated_at),
        CONSTRAINT fk_conversation_api FOREIGN KEY (api_id)
            REFERENCES api_providers(id) ON DELETE SET NULL
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS messages (
        id               BIGINT AUTO_INCREMENT PRIMARY KEY,
        conversation_id  BIGINT NOT NULL,
        role             VARCHAR(16) NOT NULL,
        content          LONGTEXT NOT NULL,
        token_count      INT NOT NULL DEFAULT 0,
        model            VARCHAR(160) NOT NULL DEFAULT '',
        created_at       DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
        updated_at       DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
                                    ON UPDATE CURRENT_TIMESTAMP(6),
        KEY idx_messages_conversation (conversation_id, id),
        CONSTRAINT fk_message_conversation FOREIGN KEY (conversation_id)
            REFERENCES conversations(id) ON DELETE CASCADE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS usage_events (
        id                 BIGINT AUTO_INCREMENT PRIMARY KEY,
        conversation_id    BIGINT NULL,
        message_id         BIGINT NULL,
        api_id             INT NULL,
        api_alias          VARCHAR(80) NOT NULL DEFAULT '',
        model              VARCHAR(160) NOT NULL DEFAULT '',
        kind               VARCHAR(16) NOT NULL DEFAULT 'chat',
        prompt_tokens      INT NOT NULL DEFAULT 0,
        completion_tokens  INT NOT NULL DEFAULT 0,
        total_tokens       INT NOT NULL DEFAULT 0,
        created_at         DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
        KEY idx_usage_conversation (conversation_id, created_at),
        KEY idx_usage_message (message_id),
        CONSTRAINT fk_usage_conversation FOREIGN KEY (conversation_id)
            REFERENCES conversations(id) ON DELETE CASCADE,
        CONSTRAINT fk_usage_message FOREIGN KEY (message_id)
            REFERENCES messages(id) ON DELETE CASCADE,
        CONSTRAINT fk_usage_api FOREIGN KEY (api_id)
            REFERENCES api_providers(id) ON DELETE SET NULL
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
    """
    CREATE TABLE IF NOT EXISTS app_meta (
        meta_key   VARCHAR(64) PRIMARY KEY,
        meta_value TEXT NOT NULL
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """,
]


class DatabaseError(RuntimeError):
    pass


def _friendly_mysql_error(exc: Exception, config: dict[str, Any]) -> str:
    host = config.get("host", "127.0.0.1")
    port = config.get("port", 3306)
    user = config.get("user", "root")
    if isinstance(exc, pymysql.err.OperationalError):
        code = exc.args[0] if exc.args else 0
        detail = str(exc.args[1] if len(exc.args) > 1 else exc)
        if code in (2003, 2013):
            return (
                f"无法连接 MySQL 服务器 {host}:{port}。\n"
                "请确认 MySQL 服务已启动，主机和端口填写正确。\n\n"
                f"详细信息：{detail}"
            )
        if code == 1045:
            return (
                f"MySQL 登录失败（用户 {user}）。\n"
                "请检查用户名和密码。\n\n"
                f"详细信息：{detail}"
            )
        if code == 1049:
            return f"数据库不存在，且自动创建失败：{detail}"
        return f"MySQL 连接错误（{code}）：{detail}"
    if isinstance(exc, pymysql.err.ProgrammingError):
        return f"数据库操作失败：{exc}"
    return f"MySQL 连接失败：{exc}"


class Database:
    """One MySQL connection owned by the GUI thread."""

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = {
            "host": str(config.get("host", "127.0.0.1")),
            "port": int(config.get("port", 3306)),
            "user": str(config.get("user", "root")),
            "password": str(config.get("password", "")),
            "name": str(config.get("name", "api_chat")),
        }
        self.connection: pymysql.connections.Connection | None = None

    @property
    def name(self) -> str:
        return self.config["name"]

    @property
    def is_connected(self) -> bool:
        return self.connection is not None and self.connection.open

    def connect(self, create_database: bool = True) -> "Database":
        name = self.config["name"]
        if not DB_NAME_RE.match(name):
            raise DatabaseError("数据库名只能包含字母、数字和下划线，且长度不超过 64 个字符。")
        try:
            if create_database:
                bootstrap = pymysql.connect(
                    host=self.config["host"],
                    port=self.config["port"],
                    user=self.config["user"],
                    password=self.config["password"],
                    charset="utf8mb4",
                    cursorclass=DictCursor,
                    autocommit=True,
                    connect_timeout=8,
                )
                try:
                    with bootstrap.cursor() as cursor:
                        cursor.execute(
                            f"CREATE DATABASE IF NOT EXISTS `{name}` "
                            "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
                        )
                finally:
                    bootstrap.close()
            self.connection = pymysql.connect(
                host=self.config["host"],
                port=self.config["port"],
                user=self.config["user"],
                password=self.config["password"],
                database=name,
                charset="utf8mb4",
                cursorclass=DictCursor,
                autocommit=True,
                connect_timeout=8,
            )
        except Exception as exc:  # converted to a message the UI can display
            raise DatabaseError(_friendly_mysql_error(exc, self.config)) from exc
        self.ensure_schema()
        return self

    def ensure_schema(self) -> None:
        if self.connection is None:
            raise DatabaseError("尚未连接数据库。")
        try:
            with self.connection.cursor() as cursor:
                for statement in SCHEMA_STATEMENTS:
                    cursor.execute(statement)
                cursor.execute(
                    "INSERT INTO app_meta (meta_key, meta_value) VALUES ('schema_version', %s) "
                    "ON DUPLICATE KEY UPDATE meta_value = VALUES(meta_value)",
                    (str(SCHEMA_VERSION),),
                )
        except Exception as exc:
            raise DatabaseError(f"初始化数据表失败：{exc}") from exc

    def cursor(self) -> DictCursor:
        if self.connection is None or not self.connection.open:
            self.connect(create_database=False)
        assert self.connection is not None
        return self.connection.cursor()

    def ping(self) -> bool:
        try:
            if self.connection is None:
                return False
            self.connection.ping(reconnect=True)
            return True
        except Exception:
            return False

    def close(self) -> None:
        try:
            if self.connection is not None and self.connection.open:
                self.connection.close()
        except Exception:
            pass
        self.connection = None

    @staticmethod
    def list_databases(config: dict[str, Any]) -> list[str]:
        """List user databases on a server without changing the active DB."""
        try:
            conn = pymysql.connect(
                host=str(config.get("host", "127.0.0.1")),
                port=int(config.get("port", 3306)),
                user=str(config.get("user", "root")),
                password=str(config.get("password", "")),
                charset="utf8mb4",
                cursorclass=DictCursor,
                autocommit=True,
                connect_timeout=8,
            )
            try:
                with conn.cursor() as cursor:
                    cursor.execute("SHOW DATABASES")
                    names = [row["Database"] for row in cursor.fetchall()]
            finally:
                conn.close()
        except Exception as exc:
            raise DatabaseError(_friendly_mysql_error(exc, config)) from exc
        system = {"information_schema", "mysql", "performance_schema", "sys"}
        return sorted(name for name in names if name not in system)

    @staticmethod
    def test_connection(config: dict[str, Any]) -> str:
        """Open and close a connection, returning a short server description."""
        name = str(config.get("name", "api_chat"))
        if not DB_NAME_RE.match(name):
            raise DatabaseError("数据库名只能包含字母、数字和下划线。")
        try:
            conn = pymysql.connect(
                host=str(config.get("host", "127.0.0.1")),
                port=int(config.get("port", 3306)),
                user=str(config.get("user", "root")),
                password=str(config.get("password", "")),
                charset="utf8mb4",
                autocommit=True,
                connect_timeout=8,
            )
            try:
                with conn.cursor() as cursor:
                    cursor.execute("SELECT VERSION(), CURRENT_USER()")
                    version, user = cursor.fetchone()
            finally:
                conn.close()
        except Exception as exc:
            raise DatabaseError(_friendly_mysql_error(exc, config)) from exc
        return f"MySQL {version} · {user}"
