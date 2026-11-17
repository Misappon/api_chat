"""Plain-text conversation export."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from .attachment_utils import format_bytes
from .models import Conversation, Message


def safe_filename(title: str, fallback: str = "api_chat_conversation") -> str:
    cleaned = re.sub(r'[\\/:*?"<>|\r\n\t]+', "_", (title or "").strip())
    cleaned = cleaned.strip(" ._")
    return (cleaned[:80] or fallback) + ".txt"


def conversation_to_text(
    conversation: Conversation,
    messages: list[Message],
    *,
    exported_at: datetime | None = None,
) -> str:
    exported_at = exported_at or datetime.now()
    lines: list[str] = [
        "API Chat 对话导出",
        "=" * 60,
        f"标题：{conversation.title}",
        f"API：{conversation.api_alias or '未绑定 API'}",
        f"模型：{conversation.model or '未指定'}",
        f"创建时间：{conversation.created_at.strftime('%Y-%m-%d %H:%M:%S') if conversation.created_at else '未知'}",
        f"导出时间：{exported_at.strftime('%Y-%m-%d %H:%M:%S')}",
        f"消息数量：{len(messages)}",
        "=" * 60,
        "",
    ]
    for message in messages:
        role = "用户" if message.role == "user" else "助手"
        stamp = message.created_at.strftime("%Y-%m-%d %H:%M:%S") if message.created_at else ""
        lines.append(f"[{stamp}] {role}")
        lines.append("-" * 60)
        lines.append(message.content.rstrip() or "（无文本内容）")
        if message.attachments:
            lines.append("")
            lines.append("附件：")
            for attachment in message.attachments:
                kind = "图片" if attachment.is_image else "文件"
                dimensions = (
                    f"，{attachment.width}×{attachment.height}"
                    if attachment.width and attachment.height
                    else ""
                )
                lines.append(
                    f"  - [{kind}] {attachment.filename}"
                    f"（{format_bytes(attachment.size_bytes)}{dimensions}）"
                )
        lines.append("")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def write_conversation_text(
    path: str | Path,
    conversation: Conversation,
    messages: list[Message],
) -> None:
    text = conversation_to_text(conversation, messages)
    Path(path).write_text(text, encoding="utf-8-sig")
