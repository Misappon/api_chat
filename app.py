"""API Chat application entry point."""

from __future__ import annotations

import ctypes
import faulthandler
import io
import logging
import os
import sys
import threading
import time
import traceback
from logging.handlers import RotatingFileHandler
from pathlib import Path

# Keep the 2D UI on the software raster path. On a few Windows 11 + virtual
# display/GPU driver combinations Qt's D3D initialization can interact badly
# with the shell compositor. These flags must be set before importing Qt.
_SOFTWARE_RENDERING = os.environ.get("QT_OPENGL", "").lower() != "desktop"
if _SOFTWARE_RENDERING:
    os.environ.setdefault("QT_OPENGL", "software")
    os.environ.setdefault("QT_QUICK_BACKEND", "software")
    os.environ.setdefault("QSG_RHI_BACKEND", "software")

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QMessageBox

from apichat import __version__
from apichat.config import Config, app_data_dir
from apichat.db import Database, DatabaseError
from apichat.repository import Repository
from apichat.ui.database_dialog import DatabaseDialog
from apichat.ui.icons import icon
from apichat.ui.main_window import MainWindow
from apichat.ui.theme import apply_theme

LOG = logging.getLogger("apichat")
_CRASH_FILE = None


class _UiWatchdog(threading.Thread):
    """Log a stack dump when the Qt event loop stops responding."""

    def __init__(self) -> None:
        super().__init__(name="apichat-ui-watchdog", daemon=True)
        self._last_beat = time.monotonic()
        self._main_ident = threading.main_thread().ident
        self._warned = False

    def beat(self) -> None:
        self._last_beat = time.monotonic()
        self._warned = False

    def run(self) -> None:
        while True:
            time.sleep(1.0)
            blocked = time.monotonic() - self._last_beat
            if blocked < 10.0 or self._warned:
                continue
            self._warned = True
            frame = sys._current_frames().get(self._main_ident)
            output = io.StringIO()
            if frame is not None:
                traceback.print_stack(frame, file=output)
            LOG.warning("UI thread blocked for %.1fs\n%s", blocked, output.getvalue())


def setup_logging() -> None:
    try:
        handler = RotatingFileHandler(
            app_data_dir() / "app.log",
            maxBytes=1_000_000,
            backupCount=2,
            encoding="utf-8",
        )
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
        )
        logging.basicConfig(level=logging.INFO, handlers=[handler])
        # Query strings can contain private search text; never log HTTP URLs.
        logging.getLogger("httpx").setLevel(logging.WARNING)
        logging.getLogger("httpcore").setLevel(logging.WARNING)
    except Exception:
        logging.basicConfig(level=logging.INFO)


def install_exception_hook(app: QApplication) -> None:
    def handle(exc_type, exc_value, exc_tb):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return
        text = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        LOG.error("Unhandled exception:\n%s", text)
        try:
            QMessageBox.critical(
                None,
                "API Chat 遇到问题",
                "程序遇到一个未处理的错误。详细信息已写入日志：\n"
                f"{app_data_dir() / 'app.log'}\n\n{exc_value}",
            )
        except Exception:
            pass

    sys.excepthook = handle


def connect_with_dialog(config: Config) -> Database | None:
    while True:
        try:
            return Database(config.database).connect()
        except DatabaseError as exc:
            box = QMessageBox()
            box.setIcon(QMessageBox.Icon.Critical)
            box.setWindowTitle("无法连接 MySQL")
            box.setText("API Chat 无法连接本地 MySQL 数据库。")
            box.setInformativeText(f"{exc}\n\n是否打开数据库设置？")
            box.setStandardButtons(
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            box.setDefaultButton(QMessageBox.StandardButton.Yes)
            if box.exec() != QMessageBox.StandardButton.Yes:
                return None
            dialog = DatabaseDialog(config.database)
            if dialog.exec() != DatabaseDialog.DialogCode.Accepted:
                return None
            if dialog.result_config:
                config.database = dialog.result_config
                config.save()


def main() -> int:
    global _CRASH_FILE
    setup_logging()
    try:
        _CRASH_FILE = open(
            app_data_dir() / "crash.log", "a", buffering=1, encoding="utf-8"
        )
        faulthandler.enable(file=_CRASH_FILE, all_threads=True)
    except Exception:
        _CRASH_FILE = None
    if sys.platform == "win32":
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                "APIChat.LocalLLMDesk.1"
            )
        except Exception:
            pass

    if _SOFTWARE_RENDERING:
        try:
            QApplication.setAttribute(Qt.ApplicationAttribute.AA_UseSoftwareOpenGL, True)
        except Exception:
            pass
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(sys.argv)
    watchdog = _UiWatchdog()
    watchdog.start()
    heartbeat = QTimer()
    heartbeat.setInterval(500)
    heartbeat.timeout.connect(watchdog.beat)
    heartbeat.start()
    app.setApplicationName("API Chat")
    app.setApplicationDisplayName("API Chat")
    app.setOrganizationName("APIChat")
    app.setApplicationVersion(__version__)
    apply_theme(app)
    asset_root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    icon_path = asset_root / "assets" / "icon.ico"
    app_icon = QIcon(str(icon_path)) if icon_path.exists() else icon("chat", "#FFFFFF", 64)
    app.setWindowIcon(app_icon)
    install_exception_hook(app)

    config = Config()
    database = connect_with_dialog(config)
    if database is None:
        return 1
    repository = Repository(database)
    try:
        window = MainWindow(config, database, repository)
    except Exception:
        LOG.exception("Failed to create main window")
        QMessageBox.critical(
            None,
            "启动失败",
            "主窗口创建失败，详细信息已写入日志。\n"
            f"{app_data_dir() / 'app.log'}",
        )
        database.close()
        return 1
    window.show()
    code = app.exec()
    try:
        database.close()
    except Exception:
        pass
    return int(code)


if __name__ == "__main__":
    raise SystemExit(main())
