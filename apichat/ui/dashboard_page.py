"""Aggregated usage console."""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..models import ApiUsageRow, DashboardRow, DashboardTotals
from ..tokens import format_tokens
from .icons import icon
from .theme import ACCENT, FAINT, MUTED, TEXT, full_time, percent_color


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

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
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

    def set_database_name(self, name: str) -> None:
        self.db_button.setToolTip(f"当前数据库：{name}\n点击切换")
