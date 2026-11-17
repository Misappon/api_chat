"""Tiny vector icon set rendered from inline SVG (no external assets)."""

from __future__ import annotations

from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

_ICONS: dict[str, tuple[str, bool]] = {
    # name: (inner svg, filled)
    "plus": ("<path d='M12 5v14M5 12h14'/>", False),
    "search": ("<circle cx='11' cy='11' r='7'/><path d='M20.2 20.2l-3.6-3.6'/>", False),
    "chat": (
        "<path d='M21 11.5a8.4 8.4 0 0 1-9 8.4 9 9 0 0 1-3.8-.8L3 21l1.9-5.1A8.4 8.4 0 1 1 21 11.5z'/>",
        False,
    ),
    "dashboard": (
        "<rect x='3' y='3' width='7' height='7' rx='1.5'/><rect x='14' y='3' width='7' height='7' rx='1.5'/>"
        "<rect x='3' y='14' width='7' height='7' rx='1.5'/><rect x='14' y='14' width='7' height='7' rx='1.5'/>",
        False,
    ),
    "api": (
        "<path d='M9 7V3M15 7V3M7 7h10v4a5 5 0 0 1-10 0zM12 16v5'/>",
        False,
    ),
    "database": (
        "<ellipse cx='12' cy='5' rx='8' ry='3'/><path d='M4 5v7c0 1.7 3.6 3 8 3s8-1.3 8-3V5'/>"
        "<path d='M4 12v7c0 1.7 3.6 3 8 3s8-1.3 8-3v-7'/>",
        False,
    ),
    "settings": (
        "<path d='M4 7h9M17 7h3M4 17h3M11 17h9'/><circle cx='15' cy='7' r='2'/><circle cx='9' cy='17' r='2'/>",
        False,
    ),
    "trash": (
        "<path d='M3 6h18M8 6V4h8v2M19 6l-1 14H6L5 6M10 11v5M14 11v5'/>",
        False,
    ),
    "edit": (
        "<path d='M12 20h9M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z'/>",
        False,
    ),
    "copy": (
        "<rect x='9' y='9' width='11' height='11' rx='2'/>"
        "<path d='M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1'/>",
        False,
    ),
    "send": ("<path d='M22 2L11 13M22 2l-7 20-4-9-9-4z'/>", True),
    "stop": ("<rect x='6' y='6' width='12' height='12' rx='2'/>", True),
    "refresh": ("<path d='M21 12a9 9 0 1 1-2.6-6.4M21 3v6h-6'/>", False),
    "chevron-down": ("<path d='m6 9 6 6 6-6'/>", False),
    "chevron-right": ("<path d='m9 6 6 6-6 6'/>", False),
    "close": ("<path d='M18 6L6 18M6 6l12 12'/>", False),
    "check": ("<path d='m5 12 4 4L19 6'/>", False),
    "key": (
        "<circle cx='7.5' cy='15.5' r='3.5'/><path d='M10.3 13.3L20 3.6M16.5 7.1l3 3M14.3 9.3l2 2'/>",
        False,
    ),
    "eye": (
        "<path d='M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z'/><circle cx='12' cy='12' r='3'/>",
        False,
    ),
    "eye-off": (
        "<path d='M3 3l18 18M10.6 5.2A11.8 11.8 0 0 1 12 5c6.5 0 10 7 10 7a17.8 17.8 0 0 1-3 4.1"
        "M6.6 6.6A17.4 17.4 0 0 0 2 12s3.5 7 10 7a11.7 11.7 0 0 0 5.4-1.3'/>",
        False,
    ),
    "more": (
        "<circle cx='5' cy='12' r='1.3' fill='currentColor' stroke='none'/>"
        "<circle cx='12' cy='12' r='1.3' fill='currentColor' stroke='none'/>"
        "<circle cx='19' cy='12' r='1.3' fill='currentColor' stroke='none'/>",
        False,
    ),
    "sparkles": (
        "<path d='M12 3l1.6 4.4L18 9l-4.4 1.6L12 15l-1.6-4.4L6 9l4.4-1.6z'/>"
        "<path d='M19 14l.9 2.1L22 17l-2.1.9L19 20l-.9-2.1L16 17l2.1-.9z'/>"
        "<path d='M5 3l.7 1.8L7.5 5.5 5.7 6.2 5 8 4.3 6.2 2.5 5.5l1.8-.7z'/>",
        False,
    ),
    "alert": (
        "<path d='M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z'/>"
        "<path d='M12 9v4M12 17h.01'/>",
        False,
    ),
    "external": (
        "<path d='M14 3h7v7M10 14L21 3M21 14v5a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5'/>",
        False,
    ),
    "arrow-up-right": ("<path d='M7 17L17 7M7 7h10v10'/>", False),
    "clock": ("<circle cx='12' cy='12' r='9'/><path d='M12 7v5l3 2'/>", False),
    "layers": (
        "<path d='M12 2 2 7l10 5 10-5-10-5zM2 12l10 5 10-5M2 17l10 5 10-5'/>",
        False,
    ),
    "server": (
        "<rect x='3' y='3' width='18' height='7' rx='2'/><rect x='3' y='14' width='18' height='7' rx='2'/>"
        "<path d='M7 6.5h.01M7 17.5h.01'/>",
        False,
    ),
    "menu": ("<path d='M4 6h16M4 12h16M4 18h16'/>", False),
    "scan": ("<path d='M3 8V5a2 2 0 0 1 2-2h3M16 3h3a2 2 0 0 1 2 2v3M21 16v3a2 2 0 0 1-2 2h-3M8 21H5a2 2 0 0 1-2-2v-3'/>", False),
    "bulb": (
        "<path d='M9 18h6M10 22h4M12 2a7 7 0 0 0-4 12.7V17h8v-2.3A7 7 0 0 0 12 2z'/>",
        False,
    ),
}

_CACHE: dict[tuple[str, str, int], QIcon] = {}


def icon(name: str, color: str = "#AAB3C5", size: int = 20) -> QIcon:
    key = (name, color, size)
    cached = _CACHE.get(key)
    if cached is not None:
        return cached
    inner, filled = _ICONS.get(name, _ICONS["chat"])
    fill = color if filled else "none"
    inner = inner.replace("currentColor", color)
    svg = (
        f"<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' "
        f"fill='{fill}' stroke='{color}' stroke-width='1.7' "
        f"stroke-linecap='round' stroke-linejoin='round'>{inner}</svg>"
    )
    scale = 2
    pixmap = QPixmap(size * scale, size * scale)
    pixmap.fill(Qt.GlobalColor.transparent)
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    renderer.render(painter)
    painter.end()
    pixmap.setDevicePixelRatio(scale)
    result = QIcon(pixmap)
    _CACHE[key] = result
    return result
