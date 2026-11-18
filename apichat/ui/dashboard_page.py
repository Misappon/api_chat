"""Aggregated usage console."""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..models import ApiUsageRow, DashboardRow, DashboardTotals
from ..tokens import format_tokens
from ..web_search import normalise_search_sources
from .icons import icon
from .theme import (
    ACCENT,
    FAINT,
    FONT_SCALE_STEP,
    MAX_FONT_SCALE,
    MIN_FONT_SCALE,
    MUTED,
    TEXT,
    full_time,
    percent_color,
)


class NumericItem(QTableWidgetItem):
    def __lt__(self, other) -> bool:  # type: ignore[override]
        left = self.data(Qt.ItemDataRole.UserRole)
        right = other.data(Qt.ItemDataRole.UserRole)
        if isinstance(left, (int, float)) and isinstance(right, (int, float)):
            return left < right
        return self.text().casefold() < other.text().casefold()


class UsageBarChart(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.data: list[tuple[str, int]] = []
        self.setMinimumHeight(190)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def set_data(self, data: list[tuple[str, int]]) -> None:
        self.data = data
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect().adjusted(4, 8, -8, -4)
        if not self.data:
            painter.setPen(QColor(FAINT))
            painter.setFont(QFont("Microsoft YaHei UI", 10))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "还没有用量数据，开始一段对话后会显示在这里")
            return
        top = max(value for _, value in self.data) or 1
        label_width = min(190, max(110, int(rect.width() * 0.3)))
        row_height = max(26, rect.height() // max(len(self.data), 1))
        row_height = min(38, row_height)
        bar_left = rect.left() + label_width + 10
        bar_width = max(40, rect.right() - bar_left - 66)

        font = QFont("Microsoft YaHei UI", 9)
        painter.setFont(font)
        metrics = QFontMetrics(font)
        for index, (label, value) in enumerate(self.data):
            y = rect.top() + index * row_height
            if y + row_height > rect.bottom() + 2:
                break
            painter.setPen(QColor(MUTED))
            elided = metrics.elidedText(label, Qt.TextElideMode.ElideRight, label_width)
            painter.drawText(
                QRectF(rect.left(), y, label_width, row_height),
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                elided,
            )
            track = QRectF(bar_left, y + row_height * 0.3, bar_width, max(6.0, row_height * 0.34))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor("#1C2637"))
            painter.drawRoundedRect(track, 4, 4)
            width = max(3.0, bar_width * (value / top))
            fill = QColor(ACCENT if index == 0 else "#405B9C")
            painter.setBrush(fill)
            painter.drawRoundedRect(QRectF(track.left(), track.top(), width, track.height()), 4, 4)
            painter.setPen(QColor(TEXT if index == 0 else MUTED))
            painter.drawText(
                QRectF(track.right() + 8, y, 62, row_height),
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                format_tokens(value),
            )


class StatCard(QFrame):
    def __init__(self, label: str, hint: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("kpiCard")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 13, 16, 12)
        layout.setSpacing(3)
        title = QLabel(label)
        title.setObjectName("kpiLabel")
        self.value = QLabel("0")
        self.value.setObjectName("kpiValue")
        self.hint = QLabel(hint)
        self.hint.setObjectName("kpiHint")
        layout.addWidget(title)
        layout.addWidget(self.value)
        layout.addWidget(self.hint)
        self.setMinimumHeight(104)

    def set_value(self, value: str, hint: Optional[str] = None) -> None:
        self.value.setText(value)
        if hint is not None:
            self.hint.setText(hint)


