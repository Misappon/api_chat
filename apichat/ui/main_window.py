"""Main application window and application-level orchestration."""

from __future__ import annotations

import threading
from dataclasses import replace
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QCloseEvent, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QStackedWidget,
    QStatusBar,
    QWidget,
)

from ..attachment_utils import AttachmentError, prepare_attachment
from ..config import Config
from ..db import Database, DatabaseError
from ..exporter import safe_filename, write_conversation_text
from ..importer import ImportedConversation
from ..lan_server import LanShareServer
from ..llm import clean_title
from ..models import CompletionResult, Conversation, Provider
from ..repository import Repository, RepositoryError
from ..tokens import context_tokens, estimate_tokens, format_tokens
from ..workers import ChatStreamWorker, TitleWorker
from .api_dialog import ApiManagerDialog
from .attachment_preview import AttachmentPreviewDialog
from .chat_page import ChatPage
from .dashboard_page import DashboardPage
from .database_dialog import DatabaseDialog
from .edit_dialog import EditMessageDialog
from .import_dialog import ImportConversationDialog
from .share_dialog import ShareDialog
from .sidebar import Sidebar
from .theme import FAINT, enable_dark_title_bar
from .widgets import Toast


class _LanBridge(QObject):
    changed = Signal(int)


class MainWindow(QMainWindow):
    def __init__(self, config: Config, database: Database, repository: Repository) -> None:
        super().__init__()
        self.config = config
        self.db = database
        self.repo = repository
        self.providers: list[Provider] = []
        self.conversations: list[Conversation] = []
        self.current_conversation: Optional[Conversation] = None
        self._generating = False
        self._chat_worker: Optional[ChatStreamWorker] = None
        self._cancel_event: Optional[threading.Event] = None
        self._stream_provider: Optional[Provider] = None
        self._stream_messages: list[dict] = []
        self._title_workers: dict[int, TitleWorker] = {}
        self._epoch = 0
        self.lan_server: Optional[LanShareServer] = None
        self._lan_bridge = _LanBridge(self)
        self._lan_bridge.changed.connect(self._on_lan_changed)
        self.setWindowTitle("API Chat · 本地 LLM 工作台")
        self.setWindowIcon(QApplication.windowIcon())
        self.setMinimumSize(1060, 700)
        self._build()
        self._install_shortcuts()
        self._restore_geometry()
        self._load_all(restore_last=True)

    # ------------------------------------------------------------------
    # construction
    # ------------------------------------------------------------------
    def _build(self) -> None:
        central = QWidget()
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.sidebar = Sidebar()
        self.stack = QStackedWidget()
        self.chat_page = ChatPage()
        self.dashboard = DashboardPage()
        self.stack.addWidget(self.chat_page)
        self.stack.addWidget(self.dashboard)
        layout.addWidget(self.sidebar)
        layout.addWidget(self.stack, 1)
        self.setCentralWidget(central)
        self.toast = Toast(central)

        self.status = QStatusBar()
        self.setStatusBar(self.status)
        self.status.showMessage("就绪")
        self.db_status = QLabel(f"MySQL · {self.db.name}")
        self.db_status.setStyleSheet(f"color: {FAINT}; font-size: 9px; padding-right: 8px;")
        self.status.addPermanentWidget(self.db_status)
        self.sidebar.set_database_name(self.db.name)
        self.dashboard.set_database_name(self.db.name)
        self.chat_page.set_db_name(self.db.name)

        self.sidebar.new_chat_requested.connect(self.new_conversation)
        self.sidebar.conversation_selected.connect(self.select_conversation)
        self.sidebar.search_changed.connect(self._on_search)
        self.sidebar.dashboard_requested.connect(self.open_dashboard)
        self.sidebar.api_manager_requested.connect(self.open_api_manager)
        self.sidebar.database_requested.connect(self.change_database)
        self.sidebar.import_requested.connect(self.import_shared_conversation)
        self.sidebar.export_requested.connect(self.export_conversation)
        self.sidebar.share_requested.connect(self.open_share_dialog)
        self.sidebar.rename_requested.connect(self.rename_conversation)
        self.sidebar.delete_requested.connect(self.delete_conversation)
        self.sidebar.clear_requested.connect(self.clear_conversation)
        self.sidebar.regenerate_title_requested.connect(self.regenerate_title)

        self.chat_page.send_requested.connect(self.send_message)
        self.chat_page.stop_requested.connect(self.stop_generation)
        self.chat_page.edit_requested.connect(self.edit_message)
        self.chat_page.attachment_preview_requested.connect(self.preview_attachment)
        self.chat_page.export_requested.connect(
            lambda: self.export_conversation(self.current_id())
        )
        self.chat_page.provider_changed.connect(self.change_provider)
        self.chat_page.title_changed.connect(self.title_changed)
        self.chat_page.new_chat_requested.connect(self.new_conversation)
        self.chat_page.api_manager_requested.connect(self.open_api_manager)
        self.chat_page.delete_requested.connect(lambda: self.delete_conversation(self.current_id()))
        self.chat_page.clear_requested.connect(lambda: self.clear_conversation(self.current_id()))
        self.chat_page.regenerate_title_requested.connect(
            lambda: self.regenerate_title(self.current_id())
        )
        self.chat_page.retry_requested.connect(self.retry_generation)
        self.chat_page.toast_requested.connect(self.show_toast)

        self.dashboard.refresh_requested.connect(self.refresh_dashboard)
        self.dashboard.change_database_requested.connect(self.change_database)
        self.dashboard.open_conversation.connect(self._open_from_dashboard)
        self.dashboard.new_chat_requested.connect(self.new_conversation)
        self.dashboard.api_manager_requested.connect(self.open_api_manager)

    def _install_shortcuts(self) -> None:
        QShortcut(QKeySequence("Ctrl+N"), self, self.new_conversation)
        QShortcut(QKeySequence("Ctrl+K"), self, self.sidebar.focus_search)
        QShortcut(QKeySequence("Ctrl+2"), self, self.open_dashboard)
        QShortcut(QKeySequence("Ctrl+1"), self, self._show_chat)

    # ------------------------------------------------------------------
    # initial data
    # ------------------------------------------------------------------
    def _load_all(self, *, restore_last: bool = True) -> None:
        self._reload_providers()
        self._reload_conversations()
        self.stack.setCurrentWidget(self.chat_page)
        self.sidebar.set_dashboard_active(False)
        if not self.conversations:
            self.current_conversation = None
            self.chat_page.show_welcome(bool(self.providers))
            return
        target: Optional[int] = None
        if restore_last:
            value = self.config.get("last_conversation_id")
            if value is not None:
                target = int(value)
                if not any(conversation.id == target for conversation in self.conversations):
                    target = None
        if target is None and self.conversations:
            target = self.conversations[0].id
        if target is not None:
            self.select_conversation(target)

    def _reload_providers(self) -> None:
        try:
            self.providers = self.repo.list_providers()
        except RepositoryError as exc:
            self.providers = []
            QMessageBox.critical(self, "读取 API 失败", str(exc))

    def _reload_conversations(self, search: Optional[str] = None) -> None:
        if search is None:
            search = self.sidebar.search.text().strip()
        try:
            self.conversations = self.repo.list_conversations(search)
        except RepositoryError as exc:
            self.conversations = []
            QMessageBox.critical(self, "读取对话失败", str(exc))
        selected = self.current_conversation.id if self.current_conversation else None
        if selected is not None and not any(c.id == selected for c in self.conversations):
            selected = None
        self.sidebar.set_conversations(self.conversations, selected)
        if not self.conversations and not search:
            self.chat_page.show_welcome(bool(self.providers))
        self._set_status(f"共 {len(self.conversations)} 个对话")

    # ------------------------------------------------------------------
    # conversation lifecycle
    # ------------------------------------------------------------------
    def new_conversation(self) -> None:
        if self._generating:
            self.show_toast("请先停止当前生成")
            return
        if not self.providers:
            answer = QMessageBox.question(
                self,
                "还没有配置 API",
                "新建对话前需要先配置一个模型 API。现在去添加吗？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes,
            )
            if answer == QMessageBox.StandardButton.Yes:
                self.open_api_manager()
            if not self.providers:
                return
        provider = self._preferred_provider()
        if self.sidebar.search.text():
            self.sidebar.search.clear()
        try:
            conversation_id = self.repo.create_conversation(provider.id if provider else None)
        except RepositoryError as exc:
            QMessageBox.critical(self, "创建对话失败", str(exc))
            return
        self._reload_conversations()
        self.select_conversation(conversation_id)
        QTimer.singleShot(60, self.chat_page.focus_composer)

    def select_conversation(self, conversation_id: int) -> None:
        if self._generating:
            self.show_toast("生成过程中不能切换对话")
            return
        try:
            conversation = self.repo.get_conversation(conversation_id)
        except RepositoryError as exc:
            QMessageBox.critical(self, "读取对话失败", str(exc))
            return
        if conversation is None:
            self.show_toast("这个对话已不存在")
            self._reload_conversations()
            return
        if conversation.api_id is None and self.providers:
            default = self._default_provider()
            if default:
                try:
                    self.repo.set_conversation_api(conversation.id, default.id)
                    conversation = self.repo.get_conversation(conversation.id) or conversation
                except RepositoryError:
                    pass
        elif conversation.api_id is not None and not any(
            provider.id == conversation.api_id for provider in self.providers
        ):
            default = self._default_provider()
            try:
                self.repo.set_conversation_api(conversation.id, default.id if default else None)
                conversation = self.repo.get_conversation(conversation.id) or conversation
            except RepositoryError:
                pass
        try:
            messages = self.repo.list_messages(conversation.id)
        except RepositoryError as exc:
            QMessageBox.critical(self, "读取消息失败", str(exc))
            return
        self.current_conversation = conversation
        self.chat_page.load_conversation(conversation, messages, self.providers)
        self.stack.setCurrentWidget(self.chat_page)
        self.sidebar.set_dashboard_active(False)
        self.sidebar.select_conversation(conversation.id, emit=False)
        if conversation.api_id is not None:
            self.config.set("last_provider_id", conversation.api_id, save=False)
        self.status.showMessage("已打开对话", 2500)
        self._maybe_auto_title(conversation.id, force=False)

    def _open_from_dashboard(self, conversation_id: int) -> None:
        self.select_conversation(conversation_id)

    def delete_conversation(self, conversation_id: Optional[int]) -> None:
        if self._generating:
            self.show_toast("请先停止当前生成")
            return
        if conversation_id is None:
            return
        conversation = next((c for c in self.conversations if c.id == conversation_id), None)
        title = conversation.title if conversation else "这个对话"
        answer = QMessageBox.question(
            self,
            "删除对话",
            f"确定删除「{title}」吗？\n\n对话消息与相关用量统计会一起删除，无法恢复。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            self.repo.delete_conversation(conversation_id)
        except RepositoryError as exc:
            QMessageBox.critical(self, "删除失败", str(exc))
            return
        if self.current_conversation and self.current_conversation.id == conversation_id:
            self.current_conversation = None
            self.chat_page.show_welcome(bool(self.providers))
        self._reload_conversations()
        if not self.conversations:
            self.current_conversation = None
            self.chat_page.show_welcome(bool(self.providers))
        else:
            next_conversation = self.conversations[0]
            self.select_conversation(next_conversation.id)
        self.show_toast("对话已删除")

    def clear_conversation(self, conversation_id: Optional[int]) -> None:
        if self._generating:
            self.show_toast("请先停止当前生成")
            return
        if conversation_id is None:
            return
        answer = QMessageBox.question(
            self,
            "清空对话",
            "确定清空当前对话的全部消息吗？\n相关用量统计也会一起清除。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            self.repo.clear_messages(conversation_id)
        except RepositoryError as exc:
            QMessageBox.critical(self, "清空失败", str(exc))
            return
        self.select_conversation(conversation_id)
        self._reload_conversations()
        self.show_toast("对话已清空")

    def rename_conversation(self, conversation_id: int) -> None:
        conversation = next((c for c in self.conversations if c.id == conversation_id), None)
        if conversation is None:
            return
        title, ok = QInputDialog.getText(self, "重命名对话", "对话标题", text=conversation.title)
        if not ok:
            return
        title = title.strip()[:200]
        if not title:
            return
        try:
            self.repo.rename_conversation(conversation_id, title, auto=False)
        except RepositoryError as exc:
            QMessageBox.critical(self, "重命名失败", str(exc))
            return
        if self.current_conversation and self.current_conversation.id == conversation_id:
            self.current_conversation.title = title
            self.current_conversation.title_auto = False
            self.chat_page.set_title(title, False)
        self._reload_conversations()

    def title_changed(self, title: str) -> None:
        if not self.current_conversation:
            return
        try:
            self.repo.rename_conversation(self.current_conversation.id, title, auto=False)
        except RepositoryError as exc:
            QMessageBox.critical(self, "修改标题失败", str(exc))
            return
        self.current_conversation.title = title
        self.current_conversation.title_auto = False
        self.chat_page.set_title(title, False)
        self._reload_conversations()

    # ------------------------------------------------------------------
    # providers / sending
    # ------------------------------------------------------------------
    def _default_provider(self) -> Optional[Provider]:
        return next((p for p in self.providers if p.is_default), self.providers[0] if self.providers else None)

    def _preferred_provider(self) -> Optional[Provider]:
        if self.current_conversation:
            provider = self._provider_for(self.current_conversation)
            if provider:
                return provider
        value = self.config.get("last_provider_id")
        if value is not None:
            provider = next((p for p in self.providers if p.id == int(value)), None)
            if provider:
                return provider
        return self._default_provider()

    def _provider_for(self, conversation: Conversation) -> Optional[Provider]:
        if conversation.api_id is not None:
            provider = next((p for p in self.providers if p.id == conversation.api_id), None)
            if provider:
                return provider
        return self._default_provider()

    def send_message(self, text: str, attachments: Optional[list] = None) -> None:
        if self._generating:
            return
        if not self.current_conversation:
            self.new_conversation()
            if not self.current_conversation:
                return
        provider = self._provider_for(self.current_conversation)
        if provider is None:
            self.chat_page.show_error(
                "当前对话还没有绑定 API。请先在「API 管理」中添加并选择一个 API。",
                can_retry=False,
            )
            return
        text = (text or "").strip()
        attachment_list = list(attachments or [])
        if not text and not attachment_list:
            return
        try:
            prepared = [prepare_attachment(attachment) for attachment in attachment_list]
            self.repo.add_message(
                self.current_conversation.id,
                "user",
                text,
                model=provider.model,
                attachments=prepared,
            )
            messages = self.repo.list_messages(self.current_conversation.id)
        except (RepositoryError, AttachmentError) as exc:
            QMessageBox.critical(self, "发送失败", str(exc))
            return
        if messages:
            self.chat_page.append_message(messages[-1])
        self.chat_page.clear_composer()
        self.chat_page.hide_error()
        self.current_conversation = (
            self.repo.get_conversation(self.current_conversation.id) or self.current_conversation
        )
        self._reload_conversations()
        self.config.set("last_provider_id", provider.id, save=False)
        self._start_stream(provider)

    def _start_stream(self, provider: Provider) -> None:
        if self._generating:
            return
        if self._chat_worker is not None and self._chat_worker.isRunning():
            return
        if not self.current_conversation:
            return
        try:
            messages = self.repo.api_messages(self.current_conversation.id)
        except RepositoryError as exc:
            self.chat_page.show_error(f"读取对话上下文失败：{exc}", can_retry=False)
            return
        if not messages:
            return
        self._stream_provider = provider
        self._stream_messages = messages
        self._cancel_event = threading.Event()
        worker = ChatStreamWorker(provider, messages, self._cancel_event, self)
        worker.delta.connect(self._on_delta)
        worker.succeeded.connect(self._on_stream_succeeded)
        worker.cancelled.connect(self._on_stream_cancelled)
        worker.failed.connect(self._on_stream_failed)
        worker.finished.connect(lambda w=worker: self._on_chat_worker_finished(w))
        self._chat_worker = worker
        self._generating = True
        self.sidebar.set_locked(True)
        self.chat_page.begin_stream(provider)
        self._set_status(f"正在请求 {provider.alias} …")
        worker.start()

    def retry_generation(self) -> None:
        if self._generating:
            return
        if not self.current_conversation:
            return
        provider = self._provider_for(self.current_conversation)
        if provider is None:
            self.chat_page.show_error("没有可用的 API，请先配置。", can_retry=False)
            return
        self.chat_page.hide_error()
        self._start_stream(provider)

    def stop_generation(self) -> None:
        if self._cancel_event is not None:
            self._cancel_event.set()
            self.chat_page.set_stream_status("正在停止…")

    def _on_delta(self, text: str) -> None:
        self.chat_page.update_stream(text)

    def _usage_for(self, provider: Provider, messages: list[dict], result: CompletionResult) -> tuple[int, int, int]:
        prompt = result.prompt_tokens or context_tokens(messages, provider.system_prompt)
        completion = result.completion_tokens or estimate_tokens(result.content)
        # Keep the locally stored total internally consistent even when a
        # partial/cancelled response only reported one side of the usage.
        return prompt, completion, prompt + completion

    def _on_stream_succeeded(self, result: CompletionResult) -> None:
        provider = self._stream_provider
        conversation = self.current_conversation
        if provider is None or conversation is None:
            self._finish_stream_ui()
            return
        content = result.content or ""
        if not content.strip():
            self._on_stream_failed("模型没有返回可显示的内容。")
            return
        prompt, completion, total = self._usage_for(
            provider, self._stream_messages, result
        )
        usage = {
            "api_id": provider.id,
            "api_alias": provider.alias,
            "model": result.model or provider.model,
            "prompt_tokens": prompt,
            "completion_tokens": completion,
            "total_tokens": total,
        }
        try:
            message_id = self.repo.add_message(
                conversation.id,
                "assistant",
                content,
                model=result.model or provider.model,
                token_count=completion,
                usage=usage,
            )
            messages = self.repo.list_messages(conversation.id)
            message = next((m for m in messages if m.id == message_id), None)
        except RepositoryError as exc:
            self.chat_page.remove_stream()
            self.chat_page.show_error(f"回复已生成，但保存到数据库失败：{exc}", can_retry=False)
            self._finish_stream_ui()
            return
        if message is None:
            self.chat_page.remove_stream()
            self._finish_stream_ui()
            return
        self.chat_page.finish_stream(
            message,
            content=content,
            prompt_tokens=prompt,
            completion_tokens=completion,
            model=result.model or provider.model,
        )
        self.current_conversation = self.repo.get_conversation(conversation.id) or conversation
        self._reload_conversations()
        self._finish_stream_ui()
        self._refresh_dashboard_if_visible()
        self._set_status(
            f"完成 · 输入 {format_tokens(prompt)} / 输出 {format_tokens(completion)} tokens"
        )
        if result.finish_reason == "length":
            self.show_toast("回复达到单次输出上限，可能未完整结束")
        self._maybe_auto_title(conversation.id, force=False)

    def _on_stream_cancelled(self, result: CompletionResult) -> None:
        provider = self._stream_provider
        conversation = self.current_conversation
        content = (result.content or "").strip()
        if provider is not None and conversation is not None and content:
            prompt, completion, total = self._usage_for(
                provider, self._stream_messages, result
            )
            try:
                message_id = self.repo.add_message(
                    conversation.id,
                    "assistant",
                    content,
                    model=result.model or provider.model,
                    token_count=completion,
                    usage={
                        "api_id": provider.id,
                        "api_alias": provider.alias,
                        "model": result.model or provider.model,
                        "prompt_tokens": prompt,
                        "completion_tokens": completion,
                        "total_tokens": total,
                    },
                )
                messages = self.repo.list_messages(conversation.id)
                message = next((m for m in messages if m.id == message_id), None)
                if message:
                    self.chat_page.finish_stream(
                        message,
                        content=content,
                        prompt_tokens=prompt,
                        completion_tokens=completion,
                        model=result.model or provider.model,
                    )
                    self.current_conversation = (
                        self.repo.get_conversation(conversation.id) or conversation
                    )
                    self._reload_conversations()
                    self.show_toast("已停止生成，保留了已经生成的内容")
                else:
                    self.chat_page.remove_stream()
            except RepositoryError:
                self.chat_page.remove_stream()
        else:
            self.chat_page.remove_stream()
            self.show_toast("已停止生成")
        self._finish_stream_ui()
        self._refresh_dashboard_if_visible()

    def _on_stream_failed(self, error: str) -> None:
        self.chat_page.remove_stream()
        self.chat_page.show_error(error, can_retry=True)
        self._finish_stream_ui()
        self._set_status("生成失败")

    def _finish_stream_ui(self) -> None:
        self._generating = False
        self.sidebar.set_locked(False)
        self.chat_page.set_generating(False)
        self._stream_provider = None
        self._stream_messages = []

    def _on_chat_worker_finished(self, worker: ChatStreamWorker) -> None:
        if self._chat_worker is worker:
            self._chat_worker = None
            self._cancel_event = None
        worker.deleteLater()

    def change_provider(self, provider_id: int) -> None:
        if not self.current_conversation:
            return
        try:
            self.repo.set_conversation_api(self.current_conversation.id, provider_id)
        except RepositoryError as exc:
            QMessageBox.critical(self, "切换 API 失败", str(exc))
            return
        self.current_conversation = (
            self.repo.get_conversation(self.current_conversation.id) or self.current_conversation
        )
        provider = self._provider_for(self.current_conversation)
        if provider:
            self.config.set("last_provider_id", provider.id, save=False)
        self._reload_conversations()
        self._set_status("已切换 API")

    # ------------------------------------------------------------------
    # editing messages
    # ------------------------------------------------------------------
    def edit_message(self, message_id: int, role: str, content: str) -> None:
        if self._generating:
            self.show_toast("请先停止当前生成")
            return
        if not self.current_conversation:
            return
        try:
            target = self.repo.get_message(message_id)
        except RepositoryError as exc:
            QMessageBox.critical(self, "读取消息失败", str(exc))
            return
        if target is None:
            self.show_toast("消息已不存在，请刷新")
            return
        dialog = EditMessageDialog(target.role, target.content, parent=self)
        if dialog.exec() != EditMessageDialog.DialogCode.Accepted or dialog.mode is None:
            return
        if dialog.mode == "save":
            try:
                self.repo.update_message(target.id, dialog.result_text)
            except RepositoryError as exc:
                QMessageBox.critical(self, "保存失败", str(exc))
                return
            self.select_conversation(self.current_conversation.id)
            self._reload_conversations()
            self.show_toast("消息已修改")
            return

        provider = self._provider_for(self.current_conversation)
        if provider is None:
            QMessageBox.warning(self, "没有可用 API", "重新提交前需要先在 API 管理中选择一个 API。")
            return
        messages = self.repo.list_messages(self.current_conversation.id)
        following = sum(1 for m in messages if m.id > target.id)
        if target.role == "user":
            if following:
                detail = f"此消息之后的 {following} 条消息将被删除，"
            else:
                detail = "将从这条消息重新请求模型，"
        else:
            detail = f"这条回复及其后的 {following} 条消息将被删除，"
        answer = QMessageBox.question(
            self,
            "确认重新提交",
            f"{detail}并产生新的模型回复。\n\n用量统计也会同步更新，是否继续？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            self.repo.edit_and_truncate(
                self.current_conversation.id,
                target.id,
                dialog.result_text,
                keep_target=(target.role == "user"),
            )
        except RepositoryError as exc:
            QMessageBox.critical(self, "修改失败", str(exc))
            return
        conversation_id = self.current_conversation.id
        self.select_conversation(conversation_id)
        self._reload_conversations()
        self._start_stream(provider)

    # ------------------------------------------------------------------
    # titles
    # ------------------------------------------------------------------
    def regenerate_title(self, conversation_id: Optional[int]) -> None:
        if conversation_id is None:
            return
        conversation = self.repo.get_conversation(conversation_id)
        if conversation is None:
            return
        if not self.repo.list_messages(conversation_id):
            self.show_toast("对话里还没有内容，无法生成标题")
            return
        try:
            self.repo.rename_conversation(conversation_id, conversation.title, auto=True)
        except RepositoryError:
            pass
        if self.current_conversation and self.current_conversation.id == conversation_id:
            self.current_conversation.title_auto = True
            self.chat_page.auto_badge.show()
        self._maybe_auto_title(conversation_id, force=True)

    def _maybe_auto_title(self, conversation_id: int, *, force: bool) -> None:
        if conversation_id in self._title_workers:
            return
        try:
            conversation = self.repo.get_conversation(conversation_id)
            messages = self.repo.list_messages(conversation_id)
        except RepositoryError:
            return
        if conversation is None:
            return
        if not force and not (conversation.title_auto and conversation.title == "新对话"):
            return
        if len(messages) < (1 if force else 2):
            return
        provider = self._provider_for(conversation)
        if provider is None:
            return
        api_messages = [
            {"role": m.role, "content": m.content}
            for m in messages
            if m.role in ("user", "assistant")
        ]
        title_provider = replace(provider, system_prompt="")
        epoch = self._epoch
        worker = TitleWorker(conversation_id, title_provider, api_messages, self)
        worker.succeeded.connect(
            lambda cid, result, w=worker, e=epoch: self._on_title_succeeded(cid, result, w, e)
        )
        worker.failed.connect(
            lambda cid, error, w=worker, e=epoch: self._on_title_failed(cid, error, w, e)
        )
        worker.finished.connect(lambda w=worker, cid=conversation_id: self._on_title_worker_done(cid, w))
        self._title_workers[conversation_id] = worker
        if force and self.current_conversation and self.current_conversation.id == conversation_id:
            self._set_status("正在生成标题…")
        worker.start()

    def _on_title_succeeded(
        self,
        conversation_id: int,
        result: CompletionResult,
        worker: TitleWorker,
        epoch: int,
    ) -> None:
        if epoch != self._epoch:
            return
        try:
            conversation = self.repo.get_conversation(conversation_id)
            messages = self.repo.list_messages(conversation_id)
        except RepositoryError:
            return
        if conversation is None:
            return
        fallback = "新对话"
        for message in messages:
            if message.role == "user" and message.content.strip():
                fallback = clean_title(message.content[:40], "新对话")
                break
        title = clean_title(result.content, fallback)
        should_apply = bool(messages) and conversation.title_auto
        try:
            if should_apply:
                self.repo.rename_conversation(conversation_id, title, auto=True)
            provider = self._provider_for(conversation) or worker.provider
            prompt = result.prompt_tokens or estimate_tokens(
                " ".join(m.get("content", "") for m in worker.messages)
            )
            completion = result.completion_tokens or estimate_tokens(result.content)
            self.repo.record_usage(
                conversation_id,
                replace(provider, alias=conversation.api_alias or provider.alias),
                result.model or provider.model,
                prompt,
                completion,
                prompt + completion,
                kind="title",
            )
        except RepositoryError:
            pass
        if should_apply:
            if self.current_conversation and self.current_conversation.id == conversation_id:
                self.current_conversation.title = title
                self.current_conversation.title_auto = True
                self.chat_page.set_title(title, True)
            self._reload_conversations()
            self._set_status("标题已更新")
        self._refresh_dashboard_if_visible()

    def _on_title_failed(
        self, conversation_id: int, error: str, worker: TitleWorker, epoch: int
    ) -> None:
        if epoch != self._epoch:
            return
        try:
            conversation = self.repo.get_conversation(conversation_id)
            messages = self.repo.list_messages(conversation_id)
        except RepositoryError:
            return
        if conversation is None:
            return
        if conversation.title == "新对话":
            fallback = "新对话"
            for message in messages:
                if message.role == "user" and message.content.strip():
                    fallback = clean_title(message.content[:40], "新对话")
                    break
            if fallback != "新对话":
                try:
                    self.repo.rename_conversation(conversation_id, fallback, auto=False)
                except RepositoryError:
                    pass
                if self.current_conversation and self.current_conversation.id == conversation_id:
                    self.current_conversation.title = fallback
                    self.current_conversation.title_auto = False
                    self.chat_page.set_title(fallback, False)
                self._reload_conversations()
        elif conversation.title_auto:
            try:
                self.repo.rename_conversation(conversation_id, conversation.title, auto=False)
            except RepositoryError:
                pass
            if self.current_conversation and self.current_conversation.id == conversation_id:
                self.current_conversation.title_auto = False
                self.chat_page.set_title(conversation.title, False)
        self._set_status(f"标题生成失败：{error.splitlines()[0][:80]}")

    def _on_title_worker_done(self, conversation_id: int, worker: TitleWorker) -> None:
        if self._title_workers.get(conversation_id) is worker:
            self._title_workers.pop(conversation_id, None)
        worker.deleteLater()

    # ------------------------------------------------------------------
    # navigation / dialogs
    # ------------------------------------------------------------------
    def open_dashboard(self) -> None:
        if self._generating:
            self.show_toast("请先停止当前生成")
            return
        self.stack.setCurrentWidget(self.dashboard)
        self.sidebar.set_dashboard_active(True)
        self.refresh_dashboard()

    def _show_chat(self) -> None:
        self.stack.setCurrentWidget(self.chat_page)
        self.sidebar.set_dashboard_active(False)

    def refresh_dashboard(self) -> None:
        try:
            totals, rows, api_rows = self.repo.dashboard()
        except RepositoryError as exc:
            QMessageBox.critical(self, "读取用量失败", str(exc))
            return
        self.dashboard.set_data(totals, rows, api_rows, self.db.name)
        self.dashboard.set_database_name(self.db.name)

    def _refresh_dashboard_if_visible(self) -> None:
        if self.stack.currentWidget() is self.dashboard:
            self.refresh_dashboard()

    # ------------------------------------------------------------------
    # attachments / import / export / LAN
    # ------------------------------------------------------------------
    def preview_attachment(self, attachment_id: int) -> None:
        try:
            attachment = self.repo.get_attachment(attachment_id)
        except RepositoryError as exc:
            QMessageBox.critical(self, "读取附件失败", str(exc))
            return
        if attachment is None:
            self.show_toast("附件已不存在")
            return
        AttachmentPreviewDialog(attachment, self).exec()

    def export_conversation(self, conversation_id: Optional[int]) -> None:
        if conversation_id is None:
            self.show_toast("请先选择一个对话")
            return
        try:
            conversation = self.repo.get_conversation(conversation_id)
            messages = self.repo.list_messages(conversation_id)
        except RepositoryError as exc:
            QMessageBox.critical(self, "读取对话失败", str(exc))
            return
        if conversation is None:
            self.show_toast("对话不存在")
            return
        default_path = Path.home() / safe_filename(conversation.title)
        path, _ = QFileDialog.getSaveFileName(
            self,
            "导出对话",
            str(default_path),
            "文本文件 (*.txt);;Markdown 文件 (*.md);;所有文件 (*.*)",
        )
        if not path:
            return
        target = Path(path)
        if not target.suffix:
            target = target.with_suffix(".txt")
        try:
            write_conversation_text(target, conversation, messages)
        except OSError as exc:
            QMessageBox.critical(self, "导出失败", str(exc))
            return
        self.show_toast(f"已导出到 {target.name}")
        self._set_status(f"已导出：{target}")

    def import_shared_conversation(self) -> None:
        if self._generating:
            self.show_toast("请先停止当前生成")
            return
        dialog = ImportConversationDialog(self)
        if dialog.exec() != ImportConversationDialog.DialogCode.Accepted:
            return
        if dialog.imported is None:
            return
        self._import_conversation_data(dialog.imported)

    def _import_conversation_data(self, imported: ImportedConversation) -> None:
        provider = self._preferred_provider()
        try:
            conversation_id = self.repo.create_conversation(
                provider.id if provider else None,
                title=imported.title or "导入的对话",
            )
            self.repo.rename_conversation(
                conversation_id, imported.title or "导入的对话", auto=False
            )
        except RepositoryError as exc:
            QMessageBox.critical(self, "导入失败", str(exc))
            return
        imported_count = 0
        try:
            for message in imported.messages:
                prepared = []
                for attachment in message.attachments:
                    try:
                        prepared.append(prepare_attachment(attachment))
                    except AttachmentError:
                        continue
                if not message.content.strip() and not prepared:
                    continue
                self.repo.add_message(
                    conversation_id,
                    message.role,
                    message.content,
                    model=provider.model if provider else "",
                    attachments=prepared,
                )
                imported_count += 1
        except (RepositoryError, AttachmentError) as exc:
            try:
                self.repo.delete_conversation(conversation_id)
            except RepositoryError:
                pass
            QMessageBox.critical(self, "导入失败", str(exc))
            return
        if imported_count == 0:
            try:
                self.repo.delete_conversation(conversation_id)
            except RepositoryError:
                pass
            QMessageBox.warning(self, "没有可导入内容", "没有识别到有效的消息。")
            return
        self._reload_conversations()
        self.select_conversation(conversation_id)
        self._set_status(f"已导入 {imported_count} 条消息")
        self.show_toast(f"已导入 {imported_count} 条消息，可继续对话")

    def open_share_dialog(self) -> None:
        dialog = ShareDialog(
            get_server=lambda: self.lan_server,
            start_server=self._start_lan_server,
            stop_server=self._stop_lan_server,
            parent=self,
        )
        dialog.exec()

    def _start_lan_server(self, port: int, token: str) -> LanShareServer:
        self._stop_lan_server()
        server = LanShareServer(
            lambda: dict(self.db.config),
            on_change=self._lan_bridge.changed.emit,
            port=port,
            token=token,
        )
        server.start()
        self.lan_server = server
        self._set_status(f"局域网共享已启动：{server.url}")
        return server

    def _stop_lan_server(self) -> None:
        if self.lan_server is not None:
            self.lan_server.stop()
            self.lan_server = None
            self._set_status("局域网共享已停止")

    def _on_lan_changed(self, conversation_id: int) -> None:
        self._reload_conversations()
        self._refresh_dashboard_if_visible()
        if self._generating:
            return
        if not self.current_conversation or self.current_conversation.id != conversation_id:
            return
        try:
            conversation = self.repo.get_conversation(conversation_id)
            messages = self.repo.list_messages(conversation_id)
        except RepositoryError:
            return
        if conversation is None:
            return
        self.current_conversation = conversation
        self.chat_page.load_conversation(
            conversation, messages, self.providers, preserve_drafts=True
        )
        self.sidebar.select_conversation(conversation_id, emit=False)
        self._set_status("移动端更新了当前对话")

    def open_api_manager(self) -> None:
        if self._generating:
            self.show_toast("请先停止当前生成")
            return
        dialog = ApiManagerDialog(self.repo, self)
        dialog.exec()
        self._reload_providers()
        if self.current_conversation:
            self.select_conversation(self.current_conversation.id)
        else:
            self._reload_conversations()
            self.chat_page.show_welcome(bool(self.providers))
            self.stack.setCurrentWidget(self.chat_page)
            self.sidebar.set_dashboard_active(False)
        self._set_status("API 配置已更新")

    def change_database(self) -> None:
        if self._generating:
            self.show_toast("请先停止当前生成")
            return
        dialog = DatabaseDialog(self.config.database, self)
        if dialog.exec() != DatabaseDialog.DialogCode.Accepted:
            return
        config = dialog.result_config
        if not config:
            return
        was_dashboard = self.stack.currentWidget() is self.dashboard
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        new_db = Database(config)
        try:
            new_db.connect()
        except DatabaseError as exc:
            QApplication.restoreOverrideCursor()
            new_db.close()
            QMessageBox.critical(self, "无法切换数据库", str(exc))
            return
        QApplication.restoreOverrideCursor()
        old_db = self.db
        self._epoch += 1
        self.db = new_db
        self.repo = Repository(new_db)
        self.config.database = config
        self.config.set("last_conversation_id", None, save=False)
        self.config.set("last_provider_id", None, save=False)
        self.config.save()
        old_db.close()
        self.current_conversation = None
        self.sidebar.set_database_name(new_db.name)
        self.dashboard.set_database_name(new_db.name)
        self.chat_page.set_db_name(new_db.name)
        self.db_status.setText(f"MySQL · {new_db.name}")
        self._load_all(restore_last=False)
        if was_dashboard:
            self.stack.setCurrentWidget(self.dashboard)
            self.sidebar.set_dashboard_active(True)
        self.refresh_dashboard()
        self.show_toast(f"已切换到数据库 {new_db.name}")

    # ------------------------------------------------------------------
    # dashboard / search / utility
    # ------------------------------------------------------------------
    def _on_search(self, text: str) -> None:
        self._reload_conversations(text) if text else self._reload_conversations()
        if self.current_conversation and text:
            # Keep the open conversation visible even when it doesn't match.
            if not any(c.id == self.current_conversation.id for c in self.conversations):
                self.sidebar.clear_selection()

    def current_id(self) -> Optional[int]:
        return self.current_conversation.id if self.current_conversation else None

    def _set_status(self, text: str) -> None:
        self.status.showMessage(text, 5000)

    def show_toast(self, text: str) -> None:
        self.toast.show_message(text)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if hasattr(self, "toast") and self.toast.isVisible():
            self.toast._reposition()

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        enable_dark_title_bar(self)

    # ------------------------------------------------------------------
    # geometry / shutdown
    # ------------------------------------------------------------------
    def _restore_geometry(self) -> None:
        window = self.config.window
        width = int(window.get("width") or 1320)
        height = int(window.get("height") or 860)
        self.resize(max(1060, width), max(700, height))
        x, y = window.get("x"), window.get("y")
        if x is not None and y is not None:
            self.move(int(x), int(y))

    def _save_geometry(self) -> None:
        geometry = self.geometry()
        self.config.data["window"] = {
            "width": geometry.width(),
            "height": geometry.height(),
            "x": geometry.x(),
            "y": geometry.y(),
        }

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        if self._chat_worker is not None and self._chat_worker.isRunning():
            answer = QMessageBox.question(
                self,
                "正在生成回复",
                "模型仍在生成回复，退出会停止生成。确定退出吗？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            if self._cancel_event is not None:
                self._cancel_event.set()
            if not self._chat_worker.wait(5000):
                self._chat_worker.terminate()
                self._chat_worker.wait(1000)
        for worker in list(self._title_workers.values()):
            if worker.isRunning():
                worker.terminate()
                worker.wait(800)
        self._title_workers.clear()
        self._stop_lan_server()
        self._save_geometry()
        self.config.set(
            "last_conversation_id",
            self.current_conversation.id if self.current_conversation else None,
            save=False,
        )
        self.config.save()
        self.db.close()
        super().closeEvent(event)
