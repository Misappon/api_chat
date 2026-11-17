"""LAN sharing controls for the mobile web client."""

from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtCore import QUrl, Qt
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ..lan_server import LanServerError, LanShareServer, local_lan_ip, new_access_token
from .icons import icon
from .theme import FAINT, enable_dark_title_bar


class ShareDialog(QDialog):
    def __init__(
        self,
        *,
        get_server: Callable[[], Optional[LanShareServer]],
        start_server: Callable[[int, str], LanShareServer],
        stop_server: Callable[[], None],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._get_server = get_server
        self._start_server = start_server
        self._stop_server = stop_server
        self.setWindowTitle("局域网共享")
        self.setModal(True)
        self.resize(660, 560)
        self._build()
        self._sync()

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        header = QFrame()
        header.setObjectName("dialogHeader")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(24, 18, 24, 14)
        icon_label = QLabel()
        icon_label.setPixmap(icon("wifi", "#8FA9FF", 28).pixmap(28, 28))
        header_layout.addWidget(icon_label, 0, Qt.AlignmentFlag.AlignTop)
        box = QVBoxLayout()
        box.setSpacing(2)
        title = QLabel("共享到局域网")
        title.setObjectName("dialogTitle")
        subtitle = QLabel("用同一 Wi-Fi 下的手机浏览器查看对话并继续聊天。")
        subtitle.setObjectName("dialogSubtitle")
        box.addWidget(title)
        box.addWidget(subtitle)
        header_layout.addLayout(box, 1)
        layout.addWidget(header)

        body = QVBoxLayout()
        body.setContentsMargins(24, 16, 24, 12)
        body.setSpacing(10)

        self.status_card = QFrame()
        self.status_card.setObjectName("card")
        status_layout = QVBoxLayout(self.status_card)
        status_layout.setContentsMargins(14, 12, 14, 12)
        status_layout.setSpacing(6)
        status_top = QHBoxLayout()
        self.status_label = QLabel("未开启")
        self.status_label.setObjectName("cardTitle")
        self.status_dot = QLabel("●")
        self.status_dot.setStyleSheet(f"color: {FAINT}; font-size: 12px;")
        status_top.addWidget(self.status_dot)
        status_top.addWidget(self.status_label)
        status_top.addStretch(1)
        status_layout.addLayout(status_top)
        url_row = QHBoxLayout()
        self.url_edit = QLineEdit()
        self.url_edit.setReadOnly(True)
        self.url_edit.setPlaceholderText("启动后显示手机访问地址")
        url_row.addWidget(self.url_edit, 1)
        self.copy_button = QPushButton("复制")
        self.copy_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.copy_button.clicked.connect(self._copy_url)
        url_row.addWidget(self.copy_button)
        self.open_button = QPushButton("打开")
        self.open_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.open_button.clicked.connect(self._open_url)
        url_row.addWidget(self.open_button)
        status_layout.addLayout(url_row)
        body.addWidget(self.status_card)

        body.addWidget(self._label("监听端口"))
        self.port_spin = QSpinBox()
        self.port_spin.setRange(1024, 65535)
        self.port_spin.setValue(8765)
        body.addWidget(self.port_spin)
        body.addWidget(self._helper("如果端口被占用，换一个 1024–65535 之间的端口。"))

        body.addWidget(self._label("访问码"))
        token_row = QHBoxLayout()
        self.token_edit = QLineEdit()
        self.token_edit.setMaxLength(64)
        self.token_edit.setPlaceholderText("至少 4 个字符")
        token_row.addWidget(self.token_edit, 1)
        self.regen_button = QPushButton("重新生成")
        self.regen_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.regen_button.clicked.connect(
            lambda: self.token_edit.setText(new_access_token())
        )
        token_row.addWidget(self.regen_button)
        body.addLayout(token_row)
        body.addWidget(
            self._helper("手机首次打开需要输入访问码；访问链接中已经包含访问码。")
        )

        self.ip_label = QLabel("")
        self.ip_label.setObjectName("helperText")
        self.ip_label.setWordWrap(True)
        body.addWidget(self.ip_label)
        warning = QLabel(
            "仅在可信局域网使用。服务使用 HTTP 明文传输，不要在公共 Wi-Fi 下开启。"
        )
        warning.setWordWrap(True)
        warning.setStyleSheet("color: #F2B84B;")
        body.addWidget(warning)
        note = QLabel("关闭此设置窗口不会停止共享；需要停止时请再次打开并点击“停止共享”。")
        note.setObjectName("helperText")
        note.setWordWrap(True)
        body.addWidget(note)
        body.addStretch(1)
        layout.addLayout(body, 1)

        footer = QFrame()
        footer.setObjectName("dialogFooter")
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(24, 10, 24, 12)
        footer_layout.setSpacing(8)
        close = QPushButton("关闭")
        close.clicked.connect(self.accept)
        footer_layout.addWidget(close)
        footer_layout.addStretch(1)
        self.toggle_button = QPushButton("启动共享")
        self.toggle_button.setObjectName("primaryButton")
        self.toggle_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.toggle_button.clicked.connect(self._toggle)
        footer_layout.addWidget(self.toggle_button)
        layout.addWidget(footer)
        self.ip_label.setText(
            f"本机局域网地址：{local_lan_ip()}\n手机与电脑需要连接同一个 Wi-Fi，"
            "Windows 防火墙首次可能询问是否允许访问。"
        )

    @staticmethod
    def _label(text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("fieldLabel")
        return label

    @staticmethod
    def _helper(text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("helperText")
        label.setWordWrap(True)
        return label

    def _sync(self) -> None:
        server = self._get_server()
        running = server is not None and server.running
        if running:
            self.status_dot.setStyleSheet("color: #41D99A; font-size: 12px;")
            self.status_label.setText("共享中")
            self.url_edit.setText(server.url)
            self.token_edit.setText(server.token)
            self.port_spin.setValue(server.port)
            self.toggle_button.setText("停止共享")
            self.toggle_button.setObjectName("dangerButton")
            self.port_spin.setEnabled(False)
            self.token_edit.setEnabled(False)
            self.regen_button.setEnabled(False)
            self.copy_button.setEnabled(True)
            self.open_button.setEnabled(True)
        else:
            self.status_dot.setStyleSheet(f"color: {FAINT}; font-size: 12px;")
            self.status_label.setText("未开启")
            self.url_edit.clear()
            self.toggle_button.setText("启动共享")
            self.toggle_button.setObjectName("primaryButton")
            self.port_spin.setEnabled(True)
            self.token_edit.setEnabled(True)
            self.regen_button.setEnabled(True)
            self.copy_button.setEnabled(False)
            self.open_button.setEnabled(False)
            if not self.token_edit.text():
                self.token_edit.setText(new_access_token())
        self.toggle_button.style().unpolish(self.toggle_button)
        self.toggle_button.style().polish(self.toggle_button)

    def _toggle(self) -> None:
        server = self._get_server()
        if server is not None and server.running:
            self._stop_server()
            self._sync()
            return
        port = self.port_spin.value()
        token = self.token_edit.text().strip()
        if len(token) < 4:
            QMessageBox.warning(self, "访问码太短", "访问码至少需要 4 个字符。")
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            self._start_server(port, token)
        except LanServerError as exc:
            QApplication.restoreOverrideCursor()
            QMessageBox.critical(self, "无法启动共享", str(exc))
            return
        QApplication.restoreOverrideCursor()
        self._sync()

    def _copy_url(self) -> None:
        if self.url_edit.text():
            QApplication.clipboard().setText(self.url_edit.text())

    def _open_url(self) -> None:
        if self.url_edit.text():
            QDesktopServices.openUrl(QUrl(self.url_edit.text()))

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        enable_dark_title_bar(self)
