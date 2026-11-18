"""Visual language for the application."""

from __future__ import annotations

import ctypes
import re
import sys
from datetime import datetime, date, timedelta
from pathlib import Path

from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication, QWidget

BG = "#0B0E14"
SIDEBAR = "#0D1119"
SURFACE = "#121824"
SURFACE_2 = "#171F2D"
SURFACE_3 = "#1D2636"
BORDER = "#263044"
BORDER_SOFT = "#1B2331"
TEXT = "#E8EDF7"
MUTED = "#94A0B5"
FAINT = "#66738A"
ACCENT = "#6D8BFF"
ACCENT_HOVER = "#86A0FF"
ACCENT_SOFT = "#202C4C"
GREEN = "#41D99A"
AMBER = "#F2B84B"
RED = "#FF7483"
CYAN = "#5DD6E8"

FONT_FAMILY = '"Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI"'
DEFAULT_FONT_SCALE = 1.0
MIN_FONT_SCALE = 0.80
MAX_FONT_SCALE = 1.50
FONT_SCALE_STEP = 0.05
_FONT_SCALE = DEFAULT_FONT_SCALE
_ASSET_ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
_CHEVRON_DOWN = (_ASSET_ROOT / "assets" / "chevron-down.svg").as_posix()
_CHEVRON_UP = (_ASSET_ROOT / "assets" / "chevron-up.svg").as_posix()
_CHECK_MARK = (_ASSET_ROOT / "assets" / "check.svg").as_posix()


def percent_color(percent: float) -> str:
    if percent < 15:
        return RED
    if percent < 40:
        return AMBER
    return GREEN


