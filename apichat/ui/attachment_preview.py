"""Preview and save an image or text attachment."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..attachment_utils import (
    AttachmentError,
    attachment_text_content,
    decode_text_bytes,
    format_bytes,
)
from ..models import Attachment
from .icons import icon
from .theme import MUTED, enable_dark_title_bar


class AttachmentPreviewDialog(QDialog):
    def __init__(self, attachment: Attachment, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.attachment = attachment
        self.setWindowTitle(f"附件 · {attachment.filename}")
        self.setModal(True)
        self.resize(860, 660)
        self._build()
        self._load()

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        header = QFrame()
        header.setObjectName("dialogHeader")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(22, 16, 22, 12)
        icon_label = QLabel()
        icon_name = "image" if self.attachment.is_image else "file"
        icon_label.setPixmap(icon(icon_name, "#8FA9FF", 26).pixmap(26, 26))
        header_layout.addWidget(icon_label, 0, Qt.AlignmentFlag.AlignTop)
        box = QVBoxLayout()
        box.setSpacing(2)
        title = QLabel(self.attachment.filename)
        title.setObjectName("dialogTitle")
        title.setWordWrap(True)
        meta = QLabel(
            f"{self.attachment.mime_type or '未知类型'} · "
            f"{format_bytes(self.attachment.size_bytes)}"
            + (
                f" · {self.attachment.width}×{self.attachment.height}"
                if self.attachment.width and self.attachment.height
                else ""
            )
        )
        meta.setObjectName("dialogSubtitle")
        box.addWidget(title)
        box.addWidget(meta)
        header_layout.addLayout(box, 1)
        layout.addWidget(header)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.content = QWidget()
        self.content_layout = QVBoxLayout(self.content)
        self.content_layout.setContentsMargins(18, 18, 18, 18)
        self.content_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.scroll.setWidget(self.content)
        layout.addWidget(self.scroll, 1)

        footer = QFrame()
        footer.setObjectName("dialogFooter")
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(22, 10, 22, 12)
        footer_layout.addStretch(1)
        self.save_button = QPushButton("保存附件")
        self.save_button.setIcon(icon("download", MUTED, 15))
        self.save_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.save_button.clicked.connect(self._save)
        footer_layout.addWidget(self.save_button)
        close = QPushButton("关闭")
        close.setObjectName("primaryButton")
        close.clicked.connect(self.accept)
        footer_layout.addWidget(close)
        layout.addWidget(footer)

    def _load(self) -> None:
        if self.attachment.is_image:
            data = self.attachment.data or self.attachment.thumbnail
            pixmap = QPixmap()
            if data:
                pixmap.loadFromData(data)
            if pixmap.isNull():
                self.content_layout.addWidget(QLabel("无法显示这张图片。"))
                return
            screen = self.screen() or QApplication.primaryScreen()
            available = screen.availableGeometry() if screen else self.geometry()
            max_width = min(940, max(320, available.width() - 120))
            max_height = min(620, max(240, available.height() - 220))
            if pixmap.width() > max_width or pixmap.height() > max_height:
                pixmap = pixmap.scaled(
                    max_width,
                    max_height,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            image_label = QLabel()
            image_label.setPixmap(pixmap)
            image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.content_layout.addWidget(image_label)
        else:
            editor = QPlainTextEdit()
            editor.setReadOnly(True)
            if self.attachment.kind == "pdf":
                try:
                    text = attachment_text_content(self.attachment)
                except AttachmentError as exc:
                    text = f"无法提取 PDF 文本：{exc}"
                if not text:
                    text = "该 PDF 没有可提取的文本（可能是扫描件）。\n仍可点击“保存附件”保存原文件。"
                editor.setPlainText(text)
            else:
                editor.setPlainText(decode_text_bytes(self.attachment.data))
            editor.setStyleSheet(
                "QPlainTextEdit { font-family: 'Cascadia Mono', Consolas, monospace; "
                "background: #0D131D; border: 1px solid #263044; "
                "border-radius: 8px; padding: 10px; }"
            )
            editor.setMinimumSize(720, 480)
            self.content_layout.addWidget(editor)

    def _save(self) -> None:
        default_name = self.attachment.filename or "attachment"
        path, _ = QFileDialog.getSaveFileName(
            self,
            "保存附件",
            str(Path.home() / default_name),
            "所有文件 (*.*)",
            options=QFileDialog.Option.DontUseNativeDialog,
        )
        if not path:
            return
        data = self.attachment.data or self.attachment.thumbnail
        try:
            Path(path).write_bytes(data)
        except OSError as exc:
            QMessageBox.critical(self, "保存失败", str(exc))
            return
        self.save_button.setText("已保存")
        self.save_button.setEnabled(False)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        enable_dark_title_bar(self)
