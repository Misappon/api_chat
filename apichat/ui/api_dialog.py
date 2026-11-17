"""API provider management dialogs."""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..models import Provider
from ..repository import Repository, RepositoryError
from ..tokens import format_tokens
from ..workers import ApiTestWorker
from .icons import icon
from .theme import FAINT, MUTED, enable_dark_title_bar

PRESETS = {
    "openai": {
        "label": "OpenAI 兼容",
        "base": "https://api.openai.com/v1",
        "model": "gpt-4o-mini",
        "context": 128_000,
        "hint": "适用于 OpenAI、DeepSeek、Moonshot、OpenRouter、Ollama 等兼容 /chat/completions 的服务。Base URL 填到 /v1 或完整接口地址。",
    },
    "anthropic": {
        "label": "Anthropic",
        "base": "https://api.anthropic.com/v1",
        "model": "claude-sonnet-4-20250514",
        "context": 200_000,
        "hint": "Anthropic Messages API，Base URL 通常填 https://api.anthropic.com/v1。",
    },
    "gemini": {
        "label": "Google Gemini",
        "base": "https://generativelanguage.googleapis.com/v1beta",
        "model": "gemini-2.5-pro",
        "context": 1_048_576,
        "hint": "Gemini generateContent API，Base URL 通常填 https://generativelanguage.googleapis.com/v1beta。",
    },
}


