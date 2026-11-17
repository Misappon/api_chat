"""Conversation sidebar with search, context meters and navigation."""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ..models import Conversation
from ..tokens import estimate_tokens, format_tokens
from .icons import icon
from .theme import FAINT, MUTED, humanize_time
from .widgets import ContextLine, ElidedLabel, SectionTitle


class ConversationCard(QFrame):
    def __init__(self, conversation: Conversation, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.conversation = conversation
        self.setObjectName("conversationCard")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(4)

        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(6)
        self.title_label = ElidedLabel(conversation.title)
        self.title_label.setObjectName("conversationTitle")
        self.title_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        self.title_label.setMinimumWidth(80)
        self.time_label = QLabel(humanize_time(conversation.last_message_at or conversation.updated_at))
        self.time_label.setObjectName("conversationMeta")
        self.time_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        top.addWidget(self.title_label, 1)
        top.addWidget(self.time_label, 0)
        layout.addLayout(top)

        detail_parts = []
        if conversation.api_alias:
            detail_parts.append(conversation.api_alias)
        else:
            detail_parts.append("未绑定 API")
        if conversation.message_count:
            detail_parts.append(f"{conversation.message_count} 条")
        if conversation.usage_total:
            detail_parts.append(f"累计 {format_tokens(conversation.usage_total)}")
        detail = ElidedLabel(" · ".join(detail_parts))
        detail.setObjectName("conversationMeta")
        detail.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        layout.addWidget(detail)

        self.context_line = ContextLine()
        self.context_line.update_context(
            conversation.context_tokens
            + estimate_tokens(conversation.system_prompt),
            conversation.context_window,
        )
        layout.addWidget(self.context_line)
        self.setToolTip(
            f"{conversation.title}\n"
            f"API：{conversation.api_alias or '未绑定'}\n"
            f"上下文：约 {format_tokens(conversation.context_tokens)} / "
            f"{format_tokens(conversation.context_window)} tokens\n"
            f"累计用量：{format_tokens(conversation.usage_total)} tokens"
        )
        for child in self.findChildren(QWidget):
            if child is not self:
                child.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    def set_selected(self, selected: bool) -> None:
        self.setProperty("selected", "true" if selected else "false")
        self.style().unpolish(self)
        self.style().polish(self)


class Sidebar(QFrame):
    new_chat_requested = Signal()
    conversation_selected = Signal(int)
    search_changed = Signal(str)
    dashboard_requested = Signal()
    api_manager_requested = Signal()
    database_requested = Signal()
    import_requested = Signal()
    export_requested = Signal(int)
    share_requested = Signal()
    rename_requested = Signal(int)
    delete_requested = Signal(int)
    clear_requested = Signal(int)
    regenerate_title_requested = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("sidebar")
        self.setFixedWidth(300)
        self._conversations: list[Conversation] = []
        self._cards: dict[int, ConversationCard] = {}
        self._current_id: Optional[int] = None
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(220)
        self._search_timer.timeout.connect(
            lambda: self.search_changed.emit(self.search.text().strip())
        )
        self._build()

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 17, 15, 12)
        layout.setSpacing(12)

        brand = QHBoxLayout()
        brand.setSpacing(10)
        mark = QLabel("A")
        mark.setObjectName("brandMark")
        mark.setFixedSize(38, 38)
        mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        brand.addWidget(mark)
        brand_text = QVBoxLayout()
        brand_text.setSpacing(0)
        name = QLabel("API Chat")
        name.setObjectName("brandName")
        sub = QLabel("LOCAL LLM DESK")
        sub.setObjectName("brandSub")
        brand_text.addWidget(name)
        brand_text.addWidget(sub)
        brand.addLayout(brand_text)
        brand.addStretch(1)
        layout.addLayout(brand)

        new_row = QHBoxLayout()
        new_row.setSpacing(6)
        self.new_button = QPushButton("  新建对话")
        self.new_button.setObjectName("newChat")
        self.new_button.setIcon(icon("plus", "#FFFFFF", 17))
        self.new_button.setIconSize(QSize(17, 17))
        self.new_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.new_button.setToolTip("新建对话 (Ctrl+N)")
        self.new_button.clicked.connect(self.new_chat_requested)
        new_row.addWidget(self.new_button, 1)
        self.new_more = QPushButton()
        self.new_more.setObjectName("newMore")
        self.new_more.setIcon(icon("more", MUTED, 19))
        self.new_more.setIconSize(QSize(19, 19))
        self.new_more.setFixedSize(37, 37)
        self.new_more.setCursor(Qt.CursorShape.PointingHandCursor)
        self.new_more.setToolTip("导入网页分享对话、导出或局域网共享")
        self.new_more.clicked.connect(self._show_new_menu)
        new_row.addWidget(self.new_more, 0)
        layout.addLayout(new_row)

        self.search = QLineEdit()
        self.search.setObjectName("search")
        self.search.setPlaceholderText("搜索对话…")
        self.search.addAction(icon("search", FAINT, 15), QLineEdit.ActionPosition.LeadingPosition)
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(lambda: self._search_timer.start())
        layout.addWidget(self.search)

        self.section = SectionTitle("对话", 0)
        layout.addWidget(self.section)

        self.list = QListWidget()
        self.list.setObjectName("conversationList")
        self.list.setFrameShape(QFrame.Shape.NoFrame)
        self.list.setSpacing(5)
        self.list.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list.currentItemChanged.connect(self._on_current_changed)
        self.list.customContextMenuRequested.connect(self._show_context_menu)

        self.list_stack = QStackedWidget()
        list_page = QWidget()
        list_layout = QVBoxLayout(list_page)
        list_layout.setContentsMargins(0, 0, 0, 0)
        list_layout.setSpacing(0)
        list_layout.addWidget(self.list)
        self.list_stack.addWidget(list_page)

        empty_page = QWidget()
        empty_layout = QVBoxLayout(empty_page)
        empty_layout.setContentsMargins(0, 0, 0, 0)
        empty_layout.addStretch(1)
        self.empty_label = QLabel("还没有对话\n点击上方「新建对话」开始")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.setStyleSheet(
            "color: #5E6B80; font-size: 11px; line-height: 1.6; padding: 8px;"
        )
        empty_layout.addWidget(self.empty_label)
        empty_layout.addStretch(1)
        self.list_stack.addWidget(empty_page)
        self.list_stack.setCurrentWidget(empty_page)
        layout.addWidget(self.list_stack, 1)

        self.dashboard_button = QPushButton("  综合控制台")
        self.dashboard_button.setObjectName("navButton")
        self.dashboard_button.setIcon(icon("dashboard", MUTED, 17))
        self.dashboard_button.setIconSize(QSize(17, 17))
        self.dashboard_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.dashboard_button.setCheckable(True)
        self.dashboard_button.clicked.connect(self.dashboard_requested)
        layout.addWidget(self.dashboard_button)

        self.api_button = QPushButton("  API 管理")
        self.api_button.setObjectName("navButton")
        self.api_button.setIcon(icon("api", MUTED, 17))
        self.api_button.setIconSize(QSize(17, 17))
        self.api_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.api_button.clicked.connect(self.api_manager_requested)
        layout.addWidget(self.api_button)

        self.share_button = QPushButton("  局域网共享")
        self.share_button.setObjectName("navButton")
        self.share_button.setIcon(icon("wifi", MUTED, 17))
        self.share_button.setIconSize(QSize(17, 17))
        self.share_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.share_button.setToolTip("在局域网内用手机浏览器访问")
        self.share_button.clicked.connect(self.share_requested)
        layout.addWidget(self.share_button)

        self.db_button = QPushButton("  api_chat")
        self.db_button.setObjectName("dbChip")
        self.db_button.setIcon(icon("database", MUTED, 15))
        self.db_button.setIconSize(QSize(15, 15))
        self.db_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.db_button.setToolTip("切换数据库")
        self.db_button.clicked.connect(self.database_requested)
        layout.addWidget(self.db_button)

        footer = QHBoxLayout()
        footer.setContentsMargins(2, 2, 2, 0)
        version = QLabel("v1.0 · MySQL")
        version.setStyleSheet(f"color: {FAINT}; font-size: 9px;")
        footer.addWidget(version)
        footer.addStretch(1)
        settings = QPushButton("设置")
        settings.setObjectName("ghostButton")
        settings.setCursor(Qt.CursorShape.PointingHandCursor)
        settings.setStyleSheet(f"color: {FAINT}; font-size: 9px; border: none; padding: 2px;")
        settings.clicked.connect(self.database_requested)
        footer.addWidget(settings)
        layout.addLayout(footer)

    # ------------------------------------------------------------------
    def set_conversations(self, conversations: list[Conversation], selected_id: Optional[int] = None) -> None:
        scroll = self.list.verticalScrollBar().value()
        self._conversations = conversations
        self.list.blockSignals(True)
        self.list.clear()
        self._cards.clear()
        for conversation in conversations:
            item = QListWidgetItem()
            item.setSizeHint(QSize(0, 89))
            item.setData(Qt.ItemDataRole.UserRole, conversation.id)
            card = ConversationCard(conversation)
            self.list.addItem(item)
            self.list.setItemWidget(item, card)
            self._cards[conversation.id] = card
            if conversation.id == selected_id:
                self.list.setCurrentItem(item)
        self.list.blockSignals(False)
        self.section.set_count(len(conversations))
        self.list_stack.setCurrentIndex(0 if conversations else 1)
        self._current_id = selected_id
        self._update_card_selection()
        self.list.verticalScrollBar().setValue(scroll)
        if selected_id is not None:
            self.select_conversation(selected_id, emit=False)

    def select_conversation(self, conversation_id: int, *, emit: bool = False) -> None:
        self.list.blockSignals(True)
        found = False
        for index in range(self.list.count()):
            item = self.list.item(index)
            if int(item.data(Qt.ItemDataRole.UserRole)) == conversation_id:
                self.list.setCurrentItem(item)
                found = True
                break
        self.list.blockSignals(False)
        self._current_id = conversation_id if found else None
        self._update_card_selection()
        if found and emit:
            self.conversation_selected.emit(conversation_id)

    def current_id(self) -> Optional[int]:
        return self._current_id

    def clear_selection(self) -> None:
        self.list.blockSignals(True)
        self.list.clearSelection()
        self.list.setCurrentItem(None)
        self.list.blockSignals(False)
        self._current_id = None
        self._update_card_selection()

    def set_database_name(self, name: str) -> None:
        self.db_button.setText(f"  {name}")

    def set_dashboard_active(self, active: bool) -> None:
        self.dashboard_button.setChecked(active)

    def set_locked(self, locked: bool) -> None:
        """Prevent switching context while a response is streaming."""
        self.list.setEnabled(not locked)
        self.new_button.setEnabled(not locked)
        self.new_more.setEnabled(not locked)
        self.dashboard_button.setEnabled(not locked)
        self.api_button.setEnabled(not locked)
        self.share_button.setEnabled(not locked)
        self.db_button.setEnabled(not locked)
        self.search.setEnabled(not locked)

    def focus_search(self) -> None:
        self.search.setFocus()
        self.search.selectAll()

    def _update_card_selection(self) -> None:
        for conversation_id, card in self._cards.items():
            card.set_selected(conversation_id == self._current_id)

    def _on_current_changed(self, current: Optional[QListWidgetItem], previous) -> None:
        if current is None:
            self._current_id = None
        else:
            self._current_id = int(current.data(Qt.ItemDataRole.UserRole))
        self._update_card_selection()
        if self._current_id is not None:
            self.conversation_selected.emit(self._current_id)

    def _show_new_menu(self) -> None:
        menu = QMenu(self)
        import_action = QAction(icon("link", MUTED, 15), "导入网页分享对话…", menu)
        import_action.triggered.connect(self.import_requested)
        export_action = QAction(icon("download", MUTED, 15), "导出当前对话…", menu)
        export_action.setEnabled(self._current_id is not None)
        export_action.triggered.connect(lambda: self.export_requested.emit(self._current_id or 0))
        share_action = QAction(icon("wifi", MUTED, 15), "共享到局域网…", menu)
        share_action.triggered.connect(self.share_requested)
        menu.addAction(import_action)
        menu.addAction(export_action)
        menu.addSeparator()
        menu.addAction(share_action)
        menu.exec(self.new_more.mapToGlobal(self.new_more.rect().bottomLeft()))

    def _show_context_menu(self, position) -> None:
        item = self.list.itemAt(position)
        if not item:
            return
        conversation_id = int(item.data(Qt.ItemDataRole.UserRole))
        menu = QMenu(self)
        rename = QAction(icon("edit", MUTED, 15), "重命名", menu)
        rename.triggered.connect(lambda: self.rename_requested.emit(conversation_id))
        regen = QAction(icon("sparkles", MUTED, 15), "自动生成标题", menu)
        regen.triggered.connect(lambda: self.regenerate_title_requested.emit(conversation_id))
        export = QAction(icon("download", MUTED, 15), "导出为文本文件", menu)
        export.triggered.connect(lambda: self.export_requested.emit(conversation_id))
        clear = QAction(icon("refresh", MUTED, 15), "清空消息", menu)
        clear.triggered.connect(lambda: self.clear_requested.emit(conversation_id))
        delete = QAction(icon("trash", "#FF7483", 15), "删除对话", menu)
        delete.triggered.connect(lambda: self.delete_requested.emit(conversation_id))
        menu.addAction(rename)
        menu.addAction(regen)
        menu.addAction(export)
        menu.addSeparator()
        menu.addAction(clear)
        menu.addAction(delete)
        menu.exec(self.list.viewport().mapToGlobal(position))
