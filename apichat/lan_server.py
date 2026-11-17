"""Small authenticated HTTP server for using API Chat from a phone on the LAN."""

from __future__ import annotations

import base64
import binascii
import html
import hmac
import json
import mimetypes
import secrets
import socket
import threading
from datetime import datetime
from html.parser import HTMLParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable, Optional
from urllib.parse import parse_qs, quote, urlparse

import markdown

from .attachment_utils import (
    MAX_ATTACHMENTS,
    AttachmentError,
    attachment_from_bytes,
    attachment_limits_mb,
    max_request_bytes,
)
from .db import Database
from .llm import LLMClient
from .models import Conversation, Message
from .repository import Repository
from .tokens import context_tokens, estimate_tokens

MAX_MESSAGE_CHARS = 20_000


class LanServerError(RuntimeError):
    pass


def local_lan_ip() -> str:
    """Best-effort primary LAN address (no traffic is actually sent)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            return sock.getsockname()[0]
    except OSError:
        try:
            return socket.gethostbyname(socket.gethostname())
        except OSError:
            return "127.0.0.1"


def new_access_token() -> str:
    return secrets.token_urlsafe(6)


def _iso(value: Optional[datetime]) -> str:
    return value.isoformat(timespec="seconds") if value else ""


_MARKDOWN_TAGS = {
    "p", "br", "hr", "strong", "em", "del", "code", "pre",
    "h1", "h2", "h3", "h4", "blockquote", "ul", "ol", "li",
    "table", "thead", "tbody", "tr", "th", "td", "a",
}


class _SafeMarkdownParser(HTMLParser):
    """Keep markdown output inert and strip scripts/event attributes."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._stack: list[Optional[str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        tag = tag.lower()
        if tag not in _MARKDOWN_TAGS:
            self._stack.append(None)
            return
        attributes: list[tuple[str, str]] = []
        if tag == "a":
            href = next((value or "" for key, value in attrs if key.lower() == "href"), "")
            if not href.lower().startswith(("http://", "https://")):
                self._stack.append(None)
                return
            attributes = [
                ("href", html.escape(href, quote=True)),
                ("target", "_blank"),
                ("rel", "noopener noreferrer"),
            ]
        attr_text = "".join(f' {key}="{value}"' for key, value in attributes)
        self.parts.append(f"<{tag}{attr_text}>")
        self._stack.append(tag)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        if tag.lower() in {"br", "hr"}:
            self.parts.append(f"<{tag.lower()}>")
            return
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        if not self._stack:
            return
        open_tag = self._stack.pop()
        if open_tag == tag.lower():
            self.parts.append(f"</{tag.lower()}>")

    def handle_data(self, data: str) -> None:
        self.parts.append(html.escape(data, quote=False))


def _markdown_html(text: str) -> str:
    escaped = html.escape(text or "", quote=False)
    rendered = markdown.markdown(
        escaped,
        extensions=["fenced_code", "tables", "sane_lists", "nl2br"],
        output_format="html",
    )
    parser = _SafeMarkdownParser()
    parser.feed(rendered)
    parser.close()
    return "".join(parser.parts)


def _conversation_json(conversation: Conversation) -> dict[str, Any]:
    return {
        "id": conversation.id,
        "title": conversation.title,
        "api_alias": conversation.api_alias,
        "model": conversation.model,
        "message_count": conversation.message_count,
        "usage_total": conversation.usage_total,
        "context_tokens": conversation.context_tokens,
        "context_window": conversation.context_window,
        "remaining_percent": round(conversation.remaining_percent, 1),
        "last_message_at": _iso(conversation.last_message_at),
        "updated_at": _iso(conversation.updated_at),
    }


def _message_json(message: Message) -> dict[str, Any]:
    return {
        "id": message.id,
        "role": message.role,
        "content": message.content,
        "html": _markdown_html(message.content),
        "created_at": _iso(message.created_at),
        "token_count": message.token_count,
        "attachments": [
            {
                "id": attachment.id,
                "filename": attachment.filename,
                "mime_type": attachment.mime_type,
                "kind": attachment.kind,
                "size_bytes": attachment.size_bytes,
                "width": attachment.width,
                "height": attachment.height,
            }
            for attachment in message.attachments
        ],
    }


