"""Chat message bubbles with markdown, actions and streaming state."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..attachment_utils import format_bytes
from ..models import Attachment, Message
from ..tokens import attachment_tokens_total, estimate_tokens, format_tokens
from .icons import icon
from .theme import MUTED, full_time
from .widgets import IconButton, ImageThumbnail, MarkdownView


class MessageBubble(QWidget):
    edit_requested = Signal(int, str, str)
    copy_requested = Signal(str)
    attachment_clicked = Signal(int)
    regenerate_requested = Signal(int)

    def __init__(
        self,
        *,
        role: str,
        content: str,
        reasoning: str = "",
        message_id: int = 0,
        model: str = "",
        created_at: Optional[datetime] = None,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        token_count: int = 0,
        attachments: Optional[list[Attachment]] = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.role = role
        self.content = content or ""
        self.reasoning = reasoning or ""
        self.message_id = message_id
        self.model = model
        self.created_at = created_at or datetime.now()
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens
        self.token_count = token_count
        self.attachments = attachments or []
        self.streaming = message_id == 0
        self._stream_timer = QTimer(self)
        self._stream_timer.setSingleShot(True)
        self._stream_timer.setInterval(70)
        self._stream_timer.timeout.connect(self._render_stream)
        self._reasoning_expanded = False
        self._build()

    def _build(self) -> None:
        is_user = self.role == "user"
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(10)

        avatar = QLabel("你" if is_user else "AI")
        avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        avatar.setFixedSize(28, 28)
        avatar.setObjectName("avatarUser" if is_user else "avatarAI")

        column = QWidget()
        column.setMaximumWidth(760)
        column.setMinimumWidth(560)
        column.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        column_layout = QVBoxLayout(column)
        column_layout.setContentsMargins(0, 0, 0, 0)
        column_layout.setSpacing(4)

        header = QHBoxLayout()
        header.setContentsMargins(2, 0, 2, 0)
        header.setSpacing(8)
        role_label = QLabel("你" if is_user else "助手")
        role_label.setObjectName("roleLabelUser" if is_user else "roleLabel")
        time_label = QLabel(self.created_at.strftime("%H:%M"))
        time_label.setObjectName("messageMeta")
        time_label.setToolTip(full_time(self.created_at))
        if is_user:
            header.addStretch(1)
            header.addWidget(time_label)
            header.addWidget(role_label)
        else:
            header.addWidget(role_label)
            if self.model:
                model_label = QLabel(self.model)
                model_label.setObjectName("messageMeta")
                model_label.setToolTip(self.model)
                header.addWidget(model_label)
            header.addStretch(1)
            header.addWidget(time_label)
        column_layout.addLayout(header)

        self.bubble = QFrame()
        self.bubble.setObjectName(
            "streamBubble" if self.streaming else ("userBubble" if is_user else "assistantBubble")
        )
        bubble_layout = QVBoxLayout(self.bubble)
        bubble_layout.setContentsMargins(14, 10, 14, 7)
        bubble_layout.setSpacing(5)

        if self.attachments:
            bubble_layout.addWidget(self._build_attachments())

        self.reasoning_box = QFrame()
        self.reasoning_box.setObjectName("reasoningBox")
        reasoning_layout = QVBoxLayout(self.reasoning_box)
        reasoning_layout.setContentsMargins(8, 5, 8, 6)
        reasoning_layout.setSpacing(2)
        self.reasoning_toggle = QPushButton("▸ 思考过程")
        self.reasoning_toggle.setObjectName("reasoningToggle")
        self.reasoning_toggle.setCheckable(True)
        self.reasoning_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self.reasoning_toggle.toggled.connect(self._toggle_reasoning)
        reasoning_layout.addWidget(self.reasoning_toggle)
        self.reasoning_view = MarkdownView()
        self.reasoning_view.set_markdown(self.reasoning, streaming=self.streaming)
        self.reasoning_view.hide()
        reasoning_layout.addWidget(self.reasoning_view)
        self.reasoning_box.setVisible(bool(self.reasoning.strip()))
        bubble_layout.addWidget(self.reasoning_box)

        self.view = MarkdownView()
        self.view.set_markdown(self.content, streaming=self.streaming)
        if not self.content.strip() and not self.streaming:
            self.view.hide()
        bubble_layout.addWidget(self.view)

        footer = QHBoxLayout()
        footer.setContentsMargins(0, 1, 0, 0)
        footer.setSpacing(2)
        self.stream_label = QLabel("正在等待模型…" if self.streaming else "")
        self.stream_label.setObjectName("streamingLabel")
        if not self.streaming:
            self.stream_label.hide()
        footer.addWidget(self.stream_label)

        self.usage_label = QLabel(self._usage_text())
        self.usage_label.setObjectName("messageMeta")
        footer.addWidget(self.usage_label)
        footer.addStretch(1)

        self.copy_button = IconButton("copy", tooltip="复制消息", size=14)
        self.copy_button.clicked.connect(self._copy)
        footer.addWidget(self.copy_button)
        self.edit_button = IconButton(
            "edit",
            tooltip="修改并重新提交" if is_user else "修改消息",
            size=14,
        )
        self.edit_button.clicked.connect(self._edit)
        footer.addWidget(self.edit_button)
        if self.streaming:
            self.copy_button.hide()
            self.edit_button.hide()
        bubble_layout.addLayout(footer)

        column_layout.addWidget(self.bubble)
        if is_user:
            root.addStretch(1)
            root.addWidget(column, 0, Qt.AlignmentFlag.AlignTop)
            root.addWidget(avatar, 0, Qt.AlignmentFlag.AlignTop)
        else:
            root.addWidget(avatar, 0, Qt.AlignmentFlag.AlignTop)
            root.addWidget(column, 1, Qt.AlignmentFlag.AlignTop)

    def _build_attachments(self) -> QWidget:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)
        images = [attachment for attachment in self.attachments if attachment.is_image]
        files = [attachment for attachment in self.attachments if not attachment.is_image]
        if images:
            grid = QGridLayout()
            grid.setContentsMargins(0, 0, 0, 0)
            grid.setHorizontalSpacing(6)
            grid.setVerticalSpacing(6)
            for index, attachment in enumerate(images):
                thumb = ImageThumbnail(attachment)
                thumb.clicked.connect(self.attachment_clicked)
                grid.addWidget(thumb, index // 2, index % 2, Qt.AlignmentFlag.AlignLeft)
            layout.addLayout(grid)
        for attachment in files:
            button = QPushButton(
                f"  {attachment.filename}  ·  {format_bytes(attachment.size_bytes)}"
            )
            button.setObjectName("messageFileButton")
            button.setIcon(icon("file", MUTED, 15))
            button.setIconSize(QSize(15, 15))
            button.setMaximumWidth(440)
            button.setSizePolicy(
                QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed
            )
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setToolTip(f"打开附件：{attachment.filename}")
            button.clicked.connect(
                lambda _checked=False, attachment_id=attachment.id: self.attachment_clicked.emit(
                    attachment_id
                )
            )
            layout.addWidget(button)
        return container

    def _toggle_reasoning(self, checked: bool) -> None:
        self._reasoning_expanded = checked
        self.reasoning_toggle.setText(("▾ " if checked else "▸ ") + "思考过程")
        self.reasoning_view.setVisible(checked and bool(self.reasoning.strip()))

    def _set_reasoning(self, reasoning: str, *, streaming: bool) -> None:
        had_reasoning = bool(self.reasoning.strip())
        self.reasoning = reasoning or ""
        has_reasoning = bool(self.reasoning.strip())
        self.reasoning_box.setVisible(has_reasoning)
        if has_reasoning:
            if not streaming:
                self.reasoning_view.set_markdown(self.reasoning, streaming=False)
            if streaming and not had_reasoning:
                self.reasoning_toggle.setChecked(True)

    def _render_stream(self) -> None:
        if not self.streaming:
            return
        self.view.set_markdown(self.content, streaming=True)
        if self.reasoning.strip():
            self.reasoning_view.set_markdown(self.reasoning, streaming=True)

    def _usage_text(self) -> str:
        if self.role == "user":
            tokens = self.token_count or (
                estimate_tokens(self.content) + attachment_tokens_total(self.attachments)
            )
            return f"约 {format_tokens(tokens)} tokens"
        if self.prompt_tokens or self.completion_tokens:
            return (
                f"输入 {format_tokens(self.prompt_tokens)} · "
                f"输出 {format_tokens(self.completion_tokens)} tokens"
            )
        if self.content:
            return f"约 {format_tokens(estimate_tokens(self.content))} tokens"
        return ""

    def update_stream(
        self, text: str, *, reasoning: Optional[str] = None, status: str = "生成中"
    ) -> None:
        self.content = text
        if reasoning is not None:
            self._set_reasoning(reasoning, streaming=True)
        if not self._stream_timer.isActive():
            self._stream_timer.start()
        approx = estimate_tokens(text)
        self.stream_label.setText(f"{status} · 已接收约 {format_tokens(approx)} tokens")
        self.stream_label.show()

    def finish(self, *, content: str, reasoning: str = "", message_id: int, model: str = "",
               prompt_tokens: int = 0, completion_tokens: int = 0,
               created_at: Optional[datetime] = None) -> None:
        self._stream_timer.stop()
        self.content = content or ""
        self._set_reasoning(reasoning, streaming=False)
        self.message_id = message_id
        self.model = model or self.model
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens
        self.created_at = created_at or self.created_at
        self.streaming = False
        self.bubble.setObjectName("assistantBubble")
        self.view.set_markdown(self.content, streaming=False)
        self.stream_label.hide()
        self.usage_label.setText(self._usage_text())
        self.copy_button.show()
        self.edit_button.show()
        self.style().unpolish(self.bubble)
        self.style().polish(self.bubble)

    def set_stream_status(self, text: str) -> None:
        if self.streaming:
            self.stream_label.setText(text)
            self.stream_label.show()

    def _copy(self) -> None:
        self.copy_requested.emit(self.content)

    def _edit(self) -> None:
        if self.message_id:
            self.edit_requested.emit(self.message_id, self.role, self.content)

    @classmethod
    def from_message(cls, message: Message, parent: QWidget | None = None) -> "MessageBubble":
        return cls(
            role=message.role,
            content=message.content,
            reasoning=message.reasoning_content,
            message_id=message.id,
            model=message.model,
            created_at=message.created_at,
            prompt_tokens=message.prompt_tokens,
            completion_tokens=message.completion_tokens,
            token_count=message.token_count,
            attachments=message.attachments,
            parent=parent,
        )