QSS = f"""
* {{
    font-family: {FONT_FAMILY};
    outline: none;
}}
QWidget {{
    color: {TEXT};
    background-color: transparent;
}}
QMainWindow, QDialog {{
    background-color: {BG};
}}
QToolTip {{
    background-color: {SURFACE_3};
    color: {TEXT};
    border: 1px solid {BORDER};
    padding: 6px 8px;
    border-radius: 6px;
}}

/* ---------- shell ---------- */
QFrame#sidebar {{
    background-color: {SIDEBAR};
    border-right: 1px solid {BORDER_SOFT};
}}
QLabel#brandName {{
    font-size: 19px;
    font-weight: 700;
    color: {TEXT};
}}
QLabel#brandSub {{
    font-size: 9px;
    color: {FAINT};
    letter-spacing: 2px;
}}
QLabel#brandMark {{
    background-color: {ACCENT};
    color: white;
    border-radius: 10px;
    font-size: 17px;
    font-weight: 800;
}}
QLabel#sectionLabel {{
    color: {FAINT};
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 1px;
}}
QLabel#countBadge {{
    color: {MUTED};
    background-color: {SURFACE_2};
    border-radius: 8px;
    padding: 1px 7px;
    font-size: 10px;
}}
QLineEdit#search {{
    background-color: {SURFACE};
    border: 1px solid {BORDER_SOFT};
    border-radius: 10px;
    padding: 8px 10px 8px 32px;
    color: {TEXT};
    font-size: 12px;
    selection-background-color: {ACCENT_SOFT};
}}
QLineEdit#search:focus {{
    border-color: {BORDER};
    background-color: {SURFACE_2};
}}
QPushButton#newChat {{
    background-color: {ACCENT};
    color: white;
    border: none;
    border-radius: 10px;
    padding: 10px 14px;
    font-size: 13px;
    font-weight: 700;
    text-align: left;
}}
QPushButton#newChat:hover {{ background-color: {ACCENT_HOVER}; }}
QPushButton#newChat:pressed {{ background-color: #5874DF; }}
QPushButton#newMore {{
    background-color: {SURFACE_2};
    border: 1px solid {BORDER};
    border-radius: 10px;
    padding: 0;
}}
QPushButton#newMore:hover {{
    background-color: {SURFACE_3};
    border-color: #3A4A68;
}}
QPushButton#newMore:disabled {{
    background-color: #111721;
    border-color: {BORDER_SOFT};
}}

QListWidget#conversationList {{
    background: transparent;
    border: none;
    padding: 0;
}}
QListWidget#conversationList::item {{
    background: transparent;
    border: none;
    padding: 0;
    margin: 0;
}}
QFrame#conversationCard {{
    background-color: transparent;
    border: 1px solid transparent;
    border-radius: 11px;
}}
QFrame#conversationCard:hover {{
    background-color: #121A27;
}}
QFrame#conversationCard[selected="true"] {{
    background-color: #182238;
    border: 1px solid #2B3B5D;
}}
QLabel#conversationTitle {{
    color: {TEXT};
    font-size: 13px;
    font-weight: 600;
}}
QLabel#conversationMeta {{
    color: {FAINT};
    font-size: 10px;
}}
QLabel#conversationPercent {{
    font-size: 10px;
    font-weight: 600;
}}
QProgressBar#contextBar {{
    background-color: #232D3F;
    border: none;
    border-radius: 2px;
    height: 4px;
    text-align: center;
}}
QProgressBar#contextBar::chunk {{
    border-radius: 2px;
    background-color: {GREEN};
}}
QProgressBar#contextBar[state="warn"]::chunk {{ background-color: {AMBER}; }}
QProgressBar#contextBar[state="danger"]::chunk {{ background-color: {RED}; }}
QProgressBar#contextBar[state="empty"]::chunk {{ background-color: {FAINT}; }}

QPushButton#navButton {{
    background: transparent;
    border: none;
    color: {MUTED};
    text-align: left;
    padding: 9px 12px;
    border-radius: 9px;
    font-size: 12px;
}}
QPushButton#navButton:hover {{
    background-color: {SURFACE};
    color: {TEXT};
}}
QPushButton#navButton:checked {{
    background-color: {ACCENT_SOFT};
    color: #C7D5FF;
}}
QPushButton#dbChip {{
    background-color: {SURFACE};
    border: 1px solid {BORDER_SOFT};
    border-radius: 8px;
    color: {MUTED};
    padding: 7px 10px;
    text-align: left;
    font-size: 11px;
}}
QPushButton#dbChip:hover {{
    border-color: {BORDER};
    color: {TEXT};
}}

/* ---------- chat ---------- */
QFrame#chatHeader {{
    background-color: {BG};
    border-bottom: 1px solid {BORDER_SOFT};
}}
QLineEdit#chatTitle {{
    background: transparent;
    border: 1px solid transparent;
    border-radius: 7px;
    padding: 3px 6px;
    color: {TEXT};
    font-size: 18px;
    font-weight: 700;
}}
QLineEdit#chatTitle:hover {{ background-color: {SURFACE}; }}
QLineEdit#chatTitle:focus {{
    background-color: {SURFACE};
    border-color: {BORDER};
}}
QLabel#autoTitleBadge {{
    color: {CYAN};
    background-color: #10252C;
    border: 1px solid #1B414B;
    border-radius: 7px;
    padding: 2px 7px;
    font-size: 9px;
    font-weight: 600;
}}
QComboBox#apiCombo {{
    background-color: {SURFACE_2};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 5px 26px 5px 9px;
    color: {TEXT};
    font-size: 11px;
    min-width: 120px;
}}
QComboBox#apiCombo:hover {{ border-color: #384766; }}
QComboBox#apiCombo::drop-down {{ border: none; width: 22px; }}
QComboBox#apiCombo::down-arrow {{
    image: url("{_CHEVRON_DOWN}");
    width: 9px;
    height: 9px;
    margin-right: 8px;
}}
QComboBox QAbstractItemView {{
    background-color: {SURFACE_2};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 4px;
    selection-background-color: {ACCENT_SOFT};
    selection-color: {TEXT};
    color: {TEXT};
}}
QFrame#contextPill {{
    background-color: {SURFACE};
    border: 1px solid {BORDER_SOFT};
    border-radius: 9px;
    padding: 4px 9px;
}}
QLabel#contextText {{ color: {MUTED}; font-size: 10px; }}
QLabel#contextPercent {{ font-size: 11px; font-weight: 700; }}
QProgressBar#contextPillBar {{
    background-color: #222D40;
    border: none;
    border-radius: 2px;
    height: 3px;
}}
QProgressBar#contextPillBar::chunk {{
    border-radius: 2px;
    background-color: {GREEN};
}}
QProgressBar#contextPillBar[state="warn"]::chunk {{ background-color: {AMBER}; }}
QProgressBar#contextPillBar[state="danger"]::chunk {{ background-color: {RED}; }}
QProgressBar#contextPillBar[state="empty"]::chunk {{ background-color: {FAINT}; }}

QScrollArea#messageScroll {{
    background-color: {BG};
    border: none;
}}
QScrollArea#messageScroll > QWidget > QWidget {{
    background-color: {BG};
}}
QWidget#messageCanvas {{ background-color: {BG}; }}

QFrame#userBubble {{
    background-color: #223C78;
    border: 1px solid #2E4C90;
    border-radius: 15px;
}}
QFrame#assistantBubble {{
    background-color: {SURFACE};
    border: 1px solid {BORDER_SOFT};
    border-radius: 15px;
}}
QFrame#streamBubble {{
    background-color: {SURFACE};
    border: 1px solid #2B3B5D;
    border-radius: 15px;
}}
QLabel#roleLabel {{
    color: {MUTED};
    font-size: 10px;
    font-weight: 700;
}}
QLabel#roleLabelUser {{
    color: #AFC6FF;
    font-size: 10px;
    font-weight: 700;
}}
QLabel#messageMeta {{
    color: {FAINT};
    font-size: 9px;
}}
QLabel#streamingLabel {{
    color: {ACCENT};
    font-size: 10px;
}}
QTextBrowser#markdownView {{
    background: transparent;
    border: none;
    padding: 0;
    color: {TEXT};
    font-size: 13px;
    selection-background-color: #334C86;
}}
QToolButton#tinyButton {{
    background: transparent;
    border: none;
    border-radius: 5px;
    padding: 3px;
    color: {MUTED};
}}
QToolButton#tinyButton:hover {{
    background-color: {SURFACE_3};
    color: {TEXT};
}}
QLabel#avatarUser {{
    background-color: #2C4B91;
    color: #DCE6FF;
    border-radius: 14px;
    font-size: 10px;
    font-weight: 700;
}}
QLabel#avatarAI {{
    background-color: #172C2A;
    color: {GREEN};
    border: 1px solid #244B43;
    border-radius: 14px;
    font-size: 10px;
    font-weight: 700;
}}

QFrame#composer {{
    background-color: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 15px;
}}
QFrame#composer[focused="true"] {{
    border-color: #3A4D77;
    background-color: #141B29;
}}
QPlainTextEdit#composerEdit {{
    background: transparent;
    border: none;
    color: {TEXT};
    font-size: 13px;
    selection-background-color: #344D85;
    padding: 2px;
}}
QLabel#composerHint {{ color: {FAINT}; font-size: 9px; }}
QLabel#composerTokens {{ color: {FAINT}; font-size: 9px; }}
QToolButton#modeToggle {{
    background-color: {SURFACE_2};
    border: 1px solid {BORDER};
    border-radius: 7px;
    color: {MUTED};
    font-size: 9px;
    padding: 3px 7px;
}}
QToolButton#modeToggle:hover {{ color: {TEXT}; border-color: {ACCENT}; }}
QToolButton#modeToggle:checked {{
    background-color: {ACCENT_SOFT};
    border-color: {ACCENT};
    color: {TEXT};
}}
QToolButton#modeToggle:disabled {{ color: {FAINT}; }}
QComboBox#modeCombo {{
    background-color: {SURFACE_2};
    border: 1px solid {BORDER};
    border-radius: 7px;
    color: {MUTED};
    font-size: 9px;
    padding: 3px 7px;
}}
QComboBox#modeCombo:hover {{ color: {TEXT}; border-color: {ACCENT}; }}
QComboBox#modeCombo:disabled {{ color: {FAINT}; }}
QFrame#searchSourceBox {{
    background-color: {SURFACE};
    border: 1px solid {BORDER_SOFT};
    border-radius: 9px;
}}
QListWidget#searchSourceList {{
    background-color: {SURFACE_2};
    border: 1px solid {BORDER};
    border-radius: 6px;
    font-size: 10px;
    padding: 2px;
}}
QComboBox#searchSourceType {{
    background-color: {SURFACE_2};
    border: 1px solid {BORDER};
    border-radius: 6px;
    font-size: 10px;
    padding: 3px 6px;
}}
QPushButton#smallButton {{
    background-color: {SURFACE_2};
    border: 1px solid {BORDER};
    border-radius: 6px;
    color: {MUTED};
    font-size: 9px;
    padding: 3px 7px;
}}
QPushButton#smallButton:hover {{ color: {TEXT}; border-color: {ACCENT}; }}
QFrame#reasoningBox {{
    background-color: #101722;
    border: 1px solid #26324A;
    border-radius: 8px;
}}
QPushButton#reasoningToggle {{
    background: transparent;
    border: none;
    color: {MUTED};
    text-align: left;
    font-size: 10px;
    font-weight: 600;
    padding: 1px 2px;
}}
QPushButton#reasoningToggle:hover {{ color: {TEXT}; }}
QPushButton#sendButton {{
    background-color: {ACCENT};
    border: none;
    border-radius: 17px;
    min-width: 34px;
    max-width: 34px;
    min-height: 34px;
    max-height: 34px;
}}
QPushButton#sendButton:hover {{ background-color: {ACCENT_HOVER}; }}
QPushButton#sendButton:disabled {{ background-color: #273145; }}
QPushButton#stopButton {{
    background-color: #39232D;
    border: 1px solid #633244;
    border-radius: 17px;
    min-width: 34px;
    max-width: 34px;
    min-height: 34px;
    max-height: 34px;
}}
QPushButton#stopButton:hover {{ background-color: #4A2A37; }}
QFrame#errorBanner {{
    background-color: #261720;
    border: 1px solid #5A293B;
    border-radius: 10px;
}}
QLabel#errorText {{ color: #FFADB7; font-size: 11px; }}
QPushButton#retryButton {{
    background-color: #3A2230;
    color: #FFC1C9;
    border: 1px solid #633244;
    border-radius: 7px;
    padding: 5px 10px;
    font-size: 10px;
    font-weight: 600;
}}
QPushButton#retryButton:hover {{ background-color: #4A2A3B; }}

QFrame#attachmentChip {{
    background-color: {SURFACE_2};
    border: 1px solid {BORDER};
    border-radius: 8px;
}}
QLabel#attachmentPreview {{
    background-color: #0D131D;
    border-radius: 6px;
}}
QLabel#attachmentName {{
    color: {TEXT};
    font-size: 10px;
}}
QLabel#attachmentMeta {{
    color: {FAINT};
    font-size: 9px;
}}
QLabel#messageImage {{
    background-color: #0D131D;
    border: 1px solid {BORDER};
    border-radius: 8px;
}}
QPushButton#messageFileButton {{
    background-color: {SURFACE_2};
    border: 1px solid {BORDER_SOFT};
    border-radius: 7px;
    color: {MUTED};
    padding: 5px 8px;
    text-align: left;
    font-size: 10px;
}}
QPushButton#messageFileButton:hover {{
    border-color: {BORDER};
    color: {TEXT};
}}
QLabel#emptyTitle {{
    color: {TEXT};
    font-size: 23px;
    font-weight: 700;
}}
QLabel#emptyBody {{
    color: {MUTED};
    font-size: 12px;
}}
QLabel#emptyGlyph {{
    background-color: {ACCENT_SOFT};
    color: #AFC2FF;
    border: 1px solid #31436C;
    border-radius: 26px;
    font-size: 24px;
    font-weight: 800;
}}

/* ---------- dashboard ---------- */
QScrollArea#dashboardScroll {{ background-color: {BG}; border: none; }}
QWidget#dashboardCanvas {{ background-color: {BG}; }}
QWidget#dashboardHeader {{ background-color: {BG}; }}
QLabel#pageTitle {{ font-size: 24px; font-weight: 700; }}
QLabel#pageSubtitle {{ color: {MUTED}; font-size: 11px; }}
QFrame#fontBox {{
    background-color: {SURFACE};
    border: 1px solid {BORDER_SOFT};
    border-radius: 9px;
}}
QLabel#fontLabel {{ color: {FAINT}; font-size: 10px; }}
QLabel#fontValue {{ color: {TEXT}; font-size: 10px; font-weight: 700; min-width: 42px; }}
QToolButton#fontButton {{
    background-color: {SURFACE_2};
    border: 1px solid {BORDER};
    border-radius: 6px;
    color: {MUTED};
    font-size: 13px;
    padding: 0;
}}
QToolButton#fontButton:hover {{ background-color: {SURFACE_3}; color: {TEXT}; }}
QToolButton#fontButton:disabled {{ color: {FAINT}; }}
QFrame#limitBox {{
    background-color: {SURFACE};
    border: 1px solid {BORDER_SOFT};
    border-radius: 9px;
}}
QLabel#limitTitle {{ color: {TEXT}; font-size: 11px; font-weight: 700; }}
QLabel#limitHint {{ color: {FAINT}; font-size: 9px; }}
QSpinBox#limitSpin {{
    min-width: 82px;
    padding: 3px 6px;
    font-size: 10px;
}}
QFrame#kpiCard {{
    background-color: {SURFACE};
    border: 1px solid {BORDER_SOFT};
    border-radius: 13px;
}}
QFrame#kpiCard:hover {{ border-color: {BORDER}; }}
QLabel#kpiLabel {{ color: {MUTED}; font-size: 10px; }}
QLabel#kpiValue {{ color: {TEXT}; font-size: 25px; font-weight: 700; }}
QLabel#kpiHint {{ color: {FAINT}; font-size: 9px; }}
QFrame#card {{
    background-color: {SURFACE};
    border: 1px solid {BORDER_SOFT};
    border-radius: 13px;
}}
QLabel#cardTitle {{ font-size: 13px; font-weight: 700; color: {TEXT}; }}
QLabel#cardHint {{ color: {FAINT}; font-size: 9px; }}
QLabel#cardValue {{ font-size: 14px; font-weight: 700; }}
QTableWidget {{
    background-color: transparent;
    border: none;
    gridline-color: transparent;
    color: {TEXT};
    font-size: 11px;
    selection-background-color: #1C2942;
    selection-color: {TEXT};
    alternate-background-color: #101621;
}}
QTableWidget::item {{
    padding: 7px 8px;
    border: none;
    border-bottom: 1px solid {BORDER_SOFT};
}}
QTableWidget::item:selected {{
    background-color: #1C2942;
    color: {TEXT};
}}
QHeaderView::section {{
    background-color: #0F1520;
    color: {FAINT};
    border: none;
    border-bottom: 1px solid {BORDER};
    padding: 7px 8px;
    font-size: 9px;
    font-weight: 700;
}}
QTableCornerButton::section {{ background-color: #0F1520; border: none; }}

/* ---------- generic controls ---------- */
QLabel#fieldLabel {{ color: {MUTED}; font-size: 11px; }}
QLabel#helperText {{ color: {FAINT}; font-size: 10px; }}
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QPlainTextEdit, QTextEdit {{
    background-color: {SURFACE_2};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 7px 9px;
    color: {TEXT};
    font-size: 12px;
    selection-background-color: #344D85;
}}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus,
QPlainTextEdit:focus, QTextEdit:focus {{
    border-color: #40598C;
    background-color: #1A2332;
}}
QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled, QComboBox:disabled,
QPlainTextEdit:disabled {{
    color: {FAINT};
    background-color: #101620;
}}
QLineEdit[error="true"], QComboBox[error="true"] {{ border-color: #7A3345; }}
QComboBox::drop-down {{ border: none; width: 24px; }}
QComboBox::down-arrow {{
    image: url("{_CHEVRON_DOWN}");
    width: 9px;
    height: 9px;
    margin-right: 9px;
}}
QSpinBox::up-button, QDoubleSpinBox::up-button {{
    subcontrol-origin: border;
    subcontrol-position: top right;
    width: 19px;
    border: none;
    background: transparent;
    margin-top: 2px;
}}
QSpinBox::down-button, QDoubleSpinBox::down-button {{
    subcontrol-origin: border;
    subcontrol-position: bottom right;
    width: 19px;
    border: none;
    background: transparent;
    margin-bottom: 2px;
}}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{
    image: url("{_CHEVRON_UP}");
    width: 8px;
    height: 8px;
}}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{
    image: url("{_CHEVRON_DOWN}");
    width: 8px;
    height: 8px;
}}
QPushButton {{
    background-color: {SURFACE_2};
    color: {TEXT};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 7px 13px;
    font-size: 11px;
}}
QPushButton:hover {{ background-color: {SURFACE_3}; border-color: #34435D; }}
QPushButton:pressed {{ background-color: #111824; }}
QPushButton:disabled {{ color: {FAINT}; background-color: #111721; border-color: {BORDER_SOFT}; }}
QPushButton#primaryButton {{
    background-color: {ACCENT};
    border: 1px solid {ACCENT};
    color: white;
    font-weight: 700;
}}
QPushButton#primaryButton:hover {{ background-color: {ACCENT_HOVER}; }}
QPushButton#primaryButton:disabled {{ background-color: #2A3550; border-color: #2A3550; color: #8D9AB4; }}
QPushButton#dangerButton {{
    background-color: #311B24;
    border: 1px solid #5D2A3A;
    color: #FF9FAC;
}}
QPushButton#dangerButton:hover {{ background-color: #422330; }}
QPushButton#ghostButton {{
    background: transparent;
    border: 1px solid transparent;
    color: {MUTED};
}}
QPushButton#ghostButton:hover {{ background-color: {SURFACE_2}; color: {TEXT}; }}
QCheckBox {{ color: {TEXT}; font-size: 11px; spacing: 8px; }}
QCheckBox::indicator {{
    width: 16px;
    height: 16px;
    border: 1px solid #34435E;
    border-radius: 4px;
    background-color: {SURFACE_2};
}}
QCheckBox::indicator:hover {{ border-color: #4A5F84; }}
QCheckBox::indicator:checked {{
    background-color: {ACCENT};
    border-color: {ACCENT};
    image: url("{_CHECK_MARK}");
}}
QDialog#dialog, QDialog {{
    background-color: #0F141D;
}}
QLabel#dialogTitle {{ font-size: 18px; font-weight: 700; }}
QLabel#dialogSubtitle {{ color: {MUTED}; font-size: 10px; }}
QFrame#dialogHeader {{ border-bottom: 1px solid {BORDER_SOFT}; }}
QFrame#dialogFooter {{ border-top: 1px solid {BORDER_SOFT}; }}
QMenu {{
    background-color: {SURFACE_2};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 5px;
    color: {TEXT};
}}
QMenu::item {{
    padding: 7px 24px 7px 12px;
    border-radius: 5px;
    font-size: 11px;
}}
QMenu::item:selected {{ background-color: {ACCENT_SOFT}; }}
QMenu::separator {{ height: 1px; background-color: {BORDER_SOFT}; margin: 4px 6px; }}
QStatusBar {{ background-color: {SIDEBAR}; color: {FAINT}; border-top: 1px solid {BORDER_SOFT}; }}
QLabel#toast {{
    background-color: #1C2638;
    color: {TEXT};
    border: 1px solid #33435E;
    border-radius: 9px;
    padding: 8px 15px;
    font-size: 11px;
}}
QScrollBar:vertical {{
    background: transparent;
    width: 9px;
    margin: 2px;
}}
QScrollBar::handle:vertical {{
    background: #2A3448;
    min-height: 28px;
    border-radius: 4px;
}}
QScrollBar::handle:vertical:hover {{ background: #3A4862; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
QScrollBar:horizontal {{
    background: transparent;
    height: 9px;
    margin: 2px;
}}
QScrollBar::handle:horizontal {{
    background: #2A3448;
    min-width: 28px;
    border-radius: 4px;
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}
QSplitter::handle {{ background-color: {BORDER_SOFT}; width: 1px; }}
QTabWidget::pane {{ border: none; background: transparent; }}
QTabBar::tab {{
    background: transparent;
    color: {MUTED};
    padding: 8px 12px;
    border-bottom: 2px solid transparent;
    font-size: 11px;
}}
QTabBar::tab:selected {{ color: {TEXT}; border-bottom-color: {ACCENT}; }}
"""