class _Handler(BaseHTTPRequestHandler):
    server_version = "APIChatLAN/1.0"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):  # noqa: A002
        return

    @property
    def share(self) -> "LanShareServer":
        return self.server.share_server  # type: ignore[attr-defined]

    def setup(self) -> None:
        super().setup()
        self.share.add_connection(self.connection)

    def finish(self) -> None:
        try:
            super().finish()
        finally:
            self.share.remove_connection(self.connection)

    def _write(self, data: bytes) -> None:
        try:
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
            self.close_connection = True

    # ------------------------------------------------------------------
    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path == "/favicon.ico":
            self.send_response(204)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if path == "/":
            if self._token_ok():
                self._send_html(MOBILE_HTML)
            elif self._query_token():
                self._send_html(
                    "<html><body style='background:#0b0e14;color:#ff9fac;"
                    "font-family:sans-serif;padding:40px'>访问码不正确。</body></html>",
                    status=403,
                )
            else:
                self._send_html(LOGIN_HTML)
            return
        if not path.startswith("/api/"):
            self._send_json({"error": "not found"}, 404)
            return
        if not self._token_ok():
            self._send_json({"error": "unauthorized"}, 401)
            return
        try:
            if path == "/api/conversations":
                self._handle_list_conversations()
            elif path == "/api/limits":
                self._handle_limits()
            elif path.startswith("/api/conversations/"):
                self._handle_get_conversation(path)
            elif path.startswith("/api/attachments/"):
                self._handle_attachment(path)
            else:
                self._send_json({"error": "not found"}, 404)
        except Exception as exc:
            self._send_json({"error": f"服务端错误：{exc}"}, 500)

    def do_POST(self) -> None:  # noqa: N802
        if not self._token_ok():
            self._send_json({"error": "unauthorized"}, 401)
            return
        path = urlparse(self.path).path
        try:
            body = self._read_json()
            if path == "/api/conversations":
                self._handle_create_conversation()
            elif path.startswith("/api/conversations/") and path.endswith("/messages"):
                self._handle_send_message(path, body)
            else:
                self._send_json({"error": "not found"}, 404)
        except LanServerError as exc:
            self._send_json({"error": str(exc)}, 400)
        except Exception as exc:
            self._send_json({"error": f"服务端错误：{exc}"}, 500)

    # ------------------------------------------------------------------
    def _query_token(self) -> str:
        query = parse_qs(urlparse(self.path).query)
        return (query.get("token") or [""])[0]

    def _token_ok(self) -> bool:
        token = self._query_token() or self.headers.get("X-Share-Token", "")
        return bool(token) and hmac.compare_digest(token, self.share.token)

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0") or 0)
        if length > max_request_bytes():
            raise LanServerError("请求过大")
        raw = self.rfile.read(length) if length else b"{}"
        try:
            data = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            raise LanServerError("请求格式错误") from exc
        return data if isinstance(data, dict) else {}

    def _send_json(self, payload: dict, status: int = 200) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Connection", "close")
        self.close_connection = True
        self.end_headers()
        self._write(data)

    def _send_html(self, content: str, status: int = 200) -> None:
        data = content.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self' data:; style-src 'unsafe-inline'; "
            "script-src 'unsafe-inline'; img-src 'self' data:;",
        )
        self.send_header("Connection", "close")
        self.close_connection = True
        self.end_headers()
        self._write(data)

    def _repo(self) -> tuple[Database, Repository]:
        config = self.share.db_config_getter()
        db = Database(config).connect(create_database=False)
        return db, Repository(db)

    def _handle_limits(self) -> None:
        image_mb, text_mb = attachment_limits_mb()
        self._send_json(
            {
                "image_mb": image_mb,
                "text_mb": text_mb,
                "max_attachments": MAX_ATTACHMENTS,
            }
        )

    def _handle_list_conversations(self) -> None:
        db, repo = self._repo()
        try:
            conversations = repo.list_conversations()
            self._send_json(
                {
                    "database": db.name,
                    "conversations": [_conversation_json(item) for item in conversations],
                }
            )
        finally:
            db.close()

    def _conversation_id(self, path: str) -> int:
        parts = path.strip("/").split("/")
        try:
            return int(parts[2])
        except (IndexError, ValueError) as exc:
            raise LanServerError("对话 ID 无效") from exc

    def _handle_get_conversation(self, path: str) -> None:
        conversation_id = self._conversation_id(path)
        db, repo = self._repo()
        try:
            conversation = repo.get_conversation(conversation_id)
            if conversation is None:
                self._send_json({"error": "对话不存在"}, 404)
                return
            messages = repo.list_messages(conversation_id)
            self._send_json(
                {
                    "conversation": _conversation_json(conversation),
                    "messages": [_message_json(message) for message in messages],
                    "database": db.name,
                }
            )
        finally:
            db.close()

    def _handle_attachment(self, path: str) -> None:
        try:
            attachment_id = int(path.strip("/").split("/")[2])
        except (IndexError, ValueError):
            self._send_json({"error": "附件 ID 无效"}, 400)
            return
        db, repo = self._repo()
        try:
            attachment = repo.get_attachment(attachment_id)
            if attachment is None:
                self._send_json({"error": "附件不存在"}, 404)
                return
            mime_type = attachment.mime_type or mimetypes.guess_type(attachment.filename)[0]
            mime_type = mime_type or "application/octet-stream"
            data = attachment.data
            self.send_response(200)
            self.send_header("Content-Type", mime_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Content-Disposition", f"inline; filename*=UTF-8''{quote(attachment.filename)}")
            self.send_header("Cache-Control", "private, max-age=3600")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Connection", "close")
            self.close_connection = True
            self.end_headers()
            self._write(data)
        finally:
            db.close()

    def _handle_create_conversation(self) -> None:
        db, repo = self._repo()
        try:
            provider = repo.default_provider()
            conversation_id = repo.create_conversation(
                provider.id if provider else None, "移动端新对话"
            )
            conversation = repo.get_conversation(conversation_id)
            self.share.notify_change(conversation_id)
            self._send_json(
                {
                    "conversation": _conversation_json(conversation)
                    if conversation
                    else {"id": conversation_id, "title": "移动端新对话"}
                },
                201,
            )
        finally:
            db.close()

    def _decode_attachments(self, raw: Any) -> list:
        if raw in (None, ""):
            return []
        if not isinstance(raw, list):
            raise LanServerError("附件格式错误")
        if len(raw) > MAX_ATTACHMENTS:
            raise LanServerError(f"每条消息最多 {MAX_ATTACHMENTS} 个附件")
        attachments = []
        for item in raw:
            if not isinstance(item, dict):
                raise LanServerError("附件格式错误")
            filename = str(item.get("filename") or "attachment")
            mime_type = str(item.get("mime_type") or "")
            encoded = str(item.get("data") or "")
            if not encoded:
                raise LanServerError(f"附件内容为空：{filename}")
            try:
                data = base64.b64decode(encoded, validate=True)
            except (ValueError, binascii.Error) as exc:
                raise LanServerError(f"附件编码错误：{filename}") from exc
            try:
                attachments.append(
                    attachment_from_bytes(data, filename, mime_type=mime_type)
                )
            except AttachmentError as exc:
                raise LanServerError(str(exc)) from exc
        return attachments

    def _handle_send_message(self, path: str, body: dict) -> None:
        conversation_id = self._conversation_id(path.replace("/messages", ""))
        try:
            attachments = self._decode_attachments(body.get("attachments"))
        except LanServerError as exc:
            self._send_json({"error": str(exc)}, 400)
            return
        content = str(body.get("content") or "").strip()
        if not content and not attachments:
            self._send_json({"error": "消息不能为空"}, 400)
            return
        if len(content) > MAX_MESSAGE_CHARS:
            self._send_json({"error": "消息过长"}, 413)
            return
        db, repo = self._repo()
        try:
            conversation = repo.get_conversation(conversation_id)
            if conversation is None:
                self._send_json({"error": "对话不存在"}, 404)
                return
            provider = None
            if conversation.api_id is not None:
                provider = repo.get_provider(conversation.api_id)
            provider = provider or repo.default_provider()
            if provider is None:
                self._send_json({"error": "该对话没有可用 API，请先在电脑端配置。"}, 409)
                return
            repo.add_message(
                conversation_id,
                "user",
                content,
                model=provider.model,
                attachments=attachments,
            )
            messages = repo.api_messages(conversation_id)
            try:
                result = LLMClient(provider).complete(messages)
            except Exception as exc:
                self.share.notify_change(conversation_id)
                self._send_json({"error": str(exc), "user_saved": True}, 502)
                return
            prompt = result.prompt_tokens or context_tokens(messages, provider.system_prompt)
            completion = result.completion_tokens or estimate_tokens(result.content)
            total = prompt + completion
            message_id = repo.add_message(
                conversation_id,
                "assistant",
                result.content,
                model=result.model or provider.model,
                token_count=completion or None,
                usage={
                    "api_id": provider.id,
                    "api_alias": provider.alias,
                    "model": result.model or provider.model,
                    "prompt_tokens": prompt,
                    "completion_tokens": completion,
                    "total_tokens": total,
                },
            )
            saved = [item for item in repo.list_messages(conversation_id) if item.id == message_id]
            conversation = repo.get_conversation(conversation_id)
            self.share.notify_change(conversation_id)
            self._send_json(
                {
                    "reply": _message_json(saved[0]) if saved else {"content": result.content},
                    "conversation": _conversation_json(conversation)
                    if conversation
                    else None,
                    "usage": {
                        "prompt_tokens": prompt,
                        "completion_tokens": completion,
                        "total_tokens": total,
                    },
                }
            )
        finally:
            db.close()


class _ShareHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


class LanShareServer:
    def __init__(
        self,
        db_config_getter: Callable[[], dict[str, Any]],
        *,
        on_change: Optional[Callable[[int], None]] = None,
        host: str = "0.0.0.0",
        port: int = 8765,
        token: str | None = None,
    ) -> None:
        self.db_config_getter = db_config_getter
        self.on_change = on_change
        self.host = host
        self.port = port
        self.token = token or new_access_token()
        self._httpd: Optional[_ShareHTTPServer] = None
        self._thread: Optional[threading.Thread] = None
        self._connections: set[Any] = set()
        self._connections_lock = threading.Lock()

    def add_connection(self, connection: Any) -> None:
        with self._connections_lock:
            self._connections.add(connection)

    def remove_connection(self, connection: Any) -> None:
        with self._connections_lock:
            self._connections.discard(connection)

    @property
    def running(self) -> bool:
        return self._httpd is not None

    @property
    def lan_ip(self) -> str:
        return local_lan_ip()

    @property
    def url(self) -> str:
        return f"http://{self.lan_ip}:{self.port}/?token={quote(self.token)}"

    def start(self) -> str:
        if self._httpd is not None:
            return self.url
        try:
            httpd = _ShareHTTPServer((self.host, self.port), _Handler)
        except OSError as exc:
            raise LanServerError(
                f"无法在端口 {self.port} 启动共享服务：{exc}\n请换一个端口，或检查端口是否被占用。"
            ) from exc
        httpd.share_server = self  # type: ignore[attr-defined]
        self._httpd = httpd
        self._thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        self._thread.start()
        return self.url

    def stop(self) -> None:
        httpd, self._httpd = self._httpd, None
        thread, self._thread = self._thread, None
        if httpd is not None:
            httpd.shutdown()
            httpd.server_close()
        with self._connections_lock:
            connections = list(self._connections)
            self._connections.clear()
        for connection in connections:
            try:
                connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                connection.close()
            except OSError:
                pass
        if thread is not None:
            thread.join(timeout=3)

    def notify_change(self, conversation_id: int) -> None:
        if self.on_change is not None:
            try:
                self.on_change(conversation_id)
            except Exception:
                pass


LOGIN_HTML = """<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>API Chat · 需要访问码</title>
<style>
:root{color-scheme:dark}*{box-sizing:border-box}
body{margin:0;min-height:100dvh;display:grid;place-items:center;background:#0b0e14;
color:#e8edf7;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Microsoft YaHei",sans-serif}
.card{width:min(360px,88vw);background:#121824;border:1px solid #263044;border-radius:16px;padding:26px}
h1{font-size:20px;margin:0 0 6px}p{color:#94a0b5;font-size:13px;line-height:1.6}
input{width:100%;padding:12px;border-radius:10px;border:1px solid #34435e;background:#171f2d;color:#fff;font-size:16px}
button{width:100%;margin-top:12px;padding:12px;border:none;border-radius:10px;background:#6d8bff;color:#fff;font-weight:700;font-size:15px}
</style></head><body><div class="card"><h1>API Chat</h1>
<p>请输入电脑端「局域网共享」中显示的访问码。</p>
<form method="get"><input name="token" autofocus autocomplete="one-time-code" placeholder="访问码">
<button>进入</button></form></div></body></html>"""


MOBILE_HTML = """<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#0b0e14">
<title>API Chat</title>
<style>
:root{--bg:#0b0e14;--surface:#121824;--surface2:#171f2d;--border:#263044;
--text:#e8edf7;--muted:#94a0b5;--faint:#66738a;--accent:#6d8bff;--green:#41d99a;
color-scheme:dark}
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
html,body{margin:0;height:100%;background:var(--bg);color:var(--text);max-width:100%;
overflow-x:hidden;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Microsoft YaHei",sans-serif}
body{overflow:hidden}
.app{height:100dvh;display:flex;flex-direction:column}
.top{height:56px;display:flex;align-items:center;gap:6px;padding:0 10px;
border-bottom:1px solid #1b2331;background:var(--bg);flex:0 0 auto}
.iconbtn{width:38px;height:38px;border:0;border-radius:10px;background:transparent;
color:var(--muted);font-size:21px;display:grid;place-items:center}
.iconbtn:active{background:var(--surface2)}
.top h1{font-size:16px;margin:0;flex:1;min-width:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.pill{font-size:10px;color:var(--muted);border:1px solid var(--border);
border-radius:999px;padding:3px 8px;white-space:nowrap;max-width:42%;overflow:hidden;text-overflow:ellipsis}
.main{flex:1;display:flex;min-height:0;position:relative}
.sidebar{width:290px;flex:0 0 290px;border-right:1px solid #1b2331;display:flex;
flex-direction:column;background:#0d1119;min-height:0;z-index:5}
.side-head{padding:12px;display:flex;gap:8px;align-items:center}
.newbtn{flex:1;border:0;border-radius:10px;background:var(--accent);color:white;
padding:10px;font-size:13px;font-weight:700}
.list{overflow:auto;padding:0 8px 12px;flex:1}
.conv{padding:10px;border:1px solid transparent;border-radius:11px;margin:4px 0;cursor:pointer}
.conv.active{background:#182238;border-color:#2b3b5d}
.conv .t{font-size:13px;font-weight:650;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.conv .m{font-size:10px;color:var(--faint);margin-top:3px;display:flex;justify-content:space-between;gap:8px}
.bar{height:3px;border-radius:2px;background:#232d3f;margin-top:6px;overflow:hidden}
.bar i{display:block;height:100%;background:var(--green);border-radius:2px}
.chat{flex:1;display:flex;flex-direction:column;min-width:0;min-height:0}
.messages{flex:1;overflow-y:auto;overflow-x:hidden;padding:14px 12px 8px;overscroll-behavior:contain}
.msg{max-width:min(760px,94%);min-width:0;margin:0 auto 14px;display:flex;gap:8px;align-items:flex-start}
.msg.user{flex-direction:row-reverse}
.avatar{flex:0 0 26px;width:26px;height:26px;border-radius:50%;display:grid;place-items:center;
font-size:10px;font-weight:700;background:#172c2a;color:var(--green);border:1px solid #244b43}
.msg.user .avatar{background:#2c4b91;color:#dce6ff;border-color:#3a5db7}
.bubble{min-width:0;max-width:calc(100% - 36px);padding:10px 12px;border-radius:14px;
background:var(--surface);border:1px solid #1b2331;font-size:14px;line-height:1.62;
white-space:normal;overflow-wrap:anywhere;word-break:break-word}
.bubble .plain{white-space:pre-wrap}
.bubble p{margin:0 0 8px}
.bubble p:last-child{margin-bottom:0}
.bubble h1,.bubble h2,.bubble h3,.bubble h4{color:#f2f6ff;margin:12px 0 6px}
.bubble h1{font-size:19px}.bubble h2{font-size:17px}.bubble h3{font-size:15px}
.bubble ul,.bubble ol{margin:4px 0 8px;padding-left:20px}
.bubble li{margin:2px 0}
.bubble pre{background:#0a1019;border:1px solid #26324a;padding:9px;border-radius:8px;
margin:8px 0;overflow-x:auto;white-space:pre-wrap;word-break:break-word}
.bubble code{font-family:"Cascadia Mono",Consolas,monospace;background:#0c121d;
color:#bfd0ff;padding:1px 4px;border-radius:4px;font-size:12px}
.bubble pre code{background:transparent;color:#dce6f8;padding:0}
.bubble blockquote{color:#a9b6cc;border-left:3px solid #3e537e;margin:6px 0;padding-left:10px}
.bubble a{color:#94adff;text-decoration:none}
.bubble table{width:100%;border-collapse:collapse;margin:6px 0;font-size:12px}
.bubble th,.bubble td{border:1px solid #2b3850;padding:4px 6px;text-align:left}
.bubble th{background:#151e2c;color:#f0f4fc}
.msg.user .bubble{background:#223c78;border-color:#2e4c90}
.meta{font-size:9px;color:var(--faint);margin-top:5px;text-align:right}
.msg.user .meta{text-align:left}
.bubble img{display:block;width:auto;max-width:100%;max-height:300px;border-radius:9px;margin-top:6px}
.file{display:inline-block;margin-top:6px;padding:5px 8px;border-radius:7px;
background:#171f2d;border:1px solid #263044;color:var(--muted);font-size:10px;text-decoration:none}
.empty{text-align:center;color:var(--faint);padding:60px 20px;font-size:13px;line-height:1.8}
.composer{flex:0 0 auto;padding:8px 10px calc(8px + env(safe-area-inset-bottom));
border-top:1px solid #1b2331;background:var(--bg)}
.draft{max-width:840px;margin:0 auto 7px;display:flex;gap:6px;overflow-x:auto;padding-bottom:2px}
.draft:empty{display:none}
.chip{flex:0 0 auto;max-width:170px;display:flex;align-items:center;gap:5px;padding:4px 6px;
border-radius:7px;background:#171f2d;border:1px solid #263044;color:var(--muted);font-size:10px}
.chip img{width:28px;height:28px;object-fit:cover;border-radius:5px}
.chip span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.chip button{border:0;background:transparent;color:var(--faint);font-size:15px;line-height:1;padding:0 2px}
.composer-inner{max-width:840px;margin:auto;display:flex;gap:6px;align-items:flex-end;
background:var(--surface);border:1px solid var(--border);border-radius:14px;padding:7px}
.attach{width:38px;height:38px;border:0;border-radius:50%;background:transparent;color:var(--muted);
font-size:20px;display:grid;place-items:center;flex:0 0 38px}
.attach:disabled{opacity:.4}
textarea{flex:1;resize:none;border:0;background:transparent;color:var(--text);
font:inherit;font-size:14px;line-height:1.5;max-height:120px;min-height:24px;outline:none;padding:5px 0}
.attach-hint{max-width:840px;margin:5px auto 0;color:var(--faint);font-size:9px;text-align:right}
.send{width:38px;height:38px;border:0;border-radius:50%;background:var(--accent);color:#fff;
font-size:19px;display:grid;place-items:center;flex:0 0 38px}
.send:disabled{background:#273145;color:#66738a}
.error{max-width:840px;margin:0 auto 8px;padding:8px 10px;border-radius:8px;
background:#261720;border:1px solid #5a293b;color:#ffadb7;font-size:11px;display:none;white-space:pre-wrap}
.backdrop{display:none;position:fixed;inset:0;background:#0009;z-index:4}
@media(max-width:760px){
 .sidebar{position:fixed;left:0;top:0;bottom:0;transform:translateX(-105%);transition:.2s}
 .sidebar.open{transform:none}
 .backdrop.show{display:block}
 .top h1{font-size:14px}
 .msg{max-width:100%}
}
</style></head><body>
<div class="app">
 <div class="top">
  <button class="iconbtn" id="menuBtn">☰</button>
  <h1 id="chatTitle">API Chat</h1>
  <span class="pill" id="ctxPill">—</span>
 </div>
 <div class="main">
  <aside class="sidebar" id="sidebar">
   <div class="side-head"><button class="newbtn" id="newBtn">＋ 新建对话</button>
   <button class="iconbtn" id="refreshBtn">↻</button></div>
   <div class="list" id="convList"></div>
  </aside>
  <div class="backdrop" id="backdrop"></div>
  <section class="chat">
   <div class="messages" id="messages"><div class="empty">选择或新建一个对话开始</div></div>
   <div class="composer">
    <div class="error" id="error"></div>
    <div class="draft" id="draftAttachments"></div>
    <div class="composer-inner">
     <button class="attach" id="attachBtn" title="添加图片或文本附件">📎</button>
     <input type="file" id="fileInput" multiple hidden accept="image/png,image/jpeg,image/webp,image/gif,image/bmp,.txt,.md,.markdown,.csv,.tsv,.json,.jsonl,.xml,.yaml,.yml,.toml,.ini,.cfg,.conf,.log,.html,.htm,.css,.js,.jsx,.ts,.tsx,.py,.java,.kt,.c,.h,.cpp,.cc,.hpp,.cs,.go,.rs,.rb,.php,.swift,.sql,.sh,.bash,.bat,.cmd,.ps1,.vue,.svelte,.lua,.r,.m,.mm">
     <textarea id="input" rows="1" placeholder="输入消息…"></textarea>
     <button class="send" id="sendBtn">➤</button>
    </div>
    <div class="attach-hint" id="attachHint"></div>
   </div>
  </section>
 </div>
</div>
<script>
const TOKEN = new URLSearchParams(location.search).get('token') || '';
const $ = (id) => document.getElementById(id);
let conversations = [];
let currentId = null;
let busy = false;
let draftAttachments = [];
let limits = {image_mb: 10, text_mb: 2, max_attachments: 6};
function esc(v){return String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
async function api(path, options={}){
  const sep = path.includes('?') ? '&' : '?';
  const res = await fetch(path + sep + 'token=' + encodeURIComponent(TOKEN), {
    ...options, headers: {'Content-Type':'application/json', ...(options.headers||{})}
  });
  const data = await res.json().catch(()=>({error:'返回格式错误'}));
  if(!res.ok) throw new Error(data.error || ('HTTP ' + res.status));
  return data;
}
function showError(text){ const e=$('error'); e.textContent=text; e.style.display=text?'block':'none'; }
function setBusy(v){ busy=v; $('sendBtn').disabled=v; $('attachBtn').disabled=v; $('sendBtn').textContent=v?'…':'➤'; }
function isImageFile(file){
  const ext=(file.name.split('.').pop()||'').toLowerCase();
  return ['image/png','image/jpeg','image/webp','image/gif','image/bmp'].includes(file.type)
    || ['png','jpg','jpeg','webp','gif','bmp'].includes(ext);
}
function renderDraft(){
  const box=$('draftAttachments');
  box.innerHTML=draftAttachments.map((a,i)=>
    `<div class="chip">${a.preview?`<img src="${a.preview}" alt="">`:'📎'}<span>${esc(a.filename)}</span><button type="button" data-index="${i}" title="移除">×</button></div>`
  ).join('');
  box.querySelectorAll('button[data-index]').forEach(btn=>btn.onclick=()=>{
    draftAttachments.splice(Number(btn.dataset.index),1); renderDraft();
  });
  $('attachBtn').title=`添加附件（最多 ${limits.max_attachments} 个；图片 ${limits.image_mb} MB，文本 ${limits.text_mb} MB）`;
  $('attachHint').textContent=`图片≤${limits.image_mb}MB · 文本≤${limits.text_mb}MB · 最多${limits.max_attachments}个`;
}
function readDataUrl(file){
  return new Promise((resolve,reject)=>{
    const reader=new FileReader();
    reader.onload=()=>resolve(String(reader.result||''));
    reader.onerror=()=>reject(reader.error||new Error('读取文件失败'));
    reader.readAsDataURL(file);
  });
}
async function addFiles(files){
  const list=Array.from(files||[]);
  if(!list.length) return;
  const errors=[];
  for(const file of list){
    if(draftAttachments.length>=limits.max_attachments){
      errors.push(`每条消息最多 ${limits.max_attachments} 个附件`); break;
    }
    const image=isImageFile(file);
    const maxMb=image?limits.image_mb:limits.text_mb;
    if(file.size>maxMb*1024*1024){
      errors.push(`${file.name} 超过 ${maxMb} MB`); continue;
    }
    try{
      const dataUrl=await readDataUrl(file);
      const encoded=dataUrl.split(',')[1]||'';
      if(!encoded) throw new Error('文件内容为空');
      draftAttachments.push({
        filename:file.name, mime_type:file.type||'', data:encoded,
        preview:image?dataUrl:''
      });
    }catch(e){ errors.push(`${file.name}: ${e.message||'读取失败'}`); }
  }
  renderDraft();
  if(errors.length) showError(errors.join(' / '));
}
function scrollBottom(){ const m=$('messages'); m.scrollTop=m.scrollHeight; }
function renderConversations(){
  const box=$('convList');
  if(!conversations.length){ box.innerHTML='<div class="empty">还没有对话</div>'; return; }
  box.innerHTML=conversations.map(c=>`
    <div class="conv ${c.id===currentId?'active':''}" data-id="${c.id}">
      <div class="t">${esc(c.title)}</div>
      <div class="m"><span>${esc(c.api_alias||'未绑定 API')} · ${c.message_count} 条</span><span>${c.remaining_percent}%</span></div>
      <div class="bar"><i style="width:${Math.max(0,Math.min(100,c.remaining_percent))}%"></i></div>
    </div>`).join('');
  box.querySelectorAll('.conv').forEach(el=>el.onclick=()=>{ openConversation(Number(el.dataset.id)); closeSidebar(); });
}
function renderMessages(data){
  const box=$('messages');
  const c=data.conversation;
  $('chatTitle').textContent=c.title || 'API Chat';
  $('ctxPill').textContent=(c.api_alias||'—')+' · 剩余 '+c.remaining_percent+'%';
  if(!data.messages.length){ box.innerHTML='<div class="empty">这段对话还没有消息，发一条吧</div>'; return; }
  box.innerHTML=data.messages.map(m=>{
    const user=m.role==='user';
    const imgs=(m.attachments||[]).filter(a=>a.kind==='image').map(a=>
      `<img src="/api/attachments/${a.id}?token=${encodeURIComponent(TOKEN)}" alt="${esc(a.filename)}" loading="lazy">`).join('');
    const files=(m.attachments||[]).filter(a=>a.kind!=='image').map(a=>
      `<a class="file" href="/api/attachments/${a.id}?token=${encodeURIComponent(TOKEN)}" target="_blank">📎 ${esc(a.filename)}</a>`).join('');
    const time=(m.created_at||'').replace('T',' ').slice(0,16);
    return `<div class="msg ${user?'user':'assistant'}">
      <div class="avatar">${user?'你':'AI'}</div>
      <div class="bubble">${m.html || '<div class="plain">'+esc(m.content)+'</div>'}${imgs}${files}
        <div class="meta">${esc(time)}</div></div></div>`;
  }).join('');
  scrollBottom();
}
async function loadConversations(selectId){
  const data=await api('/api/conversations');
  conversations=data.conversations||[];
  renderConversations();
  if(selectId) await openConversation(selectId);
  else if(!currentId && conversations.length) await openConversation(conversations[0].id);
}
async function openConversation(id){
  if(currentId!==id){ draftAttachments=[]; renderDraft(); }
  currentId=id; showError('');
  const data=await api('/api/conversations/'+id);
  renderMessages(data); renderConversations();
}
async function send(){
  if(busy) return;
  const text=$('input').value.trim();
  if((!text && !draftAttachments.length) || !currentId) return;
  setBusy(true); showError('');
  try{
    await api('/api/conversations/'+currentId+'/messages', {
      method:'POST',
      body: JSON.stringify({
        content:text,
        attachments:draftAttachments.map(a=>({filename:a.filename,mime_type:a.mime_type,data:a.data}))
      })
    });
    $('input').value=''; $('input').style.height='auto';
    draftAttachments=[]; renderDraft();
    await loadConversations(currentId);
  }catch(e){ showError(e.message); }
  finally{ setBusy(false); $('input').focus(); }
}
async function loadLimits(){
  try{
    const data=await api('/api/limits');
    limits={...limits,...data}; renderDraft();
  }catch(e){ /* keep defaults; file upload will still be validated server-side */ }
}
async function newConversation(){
  try{
    const data=await api('/api/conversations', {method:'POST', body:'{}'});
    await loadConversations(data.conversation.id);
    closeSidebar();
  }catch(e){ showError(e.message); }
}
function openSidebar(){ $('sidebar').classList.add('open'); $('backdrop').classList.add('show'); }
function closeSidebar(){ $('sidebar').classList.remove('open'); $('backdrop').classList.remove('show'); }
$('menuBtn').onclick=openSidebar;
$('backdrop').onclick=closeSidebar;
$('refreshBtn').onclick=()=>loadConversations(currentId);
$('newBtn').onclick=newConversation;
$('sendBtn').onclick=send;
$('attachBtn').onclick=()=>$('fileInput').click();
$('fileInput').onchange=async(e)=>{await addFiles(e.target.files); e.target.value='';};
$('input').addEventListener('input',()=>{const el=$('input'); el.style.height='auto'; el.style.height=Math.min(el.scrollHeight,120)+'px';});
$('input').addEventListener('keydown',(e)=>{if(e.key==='Enter'&&!e.shiftKey&&window.innerWidth>760){e.preventDefault();send();}});
renderDraft();
loadLimits().finally(()=>loadConversations().catch(e=>showError(e.message)));
</script></body></html>"""
