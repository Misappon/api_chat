"""The conversation view: header, message transcript and composer."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QKeyEvent
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ..models import Conversation, Message, Provider
from ..tokens import estimate_tokens, format_tokens
from .icons import icon
from .message_bubble import MessageBubble
from .theme import FAINT, MUTED
from .widgets import ContextPill, IconButton, Toast


class ComposerEdit(QPlainTextEdit):
    submit = Signal()
    focus_changed = Signal(bool)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("composerEdit")
        self.setPlaceholderText("输入消息…  Enter 发送，Shift+Enter 换行")
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setTabChangesFocus(True)
        self.document().setDocumentMargin(2)
        self.setFixedHeight(30)
        self.textChanged.connect(self._adjust_height)

    def _adjust_height(self) -> None:
        height = int(self.document().size().height()) + 8
        self.setFixedHeight(max(30, min(height, 150)))

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                super().keyPressEvent(event)
                return
            self.submit.emit()
            event.accept()
            return
        super().keyPressEvent(event)

    def focusInEvent(self, event) -> None:  # noqa: N802
        super().focusInEvent(event)
        self.focus_changed.emit(True)

    def focusOutEvent(self, event) -> None:  # noqa: N802
        super().focusOutEvent(event)
        self.focus_changed.emit(False)


class ChatPage(QWidget):
    send_requested = Signal(str)
    stop_requested = Signal()
    edit_requested = Signal(int, str, str)
    provider_changed = Signal(int)
    title_changed = Signal(str)
    new_chat_requested = Signal()
    api_manager_requested = Signal()
    delete_requested = Signal()
    clear_requested = Signal()
    regenerate_title_requested = Signal()
    retry_requested = Signal()
    toast_requested = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.current: Optional[Conversation] = None
        self.messages: list[Message] = []
        self._providers: list[Provider] = []
        self._loading = False
        self._generating = False
        self._stream_bubble: Optional[MessageBubble] = None
        self._auto_scroll = True
        self._build()

    # ------------------------------------------------------------------
    # construction
    # ------------------------------------------------------------------
    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.header = QFrame()
        self.header.setObjectName("chatHeader")
        header_layout = QHBoxLayout(self.header)
        header_layout.setContentsMargins(26, 11, 22, 11)
        header_layout.setSpacing(14)

        left = QVBoxLayout()
        left.setSpacing(6)
        title_row = QHBoxLayout()
        title_row.setSpacing(8)
        self.title_edit = QLineEdit()
        self.title_edit.setObjectName("chatTitle")
        self.title_edit.setPlaceholderText("对话标题")
        self.title_edit.setMinimumWidth(220)
        self.title_edit.setMaximumWidth(640)
        self.title_edit.setMaxLength(200)
        self.title_edit.setToolTip("点击可修改标题")
        self.title_edit.editingFinished.connect(self._on_title_edited)
        title_row.addWidget(self.title_edit, 0)
        self.auto_badge = QLabel("自动标题")
        self.auto_badge.setObjectName("autoTitleBadge")
        self.auto_badge.setToolTip("标题由模型根据对话自动生成")
        title_row.addWidget(self.auto_badge, 0)
        title_row.addStretch(1)
        left.addLayout(title_row)

        controls = QHBoxLayout()
        controls.setSpacing(8)
        self.api_combo = QComboBox()
        self.api_combo.setObjectName("apiCombo")
        self.api_combo.setMinimumWidth(150)
        self.api_combo.setMaximumWidth(250)
        self.api_combo.setToolTip("切换当前对话使用的 API")
        self.api_combo.currentIndexChanged.connect(self._on_provider_changed)
        controls.addWidget(self.api_combo)
        self.context_pill = ContextPill()
        controls.addWidget(self.context_pill)
        self.manage_api_button = QPushButton("管理 API")
        self.manage_api_button.setObjectName("ghostButton")
        self.manage_api_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.manage_api_button.setStyleSheet(f"color: {MUTED}; font-size: 10px;")
        self.manage_api_button.clicked.connect(self.api_manager_requested)
        controls.addWidget(self.manage_api_button)
        controls.addStretch(1)
        left.addLayout(controls)
        header_layout.addLayout(left, 1)

        self.more_button = IconButton("more", tooltip="更多操作", color=MUTED, size=20)
        self.more_button.setFixedSize(32, 32)
        self.more_button.clicked.connect(self._show_more_menu)
        header_layout.addWidget(self.more_button, 0, Qt.AlignmentFlag.AlignTop)
        layout.addWidget(self.header)

        self.stack = QStackedWidget()
        layout.addWidget(self.stack, 1)

        self.empty_page = QWidget()
        empty_layout = QVBoxLayout(self.empty_page)
        empty_layout.setContentsMargins(40, 40, 40, 40)
        empty_layout.addStretch(1)
        glyph = QLabel("A")
        glyph.setObjectName("emptyGlyph")
        glyph.setFixedSize(52, 52)
        glyph.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(glyph, 0, Qt.AlignmentFlag.AlignHCenter)
        empty_layout.addSpacing(16)
        self.empty_title = QLabel("开始一段新对话")
        self.empty_title.setObjectName("emptyTitle")
        self.empty_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(self.empty_title)
        self.empty_body = QLabel("把多个模型接进同一个工作台，对话与用量都保存在本地。")
        self.empty_body.setObjectName("emptyBody")
        self.empty_body.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_body.setWordWrap(True)
        empty_layout.addWidget(self.empty_body)
        empty_layout.addSpacing(20)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.empty_new_button = QPushButton("新建对话")
        self.empty_new_button.setObjectName("primaryButton")
        self.empty_new_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.empty_new_button.clicked.connect(self.new_chat_requested)
        buttons.addWidget(self.empty_new_button)
        self.empty_api_button = QPushButton("配置 API")
        self.empty_api_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.empty_api_button.clicked.connect(self.api_manager_requested)
        buttons.addWidget(self.empty_api_button)
        buttons.addStretch(1)
        empty_layout.addLayout(buttons)
        empty_layout.addStretch(2)
        self.stack.addWidget(self.empty_page)

        self.scroll = QScrollArea()
        self.scroll.setObjectName("messageScroll")
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.canvas = QWidget()
        self.canvas.setObjectName("messageCanvas")
        canvas_outer = QHBoxLayout(self.canvas)
        canvas_outer.setContentsMargins(24, 20, 24, 12)
        canvas_outer.setSpacing(0)
        canvas_outer.addStretch(1)
        self.messages_container = QWidget()
        self.messages_container.setMaximumWidth(900)
        self.messages_container.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        self.messages_layout = QVBoxLayout(self.messages_container)
        self.messages_layout.setContentsMargins(0, 0, 0, 0)
        self.messages_layout.setSpacing(17)
        self.messages_layout.addStretch(1)
        canvas_outer.addWidget(self.messages_container, 20)
        canvas_outer.addStretch(1)
        self.scroll.setWidget(self.canvas)
        self.scroll.verticalScrollBar().rangeChanged.connect(self._on_range_changed)
        self.scroll.verticalScrollBar().valueChanged.connect(self._on_scroll_value)
        self.stack.addWidget(self.scroll)
        self.scroll.setVisible(False)

        self.bottom = QWidget()
        bottom_layout = QVBoxLayout(self.bottom)
        bottom_layout.setContentsMargins(24, 4, 24, 16)
        bottom_layout.setSpacing(8)
        bottom_layout.addStretch(1)

        self.error_banner = QFrame()
        self.error_banner.setObjectName("errorBanner")
        error_layout = QHBoxLayout(self.error_banner)
        error_layout.setContentsMargins(12, 8, 10, 8)
        error_layout.setSpacing(8)
        alert = QLabel()
        alert.setPixmap(icon("alert", "#FF9FAC", 17).pixmap(17, 17))
        error_layout.addWidget(alert, 0, Qt.AlignmentFlag.AlignTop)
        self.error_text = QLabel()
        self.error_text.setObjectName("errorText")
        self.error_text.setWordWrap(True)
        self.error_text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        error_layout.addWidget(self.error_text, 1)
        self.retry_button = QPushButton("重试")
        self.retry_button.setObjectName("retryButton")
        self.retry_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.retry_button.clicked.connect(self.retry_requested)
        error_layout.addWidget(self.retry_button, 0, Qt.AlignmentFlag.AlignTop)
        self.error_api_button = QPushButton("API 管理")
        self.error_api_button.setObjectName("retryButton")
        self.error_api_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.error_api_button.clicked.connect(self.api_manager_requested)
        error_layout.addWidget(self.error_api_button, 0, Qt.AlignmentFlag.AlignTop)
        self.error_close = IconButton("close", tooltip="关闭", size=13)
        self.error_close.clicked.connect(self.error_banner.hide)
        error_layout.addWidget(self.error_close, 0, Qt.AlignmentFlag.AlignTop)
        self.error_banner.hide()
        bottom_layout.addWidget(self.error_banner)

        composer_center = QHBoxLayout()
        composer_center.addStretch(1)
        self.composer = QFrame()
        self.composer.setObjectName("composer")
        self.composer.setMaximumWidth(920)
        self.composer.setMinimumWidth(420)
        composer_layout = QVBoxLayout(self.composer)
        composer_layout.setContentsMargins(12, 8, 9, 7)
        composer_layout.setSpacing(2)
        self.edit = ComposerEdit()
        self.edit.submit.connect(self._on_send_clicked)
        self.edit.textChanged.connect(self._update_token_hint)
        self.edit.focus_changed.connect(self._on_composer_focus)
        composer_layout.addWidget(self.edit)
        composer_footer = QHBoxLayout()
        composer_footer.setContentsMargins(2, 0, 1, 0)
        composer_footer.setSpacing(6)
        self.hint = QLabel("Enter 发送 · Shift+Enter 换行")
        self.hint.setObjectName("composerHint")
        composer_footer.addWidget(self.hint)
        composer_footer.addStretch(1)
        self.token_hint = QLabel("约 0 tokens")
        self.token_hint.setObjectName("composerTokens")
        composer_footer.addWidget(self.token_hint)
        self.send_button = QPushButton()
        self.send_button.setObjectName("sendButton")
        self.send_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.send_button.setIcon(icon("send", "#FFFFFF", 17))
        self.send_button.setIconSize(QSize(17, 17))
        self.send_button.setToolTip("发送")
        self.send_button.clicked.connect(self._on_send_clicked)
        composer_footer.addWidget(self.send_button)
        composer_layout.addLayout(composer_footer)
        composer_center.addWidget(self.composer, 20)
        composer_center.addStretch(1)
        bottom_layout.addLayout(composer_center)

        self.disclaimer = QLabel("模型生成的内容可能不准确，请自行核验。")
        self.disclaimer.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.disclaimer.setStyleSheet(f"color: {FAINT}; font-size: 9px;")
        bottom_layout.addWidget(self.disclaimer)
        layout.addWidget(self.bottom)
        self.bottom.hide()

        self.toast = Toast(self)
        self._show_empty(has_providers=False, no_conversation=True)
        self._update_token_hint()

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------
    def set_providers(self, providers: list[Provider], current_api_id: Optional[int]) -> None:
        self._providers = list(providers)
        self._loading = True
        try:
            self.api_combo.clear()
            if not providers:
                self.api_combo.addItem("未配置 API", None)
                self.api_combo.setEnabled(False)
                self.manage_api_button.show()
                self._set_context_unavailable()
                return
            for provider in providers:
                self.api_combo.addItem(
                    icon("api", MUTED, 14), provider.alias, provider.id
                )
                index = self.api_combo.count() - 1
                self.api_combo.setItemData(
                    index,
                    f"{provider.model}\n{provider.provider_label} · "
                    f"{format_tokens(provider.context_window)} tokens",
                    Qt.ItemDataRole.ToolTipRole,
                )
            self.api_combo.setEnabled(True)
            self.manage_api_button.setVisible(False)
            if current_api_id is not None:
                found = self.api_combo.findData(current_api_id)
                if found >= 0:
                    self.api_combo.setCurrentIndex(found)
                else:
                    self.api_combo.setCurrentIndex(0)
            else:
                self.api_combo.setCurrentIndex(0)
        finally:
            self._loading = False

    def load_conversation(
        self,
        conversation: Conversation,
        messages: list[Message],
        providers: list[Provider],
    ) -> None:
        self.current = conversation
        self.messages = list(messages)
        self._loading = True
        self.set_providers(providers, conversation.api_id)
        self.title_edit.setText(conversation.title)
        self.title_edit.setEnabled(True)
        self.title_edit.setCursorPosition(0)
        self.auto_badge.setVisible(conversation.title_auto)
        self.header.setEnabled(True)
        self.more_button.setEnabled(True)
        self._loading = False
        self._clear_messages()
        if not messages:
            self._add_empty_hint()
        for message in messages:
            self._add_bubble(MessageBubble.from_message(message))
        self.header.setVisible(True)
        self.stack.setCurrentWidget(self.scroll)
        self.scroll.setVisible(True)
        self.empty_page.setVisible(False)
        self.bottom.show()
        self.edit.setEnabled(True)
        self.error_banner.hide()
        self.set_generating(False)
        self._recalculate_context()
        QTimer.singleShot(30, lambda: self._scroll_to_bottom(force=True))

    def show_welcome(self, has_providers: bool) -> None:
        self.current = None
        self.messages = []
        self._clear_messages()
        self._show_empty(has_providers=has_providers, no_conversation=True)

    def _show_empty(self, *, has_providers: bool, no_conversation: bool) -> None:
        if no_conversation:
            self.empty_title.setText("开始一段新对话")
            if has_providers:
                self.empty_body.setText("选择左侧的一个对话，或新建对话开始。\n每个对话都可以独立选择 API 与查看剩余上下文。")
            else:
                self.empty_body.setText("还没有可用的 API。先配置一个 OpenAI 兼容、Anthropic 或 Gemini 接口，再开始对话。")
        self.stack.setCurrentWidget(self.empty_page)
        self.empty_page.setVisible(True)
        self.scroll.setVisible(False)
        self.bottom.hide()
        self.header.setVisible(False)
        self.header.setEnabled(bool(self.current))
        self.title_edit.setText("")
        self.title_edit.setPlaceholderText("未选择对话")
        self.auto_badge.hide()
        self.empty_api_button.setVisible(not has_providers)
        self.empty_new_button.setEnabled(has_providers)

    def set_generating(self, generating: bool) -> None:
        self._generating = generating
        self.send_button.setObjectName("stopButton" if generating else "sendButton")
        self.send_button.setIcon(
            icon("stop", "#FF9BB0", 17) if generating else icon("send", "#FFFFFF", 17)
        )
        self.send_button.setToolTip("停止生成" if generating else "发送")
        self.send_button.style().unpolish(self.send_button)
        self.send_button.style().polish(self.send_button)
        self.api_combo.setEnabled(not generating and bool(self._providers))
        self.more_button.setEnabled(not generating)
        self.title_edit.setEnabled(not generating and self.current is not None)
        if generating:
            self.error_banner.hide()

    def begin_stream(self, provider: Provider) -> MessageBubble:
        if self._stream_bubble is not None:
            self._remove_stream_bubble()
        self._add_empty_hint(remove=True)
        bubble = MessageBubble(
            role="assistant",
            content="",
            message_id=0,
            model=provider.model,
            created_at=datetime.now(),
        )
        bubble.set_stream_status("正在连接模型…")
        self._stream_bubble = bubble
        self._insert_bubble(bubble)
        self.set_generating(True)
        self._scroll_to_bottom(force=True)
        return bubble

    def update_stream(self, text: str) -> None:
        if self._stream_bubble is not None:
            self._stream_bubble.update_stream(text)
            self._scroll_if_pinned()

    def set_stream_status(self, text: str) -> None:
        if self._stream_bubble is not None:
            self._stream_bubble.set_stream_status(text)

    def finish_stream(
        self,
        message: Message,
        *,
        content: str,
        prompt_tokens: int,
        completion_tokens: int,
        model: str = "",
    ) -> None:
        if self._stream_bubble is not None:
            self._stream_bubble.finish(
                content=content,
                message_id=message.id,
                model=model or message.model,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                created_at=message.created_at,
            )
            self._stream_bubble = None
        self.messages.append(message)
        self.set_generating(False)
        self._recalculate_context()
        self._scroll_if_pinned()

    def remove_stream(self) -> None:
        self._remove_stream_bubble()
        self.set_generating(False)

    def append_message(self, message: Message) -> None:
        self._add_empty_hint(remove=True)
        self._add_bubble(MessageBubble.from_message(message))
        self.messages.append(message)
        self._recalculate_context()
        self._scroll_to_bottom(force=True)

    def set_title(self, title: str, auto: bool) -> None:
        if not self.current:
            return
        self._loading = True
        self.title_edit.setText(title)
        self.title_edit.setCursorPosition(0)
        self.auto_badge.setVisible(auto)
        self._loading = False

    def clear_composer(self) -> None:
        self.edit.clear()
        self.edit.setFocus()

    def show_error(self, text: str, *, can_retry: bool = True) -> None:
        self.error_text.setText(text)
        self.retry_button.setVisible(can_retry)
        self.error_banner.show()
        self.error_banner.raise_()

    def hide_error(self) -> None:
        self.error_banner.hide()

    def show_toast(self, text: str) -> None:
        self.toast.show_message(text)

    def focus_composer(self) -> None:
        if self.current:
            self.edit.setFocus()

    def set_db_name(self, name: str) -> None:
        self.disclaimer.setToolTip(f"数据库：{name}")

    # ------------------------------------------------------------------
    # message rendering
    # ------------------------------------------------------------------
    def _clear_messages(self) -> None:
        self._stream_bubble = None
        while self.messages_layout.count():
            item = self.messages_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()
        self.messages_layout.addStretch(1)

    def _add_empty_hint(self, remove: bool = False) -> None:
        # Kept as a hook; the scroll view intentionally starts blank.
        return

    def _add_bubble(self, bubble: MessageBubble) -> None:
        bubble.edit_requested.connect(self.edit_requested)
        bubble.copy_requested.connect(self._copy)
        self._insert_bubble(bubble)

    def _insert_bubble(self, bubble: MessageBubble) -> None:
        self.messages_layout.insertWidget(self.messages_layout.count() - 1, bubble)

    def _remove_stream_bubble(self) -> None:
        if self._stream_bubble is None:
            return
        self.messages_layout.removeWidget(self._stream_bubble)
        self._stream_bubble.hide()
        self._stream_bubble.setParent(None)
        self._stream_bubble.deleteLater()
        self._stream_bubble = None

    def _copy(self, text: str) -> None:
        QApplication.clipboard().setText(text)
        self.show_toast("已复制到剪贴板")

    def _recalculate_context(self) -> None:
        if not self.current:
            return
        if not self._providers:
            self._set_context_unavailable()
            return
        used = sum(message.token_count for message in self.messages)
        used += estimate_tokens(self.current.system_prompt)
        self.context_pill.update_context(used, self.current.context_window)

    def _set_context_unavailable(self) -> None:
        self.context_pill.set_unavailable()

    # ------------------------------------------------------------------
    # scrolling
    # ------------------------------------------------------------------
    def _on_range_changed(self, minimum: int, maximum: int) -> None:
        if self._auto_scroll:
            self.scroll.verticalScrollBar().setValue(maximum)

    def _on_scroll_value(self, value: int) -> None:
        bar = self.scroll.verticalScrollBar()
        self._auto_scroll = value >= bar.maximum() - 90

    def _scroll_if_pinned(self) -> None:
        if self._auto_scroll:
            self._scroll_to_bottom()

    def _scroll_to_bottom(self, *, force: bool = False) -> None:
        bar = self.scroll.verticalScrollBar()
        if force:
            self._auto_scroll = True
        bar.setValue(bar.maximum())

    # ------------------------------------------------------------------
    # events / signals
    # ------------------------------------------------------------------
    def _on_send_clicked(self) -> None:
        if self._generating:
            self.stop_requested.emit()
            return
        text = self.edit.toPlainText().strip()
        if not text:
            return
        if not self.current:
            self.new_chat_requested.emit()
            return
        self.send_requested.emit(text)

    def _on_provider_changed(self, index: int) -> None:
        if self._loading or index < 0:
            return
        provider_id = self.api_combo.itemData(index)
        if provider_id is None:
            return
        provider = next((p for p in self._providers if p.id == int(provider_id)), None)
        if provider and self.current:
            self.current.api_id = provider.id
            self.current.api_alias = provider.alias
            self.current.model = provider.model
            self.current.context_window = provider.context_window
            self.current.system_prompt = provider.system_prompt
            self._recalculate_context()
            self.provider_changed.emit(provider.id)

    def _on_title_edited(self) -> None:
        if self._loading or not self.current:
            return
        title = self.title_edit.text().strip()
        if not title:
            self.title_edit.setText(self.current.title)
            return
        if title == self.current.title:
            return
        self.current.title = title
        self.auto_badge.hide()
        self.title_changed.emit(title)

    def _on_composer_focus(self, focused: bool) -> None:
        self.composer.setProperty("focused", "true" if focused else "false")
        self.composer.style().unpolish(self.composer)
        self.composer.style().polish(self.composer)

    def _update_token_hint(self) -> None:
        text = self.edit.toPlainText()
        value = estimate_tokens(text) if text.strip() else 0
        self.token_hint.setText(f"约 {format_tokens(value)} tokens")

    def _show_more_menu(self) -> None:
        menu = QMenu(self)
        regen = QAction(icon("sparkles", MUTED, 15), "重新生成标题", menu)
        regen.triggered.connect(self.regenerate_title_requested)
        clear = QAction(icon("refresh", MUTED, 15), "清空当前对话", menu)
        clear.triggered.connect(self.clear_requested)
        api = QAction(icon("api", MUTED, 15), "API 管理", menu)
        api.triggered.connect(self.api_manager_requested)
        menu.addAction(regen)
        menu.addAction(clear)
        menu.addSeparator()
        delete = QAction(icon("trash", "#FF7483", 15), "删除当前对话", menu)
        delete.triggered.connect(self.delete_requested)
        menu.addAction(delete)
        menu.addSeparator()
        menu.addAction(api)
        menu.exec(self.more_button.mapToGlobal(self.more_button.rect().bottomLeft()))

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if hasattr(self, "toast") and self.toast.isVisible():
            self.toast._reposition()
