"""Shared widgets: icons, markdown rendering, context meters and toasts."""

from __future__ import annotations

import html
import math

import markdown
from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QFontMetrics, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QSizePolicy,
    QTextBrowser,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..attachment_utils import format_bytes
from ..models import Attachment
from ..tokens import format_tokens, remaining_percent
from .icons import icon
from .theme import MUTED, percent_color


class ElidedLabel(QLabel):
    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._full_text = ""
        self.setText(text)

    def setText(self, text: str) -> None:  # noqa: N802 (Qt API)
        self._full_text = text or ""
        self.setToolTip(self._full_text)
        self._apply_elide()

    def fullText(self) -> str:  # noqa: N802
        return self._full_text

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._apply_elide()

    def _apply_elide(self) -> None:
        width = max(20, self.width())
        metrics = QFontMetrics(self.font())
        elided = metrics.elidedText(self._full_text, Qt.TextElideMode.ElideRight, width)
        QLabel.setText(self, elided)


class IconButton(QToolButton):
    def __init__(
        self,
        icon_name: str,
        *,
        tooltip: str = "",
        color: str = MUTED,
        size: int = 18,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setIcon(icon(icon_name, color, size))
        self.setIconSize(QSize(size, size))
        self.setToolTip(tooltip)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setObjectName("tinyButton")
        self.setAutoRaise(True)


class AttachmentChip(QFrame):
    """Draft attachment chip shown above the composer."""

    remove_requested = Signal(int)

    def __init__(self, attachment: Attachment, index: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("attachmentChip")
        self.setFixedWidth(188)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 5, 4, 5)
        layout.setSpacing(6)
        preview = QLabel()
        preview.setFixedSize(38, 38)
        preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        preview.setObjectName("attachmentPreview")
        pixmap = QPixmap()
        if attachment.thumbnail:
            pixmap.loadFromData(attachment.thumbnail)
        elif attachment.is_image and attachment.data:
            pixmap.loadFromData(attachment.data)
        if not pixmap.isNull():
            preview.setPixmap(
                pixmap.scaled(
                    38,
                    38,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
        else:
            preview.setPixmap(icon("file", MUTED, 20).pixmap(20, 20))
        layout.addWidget(preview, 0)
        text = QVBoxLayout()
        text.setContentsMargins(0, 0, 0, 0)
        text.setSpacing(1)
        name = ElidedLabel(attachment.filename)
        name.setObjectName("attachmentName")
        name.setFixedWidth(108)
        meta = QLabel(format_bytes(attachment.size_bytes or len(attachment.data)))
        meta.setObjectName("attachmentMeta")
        text.addWidget(name)
        text.addWidget(meta)
        layout.addLayout(text, 1)
        remove = IconButton("close", tooltip="移除附件", size=12)
        remove.setFixedSize(20, 20)
        remove.clicked.connect(lambda: self.remove_requested.emit(index))
        layout.addWidget(remove, 0, Qt.AlignmentFlag.AlignTop)
        self.setToolTip(
            f"{attachment.filename}\n{attachment.mime_type}\n"
            f"{format_bytes(attachment.size_bytes or len(attachment.data))}"
        )


class ImageThumbnail(QLabel):
    """Clickable image preview inside a message bubble."""

    clicked = Signal(int)

    def __init__(self, attachment: Attachment, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("messageImage")
        self.attachment_id = attachment.id
        pixmap = QPixmap()
        data = attachment.thumbnail or attachment.data
        if data:
            pixmap.loadFromData(data)
        if not pixmap.isNull():
            pixmap = pixmap.scaled(
                250,
                180,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self.setPixmap(pixmap)
            self.setFixedSize(pixmap.size())
        else:
            self.setText("图片")
            self.setFixedSize(120, 80)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(f"{attachment.filename} · 点击查看大图")

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if self.attachment_id:
            self.clicked.emit(self.attachment_id)
        super().mousePressEvent(event)


class ContextPill(QFrame):
    """Compact remaining-context indicator used in the chat header."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("contextPill")
        self.setFixedWidth(246)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(4)
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(6)
        self.label = QLabel("上下文")
        self.label.setObjectName("contextText")
        self.value = QLabel("—")
        self.value.setObjectName("contextPercent")
        self.value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        top.addWidget(self.label)
        top.addStretch(1)
        top.addWidget(self.value)
        layout.addLayout(top)
        self.bar = QProgressBar()
        self.bar.setObjectName("contextPillBar")
        self.bar.setRange(0, 1000)
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(3)
        layout.addWidget(self.bar)

    def update_context(self, used: int, window: int) -> None:
        remaining = remaining_percent(used, window)
        self.value.setText(f"剩余 {remaining:.1f}%")
        color = percent_color(remaining)
        self.value.setStyleSheet(f"color: {color}; font-size: 11px; font-weight: 700;")
        self.bar.setValue(int(remaining * 10))
        state = "ok" if remaining >= 40 else "warn" if remaining >= 15 else "danger"
        self.bar.setProperty("state", state)
        self.bar.style().unpolish(self.bar)
        self.bar.style().polish(self.bar)
        self.setToolTip(
            f"已用约 {format_tokens(used)} / {format_tokens(window)} tokens\n"
            f"剩余 {remaining:.1f}%（按文本估算，API 返回的账单用量见控制台）"
        )

    def set_unavailable(self) -> None:
        self.value.setText("—")
        self.bar.setValue(0)
        self.setToolTip("选择 API 后显示上下文占用")


class ContextLine(QWidget):
    """Remaining context percentage with a thin bar (sidebar cards)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(15)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(7)
        self.bar = QProgressBar()
        self.bar.setObjectName("contextBar")
        self.bar.setRange(0, 1000)
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(4)
        self.label = QLabel("—")
        self.label.setObjectName("conversationPercent")
        self.label.setFixedWidth(84)
        self.label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self.bar, 1)
        layout.addWidget(self.label)

    def update_context(self, used: int, window: int) -> None:
        remaining = remaining_percent(used, window)
        self.label.setText(f"剩余 {remaining:.1f}%")
        color = percent_color(remaining)
        self.label.setStyleSheet(f"color: {color}; font-size: 10px; font-weight: 600;")
        self.bar.setValue(int(remaining * 10))
        state = "ok" if remaining >= 40 else "warn" if remaining >= 15 else "danger"
        self.bar.setProperty("state", state)
        self.bar.style().unpolish(self.bar)
        self.bar.style().polish(self.bar)
        self.setToolTip(
            f"上下文：约 {format_tokens(used)} / {format_tokens(window)} tokens，"
            f"剩余 {remaining:.1f}%"
        )


_MD_CSS = """
body { color: #E8EDF7; font-family: "Microsoft YaHei UI", "Segoe UI"; font-size: 13px; line-height: 1.62; }
p { margin: 0 0 7px 0; }
p:last-child { margin-bottom: 0; }
h1, h2, h3, h4 { color: #F2F6FF; margin: 12px 0 6px 0; }
h1 { font-size: 18px; } h2 { font-size: 16px; } h3 { font-size: 14px; } h4 { font-size: 13px; }
ul, ol { margin: 4px 0 8px 0; padding-left: 22px; }
li { margin: 2px 0; }
code { font-family: "Cascadia Mono", Consolas, monospace; background-color: #0C121D;
       color: #BFD0FF; font-size: 12px; padding: 1px 4px; }
pre { background-color: #0A1019; border: 1px solid #26324A; padding: 10px;
      margin: 8px 0; white-space: pre-wrap; }
pre code { background-color: transparent; color: #DCE6F8; padding: 0; }
blockquote { color: #A9B6CC; border-left: 3px solid #3E537E; margin: 6px 0;
             padding-left: 10px; }
a { color: #94ADFF; text-decoration: none; }
table { border-collapse: collapse; margin: 6px 0; }
th, td { border: 1px solid #2B3850; padding: 4px 8px; }
th { background-color: #151E2C; color: #F0F4FC; }
hr { border: none; border-top: 1px solid #26324A; margin: 10px 0; }
"""


class MarkdownView(QTextBrowser):
    """Read-only rich text view that grows with its content."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("markdownView")
        self.setReadOnly(True)
        self.setOpenExternalLinks(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setLineWrapMode(QTextBrowser.LineWrapMode.WidgetWidth)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.document().setDocumentMargin(0)
        self.document().setDefaultStyleSheet(_MD_CSS)
        self._last_text = ""
        self._streaming = False
        self._last_width = 0
        self.setMinimumHeight(20)

    def set_markdown(self, text: str, *, streaming: bool = False) -> None:
        self._last_text = text or ""
        self._streaming = streaming
        if streaming:
            self.setPlainText(self._last_text)
            self.setStyleSheet(
                'background: transparent; border: none; color: #E8EDF7; '
                'font-family: "Microsoft YaHei UI", "Segoe UI"; font-size: 13px;'
            )
        else:
            try:
                escaped = html.escape(self._last_text, quote=False)
                body = markdown.markdown(
                    escaped,
                    extensions=["fenced_code", "tables", "sane_lists", "nl2br"],
                    output_format="html",
                )
            except Exception:
                body = f"<p>{html.escape(self._last_text).replace(chr(10), '<br>')}</p>"
            self.setHtml(f"<html><head><style>{_MD_CSS}</style></head><body>{body}</body></html>")
            self.setStyleSheet(
                'background: transparent; border: none; color: #E8EDF7; '
                'font-family: "Microsoft YaHei UI", "Segoe UI"; font-size: 13px;'
            )
        self._adjust_height()

    def _adjust_height(self) -> None:
        width = self.viewport().width()
        if width < 80:
            width = max(120, self.width() - 2)
        self.document().setTextWidth(max(80, width))
        height = int(math.ceil(self.document().size().height())) + 3
        self.setFixedHeight(max(22, min(height, 12000)))

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if abs(self.viewport().width() - self._last_width) > 1:
            self._last_width = self.viewport().width()
            self._adjust_height()

    def wheelEvent(self, event) -> None:  # noqa: N802
        # Let the outer message scroll area own the wheel.
        event.ignore()


class Toast(QLabel):
    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("toast")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet(
            "QLabel#toast { background-color: #1C2638; color: #E8EDF7; "
            "border: 1px solid #33435E; border-radius: 9px; padding: 8px 15px; "
            "font-size: 11px; }"
        )
        self.hide()
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide)

    def show_message(self, text: str, msec: int = 2400) -> None:
        self.setText(text)
        self.adjustSize()
        self.raise_()
        self._reposition()
        self.show()
        self._timer.start(msec)

    def _reposition(self) -> None:
        parent = self.parentWidget()
        if not parent:
            return
        x = (parent.width() - self.width()) // 2
        y = parent.height() - self.height() - 24
        self.move(max(10, x), max(10, y))


class SectionTitle(QWidget):
    def __init__(self, text: str, count: int = 0, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        label = QLabel(text)
        label.setObjectName("sectionLabel")
        self.count = QLabel(str(count))
        self.count.setObjectName("countBadge")
        layout.addWidget(label)
        layout.addWidget(self.count)
        layout.addStretch(1)

    def set_count(self, count: int) -> None:
        self.count.setText(str(count))