def _label(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("fieldLabel")
    return label


def _helper(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("helperText")
    label.setWordWrap(True)
    return label


class ProviderEditor(QDialog):
    def __init__(
        self,
        provider: Optional[Provider] = None,
        *,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.provider = provider
        self.result_provider: Optional[Provider] = None
        self._test_worker: Optional[ApiTestWorker] = None
        self._previous_type = provider.provider if provider else "openai"
        self.setWindowTitle("编辑 API" if provider else "添加 API")
        self.setModal(True)
        self.setMinimumWidth(660)
        self.resize(680, 790)
        self._build()
        if provider:
            self._load_provider(provider)
        else:
            self._apply_preset("openai", force=True)

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        header = QFrame()
        header.setObjectName("dialogHeader")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(24, 20, 24, 16)
        icon_label = QLabel()
        icon_label.setPixmap(icon("api", "#8FA9FF", 30).pixmap(30, 30))
        header_layout.addWidget(icon_label, 0, Qt.AlignmentFlag.AlignTop)
        title_box = QVBoxLayout()
        title_box.setSpacing(3)
        title = QLabel("编辑 API 连接" if self.provider else "添加 API 连接")
        title.setObjectName("dialogTitle")
        subtitle = QLabel("每个 API 可设置别名，并在对话中随时切换。")
        subtitle.setObjectName("dialogSubtitle")
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        header_layout.addLayout(title_box, 1)
        layout.addWidget(header)

        body = QWidget()
        form = QVBoxLayout(body)
        form.setContentsMargins(24, 18, 24, 12)
        form.setSpacing(8)

        form.addWidget(_label("别名"))
        self.alias_edit = QLineEdit()
        self.alias_edit.setPlaceholderText("例如：DeepSeek 主力、Claude 长文、本地 Ollama")
        self.alias_edit.setMaxLength(80)
        form.addWidget(self.alias_edit)
        form.addWidget(_helper("别名会显示在对话列表和 API 选择器中，不能重复。"))

        form.addSpacing(4)
        form.addWidget(_label("提供商类型"))
        self.type_combo = QComboBox()
        for key, preset in PRESETS.items():
            self.type_combo.addItem(preset["label"], key)
        self.type_combo.currentIndexChanged.connect(self._on_type_changed)
        form.addWidget(self.type_combo)
        self.type_hint = _helper(PRESETS["openai"]["hint"])
        form.addWidget(self.type_hint)

        form.addSpacing(4)
        form.addWidget(_label("Base URL"))
        self.base_edit = QLineEdit()
        self.base_edit.setPlaceholderText("https://api.example.com/v1")
        self.base_edit.setMaxLength(500)
        form.addWidget(self.base_edit)

        form.addSpacing(4)
        form.addWidget(_label("模型名称"))
        self.model_edit = QLineEdit()
        self.model_edit.setPlaceholderText("gpt-4o-mini")
        self.model_edit.setMaxLength(160)
        form.addWidget(self.model_edit)

        form.addSpacing(4)
        form.addWidget(_label("API Key"))
        key_row = QHBoxLayout()
        key_row.setSpacing(6)
        self.key_edit = QLineEdit()
        self.key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.key_edit.setPlaceholderText("sk-…（本地服务可留空）")
        key_row.addWidget(self.key_edit, 1)
        self.eye_button = QToolButton()
        self.eye_button.setObjectName("tinyButton")
        self.eye_button.setIcon(icon("eye", MUTED, 17))
        self.eye_button.setIconSize(QSize(17, 17))
        self.eye_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.eye_button.setToolTip("显示 / 隐藏密钥")
        self.eye_button.setCheckable(True)
        self.eye_button.toggled.connect(self._toggle_key)
        key_row.addWidget(self.eye_button)
        form.addLayout(key_row)
        form.addWidget(_helper("密钥保存在本地 MySQL 数据库中，请勿在共享电脑上使用敏感密钥。"))

        form.addSpacing(6)
        params = QHBoxLayout()
        params.setSpacing(10)
        context_box = QVBoxLayout()
        context_box.setSpacing(4)
        context_box.addWidget(_label("上下文窗口"))
        self.context_spin = QSpinBox()
        self.context_spin.setRange(256, 10_000_000)
        self.context_spin.setSingleStep(1024)
        self.context_spin.setValue(128_000)
        self.context_spin.setSuffix(" tokens")
        context_box.addWidget(self.context_spin)
        params.addLayout(context_box, 1)
        output_box = QVBoxLayout()
        output_box.setSpacing(4)
        output_box.addWidget(_label("单次最大输出"))
        self.output_spin = QSpinBox()
        self.output_spin.setRange(16, 1_000_000)
        self.output_spin.setSingleStep(256)
        self.output_spin.setValue(4096)
        self.output_spin.setSuffix(" tokens")
        output_box.addWidget(self.output_spin)
        params.addLayout(output_box, 1)
        temp_box = QVBoxLayout()
        temp_box.setSpacing(4)
        temp_box.addWidget(_label("温度"))
        self.temp_spin = QDoubleSpinBox()
        self.temp_spin.setRange(0.0, 2.0)
        self.temp_spin.setDecimals(2)
        self.temp_spin.setSingleStep(0.1)
        self.temp_spin.setValue(0.7)
        temp_box.addWidget(self.temp_spin)
        params.addLayout(temp_box, 1)
        form.addLayout(params)
        form.addWidget(_helper("上下文窗口用于计算剩余可用上下文百分比，请按模型实际规格填写。"))

        form.addSpacing(4)
        form.addWidget(_label("系统提示词（可选）"))
        self.system_edit = QPlainTextEdit()
        self.system_edit.setPlaceholderText("为这个 API 的所有对话设置默认角色或输出要求…")
        self.system_edit.setFixedHeight(76)
        form.addWidget(self.system_edit)
        form.addSpacing(4)
        self.default_check = QCheckBox("设为默认 API（新对话默认使用）")
        form.addWidget(self.default_check)
        form.addStretch(1)
        layout.addWidget(body, 1)

        footer = QFrame()
        footer.setObjectName("dialogFooter")
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(24, 12, 24, 14)
        footer_layout.setSpacing(8)
        self.test_button = QPushButton("测试连接")
        self.test_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.test_button.clicked.connect(self._test_connection)
        footer_layout.addWidget(self.test_button)
        self.test_status = QLabel("")
        self.test_status.setObjectName("helperText")
        self.test_status.setWordWrap(True)
        self.test_status.setMinimumWidth(220)
        footer_layout.addWidget(self.test_status, 1)
        cancel = QPushButton("取消")
        cancel.clicked.connect(self.reject)
        footer_layout.addWidget(cancel)
        self.save_button = QPushButton("保存 API")
        self.save_button.setObjectName("primaryButton")
        self.save_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.save_button.clicked.connect(self._save)
        footer_layout.addWidget(self.save_button)
        layout.addWidget(footer)

    def _load_provider(self, provider: Provider) -> None:
        self.alias_edit.setText(provider.alias)
        index = self.type_combo.findData(provider.provider)
        if index >= 0:
            self.type_combo.setCurrentIndex(index)
        self.base_edit.setText(provider.base_url)
        self.model_edit.setText(provider.model)
        self.key_edit.setText(provider.api_key)
        self.context_spin.setValue(provider.context_window)
        self.output_spin.setValue(provider.max_output_tokens)
        self.temp_spin.setValue(provider.temperature)
        self.system_edit.setPlainText(provider.system_prompt)
        self.default_check.setChecked(provider.is_default)
        self._previous_type = provider.provider

    def _apply_preset(self, key: str, *, force: bool = False) -> None:
        preset = PRESETS.get(key, PRESETS["openai"])
        current_base = self.base_edit.text().strip()
        current_model = self.model_edit.text().strip()
        old = PRESETS.get(self._previous_type, PRESETS["openai"])
        if force or not current_base or current_base == old["base"]:
            self.base_edit.setText(preset["base"])
        if force or not current_model or current_model == old["model"]:
            self.model_edit.setText(preset["model"])
        if force or self.context_spin.value() == old["context"]:
            self.context_spin.setValue(preset["context"])
        if hasattr(self, "type_hint"):
            self.type_hint.setText(preset["hint"])

    def _on_type_changed(self, index: int) -> None:
        key = self.type_combo.itemData(index)
        self._apply_preset(str(key))
        self._previous_type = str(key)

    def _toggle_key(self, visible: bool) -> None:
        self.key_edit.setEchoMode(
            QLineEdit.EchoMode.Normal if visible else QLineEdit.EchoMode.Password
        )
        self.eye_button.setIcon(icon("eye-off" if visible else "eye", MUTED, 17))

    def _collect(self) -> Optional[Provider]:
        alias = self.alias_edit.text().strip()
        model = self.model_edit.text().strip()
        base = self.base_edit.text().strip() or PRESETS[
            str(self.type_combo.currentData())
        ]["base"]
        if not alias:
            QMessageBox.warning(self, "缺少别名", "请为这个 API 设置一个别名。")
            self.alias_edit.setFocus()
            return None
        if not model:
            QMessageBox.warning(self, "缺少模型", "请填写模型名称。")
            self.model_edit.setFocus()
            return None
        return Provider(
            id=self.provider.id if self.provider else 0,
            alias=alias,
            provider=str(self.type_combo.currentData()),
            base_url=base,
            api_key=self.key_edit.text(),
            model=model,
            context_window=self.context_spin.value(),
            max_output_tokens=self.output_spin.value(),
            temperature=self.temp_spin.value(),
            system_prompt=self.system_edit.toPlainText().strip(),
            is_default=self.default_check.isChecked(),
        )

    def _test_connection(self) -> None:
        provider = self._collect()
        if provider is None:
            return
        self.test_button.setEnabled(False)
        self.test_button.setText("测试中…")
        self.test_status.setStyleSheet(f"color: {MUTED};")
        self.test_status.setText("正在发送测试请求，可能需要几秒钟…")
        worker = ApiTestWorker(provider, self)
        self._test_worker = worker
        worker.succeeded.connect(self._on_test_ok)
        worker.failed.connect(self._on_test_failed)
        worker.finished.connect(self._on_test_finished)
        worker.start()

    def _on_test_ok(self, text: str) -> None:
        self.test_status.setStyleSheet("color: #41D99A;")
        self.test_status.setText(text.replace("\n", " "))

    def _on_test_failed(self, text: str) -> None:
        self.test_status.setStyleSheet("color: #FF9FAC;")
        self.test_status.setText(text.splitlines()[0][:220] if text else "测试失败")

    def _on_test_finished(self) -> None:
        self.test_button.setEnabled(True)
        self.test_button.setText("测试连接")
        if self._test_worker is not None:
            self._test_worker.deleteLater()
            self._test_worker = None

    def _save(self) -> None:
        if self._test_worker is not None and self._test_worker.isRunning():
            QMessageBox.information(self, "正在测试", "请等待连接测试完成后再保存。")
            return
        provider = self._collect()
        if provider is None:
            return
        self.result_provider = provider
        self.accept()

    def reject(self) -> None:  # noqa: N802
        if self._test_worker is not None and self._test_worker.isRunning():
            QMessageBox.information(self, "正在测试", "请等待连接测试完成后再关闭。")
            return
        super().reject()

    def closeEvent(self, event) -> None:  # noqa: N802
        if self._test_worker is not None and self._test_worker.isRunning():
            event.ignore()
            return
        super().closeEvent(event)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        enable_dark_title_bar(self)


class ApiManagerDialog(QDialog):
    def __init__(self, repository: Repository, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.repository = repository
        self.providers: list[Provider] = []
        self.setWindowTitle("API 管理")
        self.setModal(True)
        self.resize(900, 620)
        self._build()
        self.refresh()

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        header = QFrame()
        header.setObjectName("dialogHeader")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(26, 20, 26, 16)
        icon_label = QLabel()
        icon_label.setPixmap(icon("api", "#8FA9FF", 32).pixmap(32, 32))
        header_layout.addWidget(icon_label, 0, Qt.AlignmentFlag.AlignTop)
        box = QVBoxLayout()
        box.setSpacing(3)
        title = QLabel("API 管理")
        title.setObjectName("dialogTitle")
        subtitle = QLabel("保存多个模型连接并为它们设置别名；对话中可随时切换。")
        subtitle.setObjectName("dialogSubtitle")
        box.addWidget(title)
        box.addWidget(subtitle)
        header_layout.addLayout(box, 1)
        layout.addWidget(header)

        content = QVBoxLayout()
        content.setContentsMargins(24, 18, 24, 12)
        content.setSpacing(10)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["别名", "类型", "模型", "上下文窗口", "默认"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setStretchLastSection(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self.table.doubleClicked.connect(lambda _: self._edit())
        self.table.itemSelectionChanged.connect(self._update_buttons)
        content.addWidget(self.table, 1)

        self.empty_label = QLabel("还没有配置 API。\n点击下方「添加 API」开始连接你的第一个模型。")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.setStyleSheet(f"color: {FAINT}; line-height: 1.7;")
        content.addWidget(self.empty_label, 1)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        self.add_button = QPushButton("  添加 API")
        self.add_button.setObjectName("primaryButton")
        self.add_button.setIcon(icon("plus", "#FFFFFF", 15))
        self.add_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.add_button.clicked.connect(self._add)
        buttons.addWidget(self.add_button)
        self.edit_button = QPushButton("编辑")
        self.edit_button.clicked.connect(self._edit)
        buttons.addWidget(self.edit_button)
        self.default_button = QPushButton("设为默认")
        self.default_button.clicked.connect(self._set_default)
        buttons.addWidget(self.default_button)
        buttons.addStretch(1)
        self.delete_button = QPushButton("删除")
        self.delete_button.setObjectName("dangerButton")
        self.delete_button.clicked.connect(self._delete)
        buttons.addWidget(self.delete_button)
        self.close_button = QPushButton("完成")
        self.close_button.clicked.connect(self.accept)
        buttons.addWidget(self.close_button)
        content.addLayout(buttons)
        layout.addLayout(content, 1)
        self._update_buttons()

    def refresh(self) -> None:
        try:
            self.providers = self.repository.list_providers()
        except RepositoryError as exc:
            QMessageBox.critical(self, "读取失败", str(exc))
            self.providers = []
        selected_id = self._selected_id()
        self.table.blockSignals(True)
        self.table.setRowCount(0)
        for row, provider in enumerate(self.providers):
            self.table.insertRow(row)
            values = [
                provider.alias,
                provider.provider_label,
                provider.model,
                format_tokens(provider.context_window),
                "默认" if provider.is_default else "",
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.ItemDataRole.UserRole, provider.id)
                if column == 4:
                    item.setForeground(QColor("#41D99A" if provider.is_default else MUTED))
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if column == 3:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if column == 0:
                    item.setToolTip(provider.alias)
                if column == 2:
                    item.setToolTip(provider.model)
                self.table.setItem(row, column, item)
            self.table.setRowHeight(row, 44)
            if selected_id == provider.id:
                self.table.selectRow(row)
        self.table.blockSignals(False)
        self.empty_label.setVisible(not self.providers)
        self.table.setVisible(bool(self.providers))
        if selected_id is not None and self.table.rowCount():
            for row in range(self.table.rowCount()):
                if int(self.table.item(row, 0).data(Qt.ItemDataRole.UserRole)) == selected_id:
                    self.table.selectRow(row)
                    break
        elif self.table.rowCount():
            self.table.selectRow(0)
        self._update_buttons()

    def _selected_id(self) -> Optional[int]:
        row = self.table.currentRow()
        if row < 0:
            return None
        item = self.table.item(row, 0)
        return int(item.data(Qt.ItemDataRole.UserRole)) if item else None

    def _selected_provider(self) -> Optional[Provider]:
        selected = self._selected_id()
        return next((p for p in self.providers if p.id == selected), None)

    def _update_buttons(self) -> None:
        has = self._selected_provider() is not None
        self.edit_button.setEnabled(has)
        self.delete_button.setEnabled(has)
        self.default_button.setEnabled(has and not bool(self._selected_provider().is_default))

    def _add(self) -> None:
        editor = ProviderEditor(parent=self)
        if editor.exec() == QDialog.DialogCode.Accepted and editor.result_provider:
            try:
                self.repository.create_provider(editor.result_provider)
            except RepositoryError as exc:
                QMessageBox.critical(self, "保存失败", str(exc))
                return
            self.refresh()

    def _edit(self) -> None:
        provider = self._selected_provider()
        if provider is None:
            return
        editor = ProviderEditor(provider, parent=self)
        if editor.exec() == QDialog.DialogCode.Accepted and editor.result_provider:
            try:
                self.repository.update_provider(editor.result_provider)
            except RepositoryError as exc:
                QMessageBox.critical(self, "保存失败", str(exc))
                return
            self.refresh()

    def _set_default(self) -> None:
        provider = self._selected_provider()
        if provider is None:
            return
        try:
            self.repository.set_default_provider(provider.id)
        except RepositoryError as exc:
            QMessageBox.critical(self, "操作失败", str(exc))
        self.refresh()

    def _delete(self) -> None:
        provider = self._selected_provider()
        if provider is None:
            return
        answer = QMessageBox.question(
            self,
            "删除 API",
            f"确定删除「{provider.alias}」吗？\n\n使用它的对话会自动切换到其他可用 API（如果有）。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            self.repository.delete_provider(provider.id)
        except RepositoryError as exc:
            QMessageBox.critical(self, "删除失败", str(exc))
            return
        self.refresh()

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        enable_dark_title_bar(self)
