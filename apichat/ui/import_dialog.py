"""Import a publicly shared web conversation."""

from __future__ import annotations

import html
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QTabWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from ..importer import ImportedConversation
from ..workers import ImportWorker
from .icons import icon
from .theme import MUTED, enable_dark_title_bar


class ImportConversationDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.imported: Optional[ImportedConversation] = None
        self._worker: Optional[ImportWorker] = None
        self.setWindowTitle("导入网页分享对话")
        self.setModal(True)
        self.resize(780, 760)
        self._build()

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        header = QFrame()
        header.setObjectName("dialogHeader")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(24, 17, 24, 13)
        icon_label = QLabel()
        icon_label.setPixmap(icon("link", "#8FA9FF", 28).pixmap(28, 28))
        header_layout.addWidget(icon_label, 0, Qt.AlignmentFlag.AlignTop)
        box = QVBoxLayout()
        box.setSpacing(2)
        title = QLabel("导入网页分享对话")
        title.setObjectName("dialogTitle")
        subtitle = QLabel(
            "读取公开分享页，重整为本应用对话并继续聊天。支持 ChatGPT / Claude / Gemini / "
            "DeepSeek 等分享页，也支持另存的 HTML 或粘贴文本。"
        )
        subtitle.setObjectName("dialogSubtitle")
        subtitle.setWordWrap(True)
        box.addWidget(title)
        box.addWidget(subtitle)
        header_layout.addLayout(box, 1)
        layout.addWidget(header)

        body = QVBoxLayout()
        body.setContentsMargins(24, 14, 24, 10)
        body.setSpacing(8)
        self.tabs = QTabWidget()
        self.tabs.setFixedHeight(250)
        self.tabs.addTab(self._build_url_tab(), "分享链接")
        self.tabs.addTab(self._build_file_tab(), "HTML 文件")
        self.tabs.addTab(self._build_text_tab(), "粘贴文本")
        body.addWidget(self.tabs)

        bottom = QHBoxLayout()
        self.download_images = QCheckBox("下载网页中的图片（最多 20 张）")
        self.download_images.setChecked(True)
        bottom.addWidget(self.download_images)
        bottom.addStretch(1)
        self.read_button = QPushButton("读取并预览")
        self.read_button.setObjectName("primaryButton")
        self.read_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.read_button.clicked.connect(self._start_read)
        bottom.addWidget(self.read_button)
        body.addLayout(bottom)

        self.status = QLabel("等待读取…")
        self.status.setObjectName("helperText")
        self.status.setWordWrap(True)
        body.addWidget(self.status)

        preview_title = QLabel("预览")
        preview_title.setObjectName("fieldLabel")
        body.addWidget(preview_title)
        self.preview = QTextBrowser()
        self.preview.setMinimumHeight(210)
        self.preview.setOpenExternalLinks(False)
        self.preview.setStyleSheet(
            "QTextBrowser { background: #0D131D; border: 1px solid #263044; "
            "border-radius: 8px; padding: 8px; }"
        )
        body.addWidget(self.preview, 1)
        layout.addLayout(body, 1)

        footer = QFrame()
        footer.setObjectName("dialogFooter")
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(24, 10, 24, 12)
        footer_layout.setSpacing(8)
        cancel = QPushButton("取消")
        cancel.clicked.connect(self.reject)
        footer_layout.addWidget(cancel)
        footer_layout.addStretch(1)
        self.import_button = QPushButton("导入为新对话")
        self.import_button.setObjectName("primaryButton")
        self.import_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.import_button.setEnabled(False)
        self.import_button.clicked.connect(self._accept_import)
        footer_layout.addWidget(self.import_button)
        layout.addWidget(footer)

    def _build_url_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(12, 12, 12, 8)
        layout.setSpacing(7)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        label = QLabel("公开分享链接")
        label.setObjectName("fieldLabel")
        layout.addWidget(label)
        self.url_edit = QLineEdit()
        self.url_edit.setPlaceholderText(
            "https://chatgpt.com/share/… 、 https://claude.ai/share/… 或 https://chat.deepseek.com/share/…"
        )
        self.url_edit.returnPressed.connect(self._start_read)
        layout.addWidget(self.url_edit)
        hint = QLabel(
            "分享页面必须允许匿名访问。若提示需要登录或页面由 JavaScript 动态渲染，"
            "请在浏览器中打开页面并另存为 HTML，再用右侧标签导入。"
        )
        hint.setObjectName("helperText")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        return page

    def _build_file_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(12, 12, 12, 8)
        layout.setSpacing(7)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        label = QLabel("保存的 HTML 文件")
        label.setObjectName("fieldLabel")
        layout.addWidget(label)
        row = QHBoxLayout()
        self.file_edit = QLineEdit()
        self.file_edit.setPlaceholderText("选择浏览器另存的 .html 文件")
        row.addWidget(self.file_edit, 1)
        browse = QPushButton("浏览…")
        browse.clicked.connect(self._browse)
        row.addWidget(browse)
        layout.addLayout(row)
        hint = QLabel(
            "在分享页按 Ctrl+S 保存为“网页，仅 HTML”或“网页，完整”，再选择该文件。"
            "完整保存的 HTML 更有利于识别页面结构。"
        )
        hint.setObjectName("helperText")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        return page

    def _build_text_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(12, 12, 12, 8)
        layout.setSpacing(7)
        label = QLabel("粘贴对话文本")
        label.setObjectName("fieldLabel")
        layout.addWidget(label)
        self.text_edit = QPlainTextEdit()
        self.text_edit.setPlaceholderText(
            "User: 你好\nAssistant: 你好，有什么可以帮你？\nUser: …"
        )
        layout.addWidget(self.text_edit, 1)
        hint = QLabel(
            "支持 User/Assistant、You/ChatGPT、用户/助手 等行首标记。"
            "这是分享页无法直接读取时最可靠的兜底方式。"
        )
        hint.setObjectName("helperText")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        return page

    def _browse(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "选择 HTML 文件", "", "HTML 文件 (*.html *.htm);;所有文件 (*.*)"
        )
        if path:
            self.file_edit.setText(path)

    def _current_source(self) -> tuple[str, str]:
        index = self.tabs.currentIndex()
        if index == 0:
            return "url", self.url_edit.text().strip()
        if index == 1:
            return "html", self.file_edit.text().strip()
        return "text", self.text_edit.toPlainText().strip()

    def _start_read(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            return
        mode, value = self._current_source()
        if not value:
            self.status.setStyleSheet("color: #FF9FAC;")
            self.status.setText("请先填写分享链接、选择 HTML 文件，或粘贴对话文本。")
            return
        self.status.setStyleSheet(f"color: {MUTED};")
        self.status.setText("正在读取并解析，请稍候…")
        self.import_button.setEnabled(False)
        self.read_button.setEnabled(False)
        self.imported = None
        worker = ImportWorker(
            mode,
            value,
            download_images=self.download_images.isChecked(),
            parent=self,
        )
        self._worker = worker
        worker.succeeded.connect(self._on_read_ok)
        worker.failed.connect(self._on_read_failed)
        worker.finished.connect(self._on_worker_finished)
        worker.start()

    def _on_read_ok(self, result: ImportedConversation) -> None:
        self.imported = result
        self.import_button.setEnabled(bool(result.messages))
        self.status.setStyleSheet("color: #41D99A;")
        extra = f" · {result.image_count} 张图片" if result.image_count else ""
        self.status.setText(f"已识别 {len(result.messages)} 条消息{extra}。确认后导入。")
        if result.warnings:
            self.status.setText(self.status.text() + " " + result.warnings[0])
        self._render_preview(result)

    def _on_read_failed(self, error: str) -> None:
        self.status.setStyleSheet("color: #FF9FAC;")
        self.status.setText(error.splitlines()[0] if error else "读取失败")
        self.preview.setHtml(
            "<div style='color:#FFADB7; white-space:pre-wrap;'>"
            + html.escape(error)
            + "</div>"
        )

    def _render_preview(self, result: ImportedConversation) -> None:
        parts = [
            f"<h3 style='margin:0 0 4px 0'>{html.escape(result.title)}</h3>",
            f"<p style='color:#94A0B5'>{len(result.messages)} 条消息 · "
            f"来源：{html.escape(result.source or '粘贴文本')}</p>",
        ]
        for message in result.messages[:24]:
            role = "用户" if message.role == "user" else "助手"
            color = "#AFC6FF" if message.role == "user" else "#41D99A"
            content = html.escape(message.content or "（图片）").replace("\n", "<br>")
            images = ""
            if message.attachments:
                images = (
                    f"<div style='color:#94A0B5'>[图片 {len(message.attachments)} 张]</div>"
                )
            parts.append(
                f"<div style='margin:8px 0 2px 0;color:{color};font-weight:700'>{role}</div>"
                f"<div style='white-space:pre-wrap;color:#E8EDF7'>{content}</div>{images}"
            )
        if len(result.messages) > 24:
            parts.append("<p style='color:#66738A'>…预览仅显示前 24 条</p>")
        self.preview.setHtml("".join(parts))

    def _accept_import(self) -> None:
        if self.imported and self.imported.messages:
            self.accept()

    def _on_worker_finished(self) -> None:
        self.read_button.setEnabled(True)
        if self._worker is not None:
            self._worker.deleteLater()
            self._worker = None

    def reject(self) -> None:  # noqa: N802
        if self._worker is not None and self._worker.isRunning():
            self.status.setText("正在读取，请稍候…")
            return
        super().reject()

    def closeEvent(self, event) -> None:  # noqa: N802
        if self._worker is not None and self._worker.isRunning():
            event.ignore()
            return
        super().closeEvent(event)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        enable_dark_title_bar(self)
