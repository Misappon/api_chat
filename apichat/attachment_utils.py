"""Attachment validation, thumbnails and text decoding."""

from __future__ import annotations

import mimetypes
from pathlib import Path

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt
from PySide6.QtGui import QColor, QImage, QImageReader, QPainter

from .models import Attachment
from .tokens import estimate_tokens

MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_TEXT_BYTES = 2 * 1024 * 1024
MAX_ATTACHMENTS = 6
THUMBNAIL_MAX = 480

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
TEXT_EXTENSIONS = {
    ".txt", ".md", ".markdown", ".csv", ".tsv", ".json", ".jsonl", ".xml",
    ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf", ".log", ".html", ".htm",
    ".css", ".js", ".jsx", ".ts", ".tsx", ".py", ".pyw", ".java", ".kt",
    ".kts", ".c", ".h", ".cpp", ".cc", ".hpp", ".cs", ".go", ".rs", ".rb",
    ".php", ".swift", ".sql", ".sh", ".bash", ".zsh", ".bat", ".cmd", ".ps1",
    ".vue", ".svelte", ".lua", ".r", ".m", ".mm",
}


class AttachmentError(ValueError):
    pass


def decode_text_bytes(data: bytes) -> str:
    for encoding in ("utf-8-sig", "gb18030", "utf-16"):
        try:
            return data.decode(encoding)
        except (UnicodeDecodeError, UnicodeError):
            continue
    return data.decode("utf-8", errors="replace")


def format_bytes(value: int) -> str:
    value = int(value or 0)
    if value >= 1024 * 1024:
        return f"{value / (1024 * 1024):.1f} MB"
    if value >= 1024:
        return f"{value / 1024:.0f} KB"
    return f"{value} B"


def _thumbnail_bytes(image: QImage) -> tuple[bytes, int, int]:
    width, height = image.width(), image.height()
    if width <= 0 or height <= 0:
        return b"", width, height
    scaled = image.scaled(
        THUMBNAIL_MAX,
        THUMBNAIL_MAX,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
    canvas = QImage(scaled.size(), QImage.Format.Format_RGB32)
    canvas.fill(QColor("#111722"))
    painter = QPainter(canvas)
    painter.drawImage(0, 0, scaled)
    painter.end()
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    canvas.save(buffer, "JPEG", 86)
    return bytes(buffer.data()), width, height


def prepare_attachment(attachment: Attachment) -> Attachment:
    """Normalize an in-memory attachment before inserting it into MySQL."""
    if attachment.kind == "image":
        image = QImage.fromData(attachment.data)
        if image.isNull():
            raise AttachmentError(f"无法读取图片：{attachment.filename}")
        if attachment.data and len(attachment.data) > MAX_IMAGE_BYTES:
            raise AttachmentError(f"图片超过 {format_bytes(MAX_IMAGE_BYTES)}：{attachment.filename}")
        attachment.width = attachment.width or image.width()
        attachment.height = attachment.height or image.height()
        attachment.mime_type = attachment.mime_type or "image/png"
        attachment.size_bytes = len(attachment.data)
        attachment.token_count = attachment.token_count or 850
        if not attachment.thumbnail:
            thumbnail, width, height = _thumbnail_bytes(image)
            attachment.thumbnail = thumbnail
            attachment.width = width
            attachment.height = height
        return attachment
    if attachment.kind == "text":
        if len(attachment.data) > MAX_TEXT_BYTES:
            raise AttachmentError(f"文本附件超过 {format_bytes(MAX_TEXT_BYTES)}：{attachment.filename}")
        text = decode_text_bytes(attachment.data)
        attachment.size_bytes = len(attachment.data)
        attachment.mime_type = attachment.mime_type or "text/plain"
        attachment.token_count = attachment.token_count or (estimate_tokens(text) + 4)
        return attachment
    raise AttachmentError(f"不支持的附件类型：{attachment.filename}")


def attachment_from_bytes(
    data: bytes,
    filename: str,
    *,
    mime_type: str = "",
) -> Attachment:
    name = Path(filename).name or "attachment"
    extension = Path(name).suffix.lower()
    if not data:
        raise AttachmentError(f"文件为空：{name}")
    if extension in IMAGE_EXTENSIONS or mime_type.startswith("image/"):
        if len(data) > MAX_IMAGE_BYTES:
            raise AttachmentError(f"图片超过 {format_bytes(MAX_IMAGE_BYTES)}：{name}")
        image = QImage.fromData(data)
        if image.isNull():
            raise AttachmentError(f"无法识别图片格式：{name}")
        buffer = QBuffer()
        buffer.setData(QByteArray(data))
        buffer.open(QIODevice.OpenModeFlag.ReadOnly)
        reader = QImageReader(buffer)
        fmt = (reader.format().data().decode("ascii", errors="ignore") or "png").lower()
        buffer.close()
        attachment = Attachment(
            filename=name,
            mime_type=mime_type or f"image/{'jpeg' if fmt == 'jpg' else fmt}",
            kind="image",
            size_bytes=len(data),
            data=data,
            width=image.width(),
            height=image.height(),
        )
        return prepare_attachment(attachment)
    if extension in TEXT_EXTENSIONS or mime_type.startswith("text/"):
        if len(data) > MAX_TEXT_BYTES:
            raise AttachmentError(f"文本附件超过 {format_bytes(MAX_TEXT_BYTES)}：{name}")
        attachment = Attachment(
            filename=name,
            mime_type=mime_type or "text/plain",
            kind="text",
            size_bytes=len(data),
            data=data,
        )
        return prepare_attachment(attachment)
    raise AttachmentError(
        f"暂不支持 {extension or '该'} 类型。支持图片（PNG/JPG/WebP/GIF/BMP）"
        "和文本、代码、Markdown、JSON、CSV 文件。"
    )


def attachment_from_path(path: str | Path) -> Attachment:
    file_path = Path(path)
    if not file_path.is_file():
        raise AttachmentError(f"文件不存在：{file_path}")
    size = file_path.stat().st_size
    if size > MAX_IMAGE_BYTES:
        raise AttachmentError(f"文件超过 {format_bytes(MAX_IMAGE_BYTES)}：{file_path.name}")
    data = file_path.read_bytes()
    mime_type, _ = mimetypes.guess_type(file_path.name)
    return attachment_from_bytes(data, file_path.name, mime_type=mime_type or "")


def image_attachment_from_qimage(image: QImage, filename: str = "粘贴的图片.png") -> Attachment:
    if image.isNull():
        raise AttachmentError("剪贴板中没有可用图片。")
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    return attachment_from_bytes(bytes(buffer.data()), filename, mime_type="image/png")


def attachment_text_content(attachment: Attachment) -> str:
    if attachment.kind != "text":
        return ""
    return decode_text_bytes(attachment.data)