class DashboardPage(QWidget):
    refresh_requested = Signal()
    change_database_requested = Signal()
    open_conversation = Signal(int)
    new_chat_requested = Signal()
    api_manager_requested = Signal()
    font_scale_changed = Signal(float)
    attachment_limits_changed = Signal(int, int, int)
    search_sources_changed = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._font_scale = 1.0
        self._updating_search_list = False
        self._build()

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        scroll = QScrollArea()
        scroll.setObjectName("dashboardScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        canvas = QWidget()
        canvas.setObjectName("dashboardCanvas")
        layout = QVBoxLayout(canvas)
        layout.setContentsMargins(28, 24, 28, 30)
        layout.setSpacing(15)

        header = QHBoxLayout()
        title_box = QVBoxLayout()
        title_box.setSpacing(2)
        title = QLabel("综合控制台")
        title.setObjectName("pageTitle")
        self.subtitle = QLabel("API 总用量与各对话用量 · 本地数据库统计")
        self.subtitle.setObjectName("pageSubtitle")
        title_box.addWidget(title)
        title_box.addWidget(self.subtitle)
        header.addLayout(title_box)
        header.addStretch(1)

        self.font_box = QFrame()
        self.font_box.setObjectName("fontBox")
        font_layout = QHBoxLayout(self.font_box)
        font_layout.setContentsMargins(8, 4, 4, 4)
        font_layout.setSpacing(5)
        font_label = QLabel("字号")
        font_label.setObjectName("fontLabel")
        font_layout.addWidget(font_label)
        self.font_down = QToolButton()
        self.font_down.setObjectName("fontButton")
        self.font_down.setText("−")
        self.font_down.setToolTip("减小全局字号 (Ctrl+Shift+-)")
        self.font_down.setFixedSize(25, 24)
        self.font_down.setCursor(Qt.CursorShape.PointingHandCursor)
        self.font_down.clicked.connect(lambda: self._change_font(-FONT_SCALE_STEP))
        font_layout.addWidget(self.font_down)
        self.font_value = QLabel("100%")
        self.font_value.setObjectName("fontValue")
        self.font_value.setAlignment(Qt.AlignmentFlag.AlignCenter)
        font_layout.addWidget(self.font_value)
        self.font_up = QToolButton()
        self.font_up.setObjectName("fontButton")
        self.font_up.setText("+")
        self.font_up.setToolTip("增大全局字号 (Ctrl+Shift++)")
        self.font_up.setFixedSize(25, 24)
        self.font_up.setCursor(Qt.CursorShape.PointingHandCursor)
        self.font_up.clicked.connect(lambda: self._change_font(FONT_SCALE_STEP))
        font_layout.addWidget(self.font_up)
        header.addWidget(self.font_box)

        self.db_button = QPushButton("  切换数据库")
        self.db_button.setIcon(icon("database", MUTED, 15))
        self.db_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.db_button.clicked.connect(self.change_database_requested)
        header.addWidget(self.db_button)
        refresh = QPushButton("  刷新")
        refresh.setIcon(icon("refresh", MUTED, 15))
        refresh.setCursor(Qt.CursorShape.PointingHandCursor)
        refresh.clicked.connect(self.refresh_requested)
        header.addWidget(refresh)
        layout.addLayout(header)

        limit_box = QFrame()
        limit_box.setObjectName("limitBox")
        limit_layout = QHBoxLayout(limit_box)
        limit_layout.setContentsMargins(14, 8, 14, 8)
        limit_layout.setSpacing(8)
        limit_title = QLabel("附件上传上限")
        limit_title.setObjectName("limitTitle")
        limit_layout.addWidget(limit_title)
        limit_hint = QLabel("单文件")
        limit_hint.setObjectName("limitHint")
        limit_layout.addWidget(limit_hint)
        limit_layout.addSpacing(8)
        limit_layout.addWidget(QLabel("图片"))
        self.image_limit_spin = QSpinBox()
        self.image_limit_spin.setObjectName("limitSpin")
        self.image_limit_spin.setRange(1, 50)
        self.image_limit_spin.setValue(10)
        self.image_limit_spin.setSuffix(" MB")
        self.image_limit_spin.setToolTip("单张图片的最大上传大小")
        limit_layout.addWidget(self.image_limit_spin)
        limit_layout.addSpacing(8)
        limit_layout.addWidget(QLabel("文本"))
        self.text_limit_spin = QSpinBox()
        self.text_limit_spin.setObjectName("limitSpin")
        self.text_limit_spin.setRange(1, 20)
        self.text_limit_spin.setValue(2)
        self.text_limit_spin.setSuffix(" MB")
        self.text_limit_spin.setToolTip("单个文本/代码文件的最大上传大小")
        limit_layout.addWidget(self.text_limit_spin)
        limit_layout.addSpacing(8)
        limit_layout.addWidget(QLabel("PDF"))
        self.pdf_limit_spin = QSpinBox()
        self.pdf_limit_spin.setObjectName("limitSpin")
        self.pdf_limit_spin.setRange(1, 50)
        self.pdf_limit_spin.setValue(20)
        self.pdf_limit_spin.setSuffix(" MB")
        self.pdf_limit_spin.setToolTip("单个 PDF 文件的最大上传大小")
        limit_layout.addWidget(self.pdf_limit_spin)
        limit_layout.addStretch(1)
        limit_note = QLabel("对桌面端和手机网页端同时生效")
        limit_note.setObjectName("limitHint")
        limit_layout.addWidget(limit_note)
        layout.addWidget(limit_box)
        self.image_limit_spin.valueChanged.connect(self._emit_attachment_limits)
        self.text_limit_spin.valueChanged.connect(self._emit_attachment_limits)
        self.pdf_limit_spin.valueChanged.connect(self._emit_attachment_limits)

        search_box = QFrame()
        search_box.setObjectName("searchSourceBox")
        search_layout = QVBoxLayout(search_box)
        search_layout.setContentsMargins(14, 8, 14, 9)
        search_layout.setSpacing(5)
        search_title = QLabel("搜索源优先级")
        search_title.setObjectName("limitTitle")
        search_hint = QLabel(
            "开启联网后按从上到下的顺序搜索并汇总；可增删和调整顺序"
        )
        search_hint.setObjectName("limitHint")
        search_layout.addWidget(search_title)
        search_layout.addWidget(search_hint)
        search_body = QHBoxLayout()
        search_body.setSpacing(8)
        self.search_list = QListWidget()
        self.search_list.setObjectName("searchSourceList")
        self.search_list.setFixedHeight(78)
        self.search_list.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self.search_list.itemChanged.connect(self._on_search_item_changed)
        search_body.addWidget(self.search_list, 1)
        search_controls = QVBoxLayout()
        search_controls.setSpacing(4)
        source_row = QHBoxLayout()
        source_row.setSpacing(4)
        self.search_type_combo = QComboBox()
        self.search_type_combo.setObjectName("searchSourceType")
        self.search_type_combo.addItem("Bing", "bing")
        self.search_type_combo.addItem("DuckDuckGo", "duckduckgo")
        self.search_type_combo.addItem("SearXNG", "searxng")
        self.search_type_combo.addItem("Tavily", "tavily")
        source_row.addWidget(self.search_type_combo)
        add_source = QPushButton("添加")
        add_source.setObjectName("smallButton")
        add_source.clicked.connect(self._add_search_source)
        source_row.addWidget(add_source)
        search_controls.addLayout(source_row)
        order_row = QHBoxLayout()
        order_row.setSpacing(4)
        up = QPushButton("↑ 上移")
        up.setObjectName("smallButton")
        up.clicked.connect(lambda: self._move_search_source(-1))
        down = QPushButton("↓ 下移")
        down.setObjectName("smallButton")
        down.clicked.connect(lambda: self._move_search_source(1))
        edit_key = QPushButton("填 Key")
        edit_key.setObjectName("smallButton")
        edit_key.setToolTip("为选中的 Tavily 搜索源填写或更换 API Key")
        edit_key.clicked.connect(self._edit_tavily_key)
        remove = QPushButton("删除")
        remove.setObjectName("smallButton")
        remove.clicked.connect(self._remove_search_source)
        for button in (up, down, edit_key, remove):
            order_row.addWidget(button)
        search_controls.addLayout(order_row)
        search_body.addLayout(search_controls)
        search_layout.addLayout(search_body)
        layout.addWidget(search_box)

        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(12)
        self.total_card = StatCard("API 总用量", "输入 + 输出 tokens")
        self.input_card = StatCard("输入 Tokens", "Prompt tokens")
        self.output_card = StatCard("输出 Tokens", "Completion tokens")
        self.request_card = StatCard("API 请求", "包含对话与自动标题")
        for index, card in enumerate(
            [self.total_card, self.input_card, self.output_card, self.request_card]
        ):
            grid.addWidget(card, 0, index)
            grid.setColumnStretch(index, 1)
        layout.addLayout(grid)

        chart_card = QFrame()
        chart_card.setObjectName("card")
        chart_layout = QVBoxLayout(chart_card)
        chart_layout.setContentsMargins(16, 14, 16, 10)
        chart_layout.setSpacing(2)
        chart_header = QHBoxLayout()
        chart_title = QLabel("对话用量排行")
        chart_title.setObjectName("cardTitle")
        chart_header.addWidget(chart_title)
        chart_header.addStretch(1)
        chart_hint = QLabel("按总 tokens 排序 · 前 6 个对话")
        chart_hint.setObjectName("cardHint")
        chart_header.addWidget(chart_hint)
        chart_layout.addLayout(chart_header)
        self.chart = UsageBarChart()
        chart_layout.addWidget(self.chart, 1)
        chart_card.setMinimumHeight(210)
        layout.addWidget(chart_card)

        conv_card = QFrame()
        conv_card.setObjectName("card")
        conv_layout = QVBoxLayout(conv_card)
        conv_layout.setContentsMargins(16, 14, 16, 9)
        conv_layout.setSpacing(6)
        conv_header = QHBoxLayout()
        conv_title = QLabel("各对话用量")
        conv_title.setObjectName("cardTitle")
        conv_header.addWidget(conv_title)
        conv_header.addStretch(1)
        conv_hint = QLabel("双击行打开对话 · 用量随消息修改、截断或删除自动更新")
        conv_hint.setObjectName("cardHint")
        conv_header.addWidget(conv_hint)
        conv_layout.addLayout(conv_header)
        self.conv_table = QTableWidget(0, 9)
        self.conv_table.setHorizontalHeaderLabels(
            ["对话", "API", "消息", "请求", "输入", "输出", "总 Tokens", "当前上下文", "剩余"]
        )
        self._setup_table(self.conv_table)
        self.conv_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.conv_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        for column in range(2, 9):
            self.conv_table.horizontalHeader().setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        self.conv_table.cellDoubleClicked.connect(self._open_row)
        conv_layout.addWidget(self.conv_table)
        self.conv_empty = QLabel("还没有对话。")
        self.conv_empty.setObjectName("cardHint")
        self.conv_empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.conv_empty.setMinimumHeight(80)
        conv_layout.addWidget(self.conv_empty)
        layout.addWidget(conv_card)

        api_card = QFrame()
        api_card.setObjectName("card")
        api_layout = QVBoxLayout(api_card)
        api_layout.setContentsMargins(16, 14, 16, 9)
        api_layout.setSpacing(6)
        api_header = QHBoxLayout()
        api_title = QLabel("按 API 汇总")
        api_title.setObjectName("cardTitle")
        api_header.addWidget(api_title)
        api_header.addStretch(1)
        api_hint = QLabel("以调用时的别名和模型归档")
        api_hint.setObjectName("cardHint")
        api_header.addWidget(api_hint)
        api_layout.addLayout(api_header)
        self.api_table = QTableWidget(0, 6)
        self.api_table.setHorizontalHeaderLabels(
            ["API 别名", "模型", "请求", "输入", "输出", "总 Tokens"]
        )
        self._setup_table(self.api_table)
        self.api_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.api_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        for column in range(2, 6):
            self.api_table.horizontalHeader().setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        api_layout.addWidget(self.api_table)
        self.api_empty = QLabel("还没有 API 用量。")
        self.api_empty.setObjectName("cardHint")
        self.api_empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.api_empty.setMinimumHeight(70)
        api_layout.addWidget(self.api_empty)
        layout.addWidget(api_card)

        layout.addStretch(1)
        scroll.setWidget(canvas)
        outer.addWidget(scroll)

    @staticmethod
    def _setup_table(table: QTableWidget) -> None:
        table.verticalHeader().setVisible(False)
        table.setShowGrid(False)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setAlternatingRowColors(True)
        table.setSortingEnabled(True)
        table.setMinimumHeight(210)
        table.setMaximumHeight(360)
        table.setCursor(Qt.CursorShape.PointingHandCursor)
        table.horizontalHeader().setHighlightSections(False)

    def set_data(
        self,
        totals: DashboardTotals,
        rows: list[DashboardRow],
        api_rows: list[ApiUsageRow],
        db_name: str,
    ) -> None:
        self.subtitle.setText(
            f"当前数据库 · {db_name} · {totals.conversation_count} 个对话 · 本地统计"
        )
        self.total_card.set_value(
            f"{format_tokens(totals.total_tokens)}",
            f"输入 {format_tokens(totals.prompt_tokens)} · 输出 {format_tokens(totals.completion_tokens)}",
        )
        self.input_card.set_value(format_tokens(totals.prompt_tokens), "Prompt tokens")
        self.output_card.set_value(format_tokens(totals.completion_tokens), "Completion tokens")
        self.request_card.set_value(str(totals.request_count), "包含对话与自动标题请求")
        chart_rows = sorted(rows, key=lambda item: item.total_tokens, reverse=True)[:6]
        self.chart.set_data([(row.title, row.total_tokens) for row in chart_rows])
        self._fill_conversations(rows)
        self._fill_apis(api_rows)

    def _fill_conversations(self, rows: list[DashboardRow]) -> None:
        self.conv_table.setSortingEnabled(False)
        self.conv_table.setRowCount(0)
        for row in rows:
            index = self.conv_table.rowCount()
            self.conv_table.insertRow(index)
            values = [
                (row.title, None, str),
                (row.api_alias, None, str),
                (row.message_count, row.message_count, int),
                (row.request_count, row.request_count, int),
                (format_tokens(row.prompt_tokens), row.prompt_tokens, int),
                (format_tokens(row.completion_tokens), row.completion_tokens, int),
                (format_tokens(row.total_tokens), row.total_tokens, int),
                (format_tokens(row.context_tokens), row.context_tokens, int),
                (f"{row.remaining_percent:.1f}%", row.remaining_percent, float),
            ]
            for column, (text, numeric, kind) in enumerate(values):
                item = NumericItem(str(text))
                if numeric is not None:
                    item.setData(Qt.ItemDataRole.UserRole, numeric)
                if kind is int:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                if column == 8:
                    color = percent_color(row.remaining_percent)
                    item.setForeground(QColor(color))
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if column == 0:
                    item.setData(Qt.ItemDataRole.UserRole + 1, row.conversation_id)
                    item.setToolTip(f"{row.title}\n最近活动：{full_time(row.last_activity)}")
                if column == 1:
                    item.setToolTip(row.model)
                self.conv_table.setItem(index, column, item)
            self.conv_table.setRowHeight(index, 36)
        self.conv_table.setSortingEnabled(True)
        self.conv_table.sortItems(6, Qt.SortOrder.DescendingOrder)
        self.conv_table.setVisible(bool(rows))
        self.conv_empty.setVisible(not rows)

    def _fill_apis(self, rows: list[ApiUsageRow]) -> None:
        self.api_table.setSortingEnabled(False)
        self.api_table.setRowCount(0)
        for row in rows:
            index = self.api_table.rowCount()
            self.api_table.insertRow(index)
            values = [
                (row.api_alias, None),
                (row.model, None),
                (row.request_count, row.request_count),
                (format_tokens(row.prompt_tokens), row.prompt_tokens),
                (format_tokens(row.completion_tokens), row.completion_tokens),
                (format_tokens(row.total_tokens), row.total_tokens),
            ]
            for column, (text, numeric) in enumerate(values):
                item = NumericItem(str(text))
                if numeric is not None:
                    item.setData(Qt.ItemDataRole.UserRole, numeric)
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                if column == 0:
                    item.setToolTip(row.api_alias)
                if column == 1:
                    item.setToolTip(row.model)
                self.api_table.setItem(index, column, item)
            self.api_table.setRowHeight(index, 36)
        self.api_table.setSortingEnabled(True)
        self.api_table.setVisible(bool(rows))
        self.api_empty.setVisible(not rows)

    def _open_row(self, row: int, column: int) -> None:
        item = self.conv_table.item(row, 0)
        if item is None:
            return
        conversation_id = item.data(Qt.ItemDataRole.UserRole + 1)
        if conversation_id is not None:
            self.open_conversation.emit(int(conversation_id))

    def _change_font(self, delta: float) -> None:
        target = max(MIN_FONT_SCALE, min(MAX_FONT_SCALE, self._font_scale + delta))
        self.font_scale_changed.emit(round(target, 2))

    def _emit_attachment_limits(self) -> None:
        self.attachment_limits_changed.emit(
            self.image_limit_spin.value(),
            self.text_limit_spin.value(),
            self.pdf_limit_spin.value(),
        )

    def _current_search_sources(self) -> list[dict[str, str]]:
        result = []
        for index in range(self.search_list.count()):
            data = self.search_list.item(index).data(Qt.ItemDataRole.UserRole)
            if isinstance(data, dict):
                result.append(dict(data))
        return result

    def _render_search_sources(self, sources: list[dict], select_row: int = -1) -> None:
        self._updating_search_list = True
        self.search_list.blockSignals(True)
        self.search_list.clear()
        for index, source in enumerate(sources):
            enabled = source.get("enabled", True)
            mark = "✓" if enabled else "✗"
            key_hint = ""
            if source.get("type") == "tavily":
                key_hint = " · 已配置 Key" if source.get("api_key") else " · 未配置 Key"
            item = QListWidgetItem(
                f"{index + 1}. {source.get('label') or source.get('type')}  {mark}{key_hint}"
            )
            if not enabled:
                item.setForeground(QColor(FAINT))
            hint = "已启用" if enabled else "已禁用（不参与搜索）"
            tooltip = f"{hint}\n{source.get('endpoint') or ''}"
            if key_hint:
                tooltip += f"\n{key_hint.strip(' ·')}"
            item.setToolTip(tooltip)
            item.setData(Qt.ItemDataRole.UserRole, dict(source))
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(
                Qt.CheckState.Checked if enabled else Qt.CheckState.Unchecked
            )
            self.search_list.addItem(item)
        if 0 <= select_row < self.search_list.count():
            self.search_list.setCurrentRow(select_row)
        self.search_list.blockSignals(False)
        self._updating_search_list = False

    def _on_search_item_changed(self, item: QListWidgetItem) -> None:
        if self._updating_search_list:
            return
        data = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(data, dict):
            return
        enabled = item.checkState() == Qt.CheckState.Checked
        if bool(data.get("enabled", True)) == enabled:
            return
        row = self.search_list.row(item)
        sources = self._current_search_sources()
        sources[row]["enabled"] = enabled
        self._commit_search_sources(sources, select_row=row)

    def set_search_sources(self, sources: object) -> None:
        self._render_search_sources(normalise_search_sources(sources))

    def _commit_search_sources(
        self, sources: list[dict], *, select_row: int = -1
    ) -> None:
        sources = normalise_search_sources(sources)
        self._render_search_sources(sources, select_row=select_row)
        self.search_sources_changed.emit(sources)

    def _add_search_source(self) -> None:
        kind = str(self.search_type_combo.currentData() or "bing")
        endpoint = ""
        api_key = ""
        if kind == "searxng":
            endpoint, ok = QInputDialog.getText(
                self,
                "添加 SearXNG",
                "公网 HTTPS SearXNG 地址（需支持 format=json）：",
            )
            if not ok or not endpoint.strip():
                return
            endpoint = endpoint.strip()
        elif kind == "tavily":
            api_key, ok = QInputDialog.getText(
                self,
                "添加 Tavily",
                "Tavily API Key（以 tvly- 开头，保存在本地配置中）：",
                QLineEdit.EchoMode.Password,
            )
            if not ok or not api_key.strip():
                return
            api_key = api_key.strip()
        sources = self._current_search_sources()
        before = len(normalise_search_sources(sources))
        sources.append(
            {
                "id": "",
                "type": kind,
                "label": {
                    "bing": "Bing",
                    "duckduckgo": "DuckDuckGo",
                    "searxng": "SearXNG",
                    "tavily": "Tavily",
                }.get(kind, kind),
                "endpoint": endpoint,
                "api_key": api_key,
                "enabled": True,
            }
        )
        normalized = normalise_search_sources(sources)
        if len(normalized) <= before:
            QMessageBox.information(
                self,
                "搜索源未添加",
                "该搜索源已存在，或 SearXNG 地址不是公网 HTTPS 地址。",
            )
            return
        self._commit_search_sources(normalized, select_row=len(normalized) - 1)

    def _edit_tavily_key(self) -> None:
        row = self.search_list.currentRow()
        sources = self._current_search_sources()
        if row < 0 or sources[row].get("type") != "tavily":
            QMessageBox.information(self, "无法编辑", "请先选中 Tavily 搜索源。")
            return
        api_key, ok = QInputDialog.getText(
            self,
            "Tavily API Key",
            "输入新的 API Key（留空则表示不修改）：",
            QLineEdit.EchoMode.Password,
        )
        if not ok:
            return
        api_key = api_key.strip()
        if api_key:
            sources[row]["api_key"] = api_key
        self._commit_search_sources(sources, select_row=row)

    def _move_search_source(self, delta: int) -> None:
        row = self.search_list.currentRow()
        target = row + delta
        sources = self._current_search_sources()
        if row < 0 or target < 0 or target >= len(sources):
            return
        sources[row], sources[target] = sources[target], sources[row]
        self._commit_search_sources(sources)
        self.search_list.setCurrentRow(target)

    def _remove_search_source(self) -> None:
        row = self.search_list.currentRow()
        sources = self._current_search_sources()
        if row < 0 or len(sources) <= 1:
            return
        sources.pop(row)
        self._commit_search_sources(sources)

    def set_attachment_limits(self, image_mb: int, text_mb: int, pdf_mb: int) -> None:
        self.image_limit_spin.blockSignals(True)
        self.text_limit_spin.blockSignals(True)
        self.pdf_limit_spin.blockSignals(True)
        self.image_limit_spin.setValue(max(1, min(50, int(image_mb))))
        self.text_limit_spin.setValue(max(1, min(20, int(text_mb))))
        self.pdf_limit_spin.setValue(max(1, min(50, int(pdf_mb))))
        self.image_limit_spin.blockSignals(False)
        self.text_limit_spin.blockSignals(False)
        self.pdf_limit_spin.blockSignals(False)

    def set_font_scale(self, scale: float) -> None:
        self._font_scale = max(MIN_FONT_SCALE, min(MAX_FONT_SCALE, scale))
        self.font_value.setText(f"{int(round(self._font_scale * 100))}%")
        self.font_down.setEnabled(self._font_scale > MIN_FONT_SCALE + 0.001)
        self.font_up.setEnabled(self._font_scale < MAX_FONT_SCALE - 0.001)

    def set_database_name(self, name: str) -> None:
        self.db_button.setToolTip(f"当前数据库：{name}\n点击切换")
