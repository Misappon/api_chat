"""Dialog for editing a single message and optionally resubmitting it."""

from __future__ import annotations

from typing import Literal, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..tokens import estimate_tokens, format_tokens
from .icons import icon
from .theme import FAINT, enable_dark_title_bar

Mode = Literal["save", "resubmit"]


class EditMessageDialog(QDialog):
    def __init__(
        self,
        role: str,
        content: str,
        *,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.role = role
        self.mode: Optional[Mode] = None
        self.result_text = content
        self.setWindowTitle("修改消息")
        self.setModal(True)
        self.resize(700, 560)
        self._build(content)

    def _build(self, content: str) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        header = QFrame()
        header.setObjectName("dialogHeader")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(24, 18, 24, 14)
        icon_label = QLabel()
        icon_label.setPixmap(icon("edit", "#8FA9FF", 26).pixmap(26, 26))
        header_layout.addWidget(icon_label, 0, Qt.AlignmentFlag.AlignTop)
        box = QVBoxLayout()
        box.setSpacing(3)
        title = QLabel("修改用户消息" if self.role == "user" else "修改助手回复")
        title.setObjectName("dialogTitle")
        if self.role == "user":
            note = "保存并提交后会删除此消息之后的回复，并从这条消息重新请求模型。"
        else:
            note = "助手消息的修改会直接保存到历史记录，并同步更新上下文占用。"
        subtitle = QLabel(note)
        subtitle.setObjectName("dialogSubtitle")
        subtitle.setWordWrap(True)
        box.addWidget(title)
        box.addWidget(subtitle)
        header_layout.addLayout(box, 1)
        layout.addWidget(header)

        body = QVBoxLayout()
        body.setContentsMargins(24, 16, 24, 10)
        body.setSpacing(8)
        label = QLabel("消息内容")
        label.setObjectName("fieldLabel")
        body.addWidget(label)
        self.editor = QPlainTextEdit()
        self.editor.setPlainText(content)
        self.editor.setMinimumHeight(300)
        self.editor.textChanged.connect(self._update_count)
        body.addWidget(self.editor, 1)
        row = QHBoxLayout()
        self.warning = QLabel("")
        self.warning.setStyleSheet("color: #FF9FAC; font-size: 10px;")
        row.addWidget(self.warning, 1)
        self.count = QLabel("")
        self.count.setStyleSheet(f"color: {FAINT}; font-size: 10px;")
        row.addWidget(self.count)
        body.addLayout(row)
        layout.addLayout(body, 1)

        footer = QFrame()
        footer.setObjectName("dialogFooter")
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(24, 12, 24, 14)
        footer_layout.setSpacing(8)
        cancel = QPushButton("取消")
        cancel.clicked.connect(self.reject)
        footer_layout.addWidget(cancel)
        footer_layout.addStretch(1)
        self.save_button = QPushButton("仅保存修改")
        self.save_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.save_button.clicked.connect(lambda: self._finish("save"))
        footer_layout.addWidget(self.save_button)
        self.resubmit_button = QPushButton("保存并重新提交")
        self.resubmit_button.setObjectName("primaryButton")
        self.resubmit_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.resubmit_button.clicked.connect(lambda: self._finish("resubmit"))
        footer_layout.addWidget(self.resubmit_button)
        if self.role != "user":
            # Regenerating from an edited assistant turn would silently discard
            # the edit; keep this dialog to a safe save-only operation.
            self.resubmit_button.hide()
            self.save_button.setObjectName("primaryButton")
        layout.addWidget(footer)
        self._update_count()

    def _update_count(self) -> None:
        text = self.editor.toPlainText()
        self.count.setText(
            f"{len(text)} 字符 · 约 {format_tokens(estimate_tokens(text))} tokens"
        )
        if text.strip():
            self.warning.setText("")
        self.resubmit_button.setEnabled(bool(text.strip()))
        self.save_button.setEnabled(bool(text.strip()))

    def _finish(self, mode: Mode) -> None:
        text = self.editor.toPlainText().strip()
        if not text:
            self.warning.setText("消息内容不能为空。")
            return
        self.result_text = text
        self.mode = mode
        self.accept()

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        enable_dark_title_bar(self)
