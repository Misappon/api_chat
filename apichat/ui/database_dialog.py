"""MySQL connection and database selection dialog."""

from __future__ import annotations

from typing import Any, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
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

from ..db import Database, DatabaseError
from .icons import icon
from .theme import MUTED, enable_dark_title_bar


class DatabaseDialog(QDialog):
    def __init__(self, config: dict[str, Any], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._initial = dict(config)
        self._result_config: Optional[dict[str, Any]] = None
        self.setWindowTitle("数据库设置")
        self.setModal(True)
        self.resize(640, 600)
        self._build()
        self._load(config)
        self._refresh_databases(show_errors=False)

    @property
    def result_config(self) -> Optional[dict[str, Any]]:
        return self._result_config

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        header = QFrame()
        header.setObjectName("dialogHeader")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(26, 20, 26, 16)
        icon_label = QLabel()
        icon_label.setPixmap(icon("database", "#8FA9FF", 30).pixmap(30, 30))
        header_layout.addWidget(icon_label, 0, Qt.AlignmentFlag.AlignTop)
        box = QVBoxLayout()
        box.setSpacing(3)
        title = QLabel("数据库设置")
        title.setObjectName("dialogTitle")
        subtitle = QLabel("对话、API 配置和用量统计都保存在本地 MySQL 数据库中。")
        subtitle.setObjectName("dialogSubtitle")
        box.addWidget(title)
        box.addWidget(subtitle)
        header_layout.addLayout(box, 1)
        layout.addWidget(header)

        body = QWidget()
        form = QVBoxLayout(body)
        form.setContentsMargins(26, 18, 26, 12)
        form.setSpacing(7)

        form.addWidget(self._label("MySQL 主机"))
        host_row = QHBoxLayout()
        host_row.setSpacing(8)
        self.host_edit = QLineEdit()
        self.host_edit.setPlaceholderText("127.0.0.1")
        host_row.addWidget(self.host_edit, 1)
        port_label = QLabel("端口")
        port_label.setObjectName("fieldLabel")
        host_row.addWidget(port_label)
        self.port_spin = QSpinBox()
        self.port_spin.setRange(1, 65535)
        self.port_spin.setValue(3306)
        self.port_spin.setFixedWidth(92)
        host_row.addWidget(self.port_spin)
        form.addLayout(host_row)

        form.addWidget(self._label("用户名"))
        self.user_edit = QLineEdit()
        self.user_edit.setPlaceholderText("root")
        form.addWidget(self.user_edit)

        form.addWidget(self._label("密码"))
        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.password_edit.setPlaceholderText("没有密码可留空")
        form.addWidget(self.password_edit)
        self.show_password = QCheckBox("显示密码")
        self.show_password.toggled.connect(
            lambda checked: self.password_edit.setEchoMode(
                QLineEdit.EchoMode.Normal if checked else QLineEdit.EchoMode.Password
            )
        )
        form.addWidget(self.show_password)

        form.addWidget(self._label("数据库"))
        db_row = QHBoxLayout()
        db_row.setSpacing(8)
        self.database_combo = QComboBox()
        self.database_combo.setEditable(True)
        self.database_combo.setPlaceholderText("api_chat")
        db_row.addWidget(self.database_combo, 1)
        refresh = QPushButton("刷新列表")
        refresh.setCursor(Qt.CursorShape.PointingHandCursor)
        refresh.clicked.connect(lambda: self._refresh_databases(show_errors=True))
        db_row.addWidget(refresh)
        form.addLayout(db_row)
        hint = QLabel(
            "默认使用 api_chat。若数据库不存在，连接时会自动创建数据库和所需数据表。"
        )
        hint.setObjectName("helperText")
        hint.setWordWrap(True)
        form.addWidget(hint)

        form.addSpacing(8)
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet("color: #263044;")
        form.addWidget(line)
        form.addSpacing(4)
        self.status = QLabel("")
        self.status.setObjectName("helperText")
        self.status.setWordWrap(True)
        form.addWidget(self.status)
        form.addStretch(1)
        layout.addWidget(body, 1)

        footer = QFrame()
        footer.setObjectName("dialogFooter")
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(26, 12, 26, 14)
        footer_layout.setSpacing(8)
        test = QPushButton("测试连接")
        test.setCursor(Qt.CursorShape.PointingHandCursor)
        test.clicked.connect(self._test)
        footer_layout.addWidget(test)
        footer_layout.addStretch(1)
        cancel = QPushButton("取消")
        cancel.clicked.connect(self.reject)
        footer_layout.addWidget(cancel)
        self.save_button = QPushButton("使用此数据库")
        self.save_button.setObjectName("primaryButton")
        self.save_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.save_button.clicked.connect(self._save)
        footer_layout.addWidget(self.save_button)
        layout.addWidget(footer)

    @staticmethod
    def _label(text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("fieldLabel")
        return label

    def _load(self, config: dict[str, Any]) -> None:
        self.host_edit.setText(str(config.get("host", "127.0.0.1")))
        self.port_spin.setValue(int(config.get("port", 3306)))
        self.user_edit.setText(str(config.get("user", "root")))
        self.password_edit.setText(str(config.get("password", "")))
        self.database_combo.setCurrentText(str(config.get("name", "api_chat")))

    def _collect(self) -> Optional[dict[str, Any]]:
        name = self.database_combo.currentText().strip()
        host = self.host_edit.text().strip() or "127.0.0.1"
        user = self.user_edit.text().strip() or "root"
        if not name:
            QMessageBox.warning(self, "缺少数据库名", "请填写数据库名称，默认是 api_chat。")
            return None
        if not all(ch.isalnum() or ch == "_" for ch in name):
            QMessageBox.warning(
                self, "数据库名无效", "数据库名只能包含字母、数字和下划线，不能包含空格或连字符。"
            )
            return None
        return {
            "host": host,
            "port": self.port_spin.value(),
            "user": user,
            "password": self.password_edit.text(),
            "name": name,
        }

    def _refresh_databases(self, *, show_errors: bool) -> None:
        config = self._collect()
        if config is None:
            return
        current = self.database_combo.currentText().strip()
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            names = Database.list_databases(config)
        except DatabaseError as exc:
            QApplication.restoreOverrideCursor()
            if show_errors:
                QMessageBox.critical(self, "无法读取数据库", str(exc))
            else:
                self.status.setText("暂时无法连接 MySQL，请检查服务是否启动。")
            return
        QApplication.restoreOverrideCursor()
        self.database_combo.blockSignals(True)
        self.database_combo.clear()
        self.database_combo.addItems(names)
        if current:
            self.database_combo.setCurrentText(current)
        elif "api_chat" in names:
            self.database_combo.setCurrentText("api_chat")
        else:
            self.database_combo.setCurrentText("api_chat")
        self.database_combo.blockSignals(False)
        self.status.setStyleSheet(f"color: {MUTED};")
        self.status.setText(f"已找到 {len(names)} 个数据库。连接使用时会自动创建缺少的表。")

    def _test(self) -> None:
        config = self._collect()
        if config is None:
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            description = Database.test_connection(config)
        except DatabaseError as exc:
            QApplication.restoreOverrideCursor()
            self.status.setStyleSheet("color: #FF9FAC;")
            self.status.setText(str(exc))
            return
        QApplication.restoreOverrideCursor()
        self.status.setStyleSheet("color: #41D99A;")
        self.status.setText(f"连接成功：{description}。目标数据库：{config['name']}")

    def _save(self) -> None:
        config = self._collect()
        if config is None:
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            description = Database.test_connection(config)
        except DatabaseError as exc:
            QApplication.restoreOverrideCursor()
            QMessageBox.critical(self, "连接失败", str(exc))
            return
        QApplication.restoreOverrideCursor()
        self._result_config = config
        self.status.setStyleSheet("color: #41D99A;")
        self.status.setText(f"连接成功：{description}")
        self.accept()

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        enable_dark_title_bar(self)