def clamp_font_scale(value: float) -> float:
    return max(MIN_FONT_SCALE, min(MAX_FONT_SCALE, round(float(value), 2)))


def get_font_scale() -> float:
    return _FONT_SCALE


def font_px(value: float) -> int:
    return max(1, int(round(float(value) * _FONT_SCALE)))


_FONT_SIZE_RE = re.compile(r"font-size:\s*([0-9]+(?:\.[0-9]+)?)px")


def _scaled_qss(qss: str) -> str:
    return _FONT_SIZE_RE.sub(
        lambda match: f"font-size: {font_px(float(match.group(1)))}px", qss
    )


def apply_font_scale(app: QApplication, scale: float) -> float:
    """Apply the app-wide font scale to QSS and the ambient Qt font."""
    global _FONT_SCALE
    _FONT_SCALE = clamp_font_scale(scale)
    font = QFont(app.font())
    font.setPointSizeF(10.0 * _FONT_SCALE)
    app.setFont(font)
    app.setStyleSheet(_scaled_qss(QSS))
    return _FONT_SCALE


def apply_theme(app: QApplication) -> None:
    app.setStyle("Fusion")
    font = QFont("Microsoft YaHei UI")
    if not font.exactMatch():
        font = QFont("Microsoft YaHei")
    if not font.exactMatch():
        font = QFont("Segoe UI")
    font.setPointSize(10)
    app.setFont(font)
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(BG))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(TEXT))
    palette.setColor(QPalette.ColorRole.Base, QColor(SURFACE_2))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(SURFACE))
    palette.setColor(QPalette.ColorRole.Text, QColor(TEXT))
    palette.setColor(QPalette.ColorRole.Button, QColor(SURFACE_2))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(TEXT))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(ACCENT))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#FFFFFF"))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(SURFACE_3))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor(TEXT))
    app.setPalette(palette)
    app.setStyleSheet(_scaled_qss(QSS))


def enable_dark_title_bar(widget: QWidget) -> None:
    if sys.platform != "win32":
        return
    try:
        hwnd = int(widget.winId())
        value = ctypes.c_int(1)
        # 20 = DWMWA_USE_IMMERSIVE_DARK_MODE on current Windows 10/11.
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            hwnd, 20, ctypes.byref(value), ctypes.sizeof(value)
        )
    except Exception:
        pass


def humanize_time(value: datetime | None) -> str:
    if value is None:
        return ""
    today = date.today()
    day = value.date()
    if day == today:
        return value.strftime("%H:%M")
    if day == today - timedelta(days=1):
        return "昨天"
    if today - timedelta(days=6) <= day < today:
        names = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
        return names[day.weekday()]
    if day.year == today.year:
        return value.strftime("%m/%d")
    return value.strftime("%Y/%m/%d")


def full_time(value: datetime | None) -> str:
    return value.strftime("%Y-%m-%d %H:%M") if value else ""


def format_int(value: int) -> str:
    return f"{int(value):,}"
