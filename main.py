"""
main.py

Axiom AI application entry point.

Bootstraps the QApplication, installs a global exception handler, and
launches the MainWindow.  Contains zero business logic.
"""

import sys
import traceback
from pathlib import Path

# Ensure the project root is on sys.path so all packages resolve correctly.
sys.path.insert(0, str(Path(__file__).parent))

from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtCore import Qt

from ui.main_window import MainWindow
from core.logger import logger

_DARK_QSS: str = """
/* ── Global Catppuccin Mocha ───────────────────────────────── */
QWidget {
    background-color: #1e1e2e;
    color: #cdd6f4;
    font-size: 11pt;
    font-family: sans-serif;
}

/* ── Main window / frames ───────────────────────────────────── */
QMainWindow, QDialog {
    background-color: #1e1e2e;
}

QLabel {
    background: transparent;
}

QFrame[frameShape="5"],
QFrame[frameShape="4"] {
    background-color: #181825;
    border: 1px solid #313244;
    border-radius: 8px;
}

/* ── Buttons ────────────────────────────────────────────────── */
QPushButton {
    background-color: #313244;
    color: #cdd6f4;
    border: 1px solid #45475a;
    border-radius: 6px;
    padding: 6px 16px;
    min-height: 28px;
}
QPushButton:hover {
    background-color: #45475a;
}
QPushButton:pressed {
    background-color: #585b70;
}
QPushButton:disabled {
    background-color: #181825;
    color: #585b70;
    border: 1px solid #313244;
}

/* ── Text inputs ────────────────────────────────────────────── */
QLineEdit, QTextEdit, QPlainTextEdit {
    background-color: #181825;
    color: #cdd6f4;
    border: 1px solid #313244;
    border-radius: 6px;
    padding: 6px 10px;
    selection-background-color: #585b70;
    font-size: 11pt;
}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus {
    border: 1px solid #89b4fa;
}

/* ── Tabs ───────────────────────────────────────────────────── */
QTabWidget::pane {
    border: 1px solid #313244;
    background-color: #1e1e2e;
}
QTabBar::tab {
    background-color: #181825;
    color: #a6adc8;
    padding: 8px 20px;
    border: 1px solid #313244;
    border-bottom: none;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    margin-right: 2px;
}
QTabBar::tab:selected {
    background-color: #1e1e2e;
    color: #cdd6f4;
    border-bottom: 2px solid #89b4fa;
}
QTabBar::tab:hover:!selected {
    background-color: #313244;
}

/* ── Scroll bars ────────────────────────────────────────────── */
QScrollBar:vertical {
    background: #1e1e2e;
    width: 12px;
    margin: 0;
}
QScrollBar::handle:vertical {
    background: #313244;
    min-height: 30px;
    border-radius: 6px;
}
QScrollBar::handle:vertical:hover {
    background: #45475a;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
}
QScrollBar:horizontal {
    background: #1e1e2e;
    height: 12px;
}
QScrollBar::handle:horizontal {
    background: #313244;
    border-radius: 6px;
}

/* ── Splitter ───────────────────────────────────────────────── */
QSplitter::handle {
    background-color: #313244;
}

/* ── Status bar ─────────────────────────────────────────────── */
QStatusBar {
    background-color: #181825;
    color: #a6adc8;
    border-top: 1px solid #313244;
}

/* ── Menu bar ───────────────────────────────────────────────── */
QMenuBar {
    background-color: #11111b;
    color: #cdd6f4;
}
QMenuBar::item:selected {
    background-color: #313244;
}
QMenu {
    background-color: #181825;
    color: #cdd6f4;
    border: 1px solid #313244;
}
QMenu::item:selected {
    background-color: #313244;
}

/* ── Group boxes ────────────────────────────────────────────── */
QGroupBox {
    border: 1px solid #313244;
    border-radius: 8px;
    margin-top: 16px;
    padding-top: 12px;
    font-weight: bold;
    color: #89b4fa;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 0 8px;
    color: #89b4fa;
}

/* ── Labels ─────────────────────────────────────────────────── */
QLabel {
    color: #cdd6f4;
}

/* ── List / combo widgets ───────────────────────────────────── */
QListWidget, QListView {
    background-color: #181825;
    color: #cdd6f4;
    border: 1px solid #313244;
    border-radius: 8px;
    outline: none;
}
QListWidget::item:selected {
    background-color: #313244;
    color: #89b4fa;
    border-radius: 4px;
}
QComboBox {
    background-color: #181825;
    color: #cdd6f4;
    border: 1px solid #313244;
    border-radius: 6px;
    padding: 6px 12px;
}
QComboBox::drop-down {
    border: none;
}
QComboBox QAbstractItemView {
    background-color: #181825;
    color: #cdd6f4;
    selection-background-color: #313244;
    border: 1px solid #313244;
}

/* ── Spinbox ────────────────────────────────────────────────── */
QSpinBox, QDoubleSpinBox {
    background-color: #181825;
    color: #cdd6f4;
    border: 1px solid #313244;
    border-radius: 6px;
    padding: 4px 8px;
}

/* ── Progress bar ───────────────────────────────────────────── */
QProgressBar {
    background-color: #181825;
    border: 1px solid #313244;
    border-radius: 8px;
    text-align: center;
    color: #cdd6f4;
}
QProgressBar::chunk {
    background-color: #89b4fa;
    border-radius: 6px;
}

/* ── Chat display ───────────────────────────────────────────── */
ChatDisplayWidget QTextEdit {
    border: none;
    background-color: #1e1e2e;
    padding: 12px 16px;
    line-height: 1.6;
}
"""


def _install_exception_hook() -> None:
    """Install a global sys.excepthook to catch unhandled exceptions.

    Any exception that escapes Qt's event loop is:
      1. Written to ~/.cache/AxiomAI/crash_YYYYMMDD_HHMMSS.log with system metadata
      2. Logged to the persistent axiom_ai.log
      3. Shown to the user in a QMessageBox.critical
      4. Exits the application with code 1
    """
    import platform
    from datetime import datetime

    def _hook(exc_type, exc_value, exc_tb):
        now = datetime.now()
        timestamp = now.isoformat()
        file_timestamp = now.strftime("%Y%m%d_%H%M%S")
        crash_log = Path.home() / ".cache" / "Axiom AI" / f"crash_{file_timestamp}.log"
        
        py_ver = sys.version.replace("\n", " ")
        plat = platform.platform()
        
        tb_str = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        
        header = (
            f"Axiom AI Crash Report\n"
            f"==================\n"
            f"Timestamp: {timestamp}\n"
            f"Python:    {py_ver}\n"
            f"Platform:  {plat}\n\n"
            f"Traceback:\n"
        )
        
        report = header + tb_str

        # 1. Log to persistent log
        logger.critical(f"FATAL UNHANDLED EXCEPTION: {exc_value}\n{tb_str}")

        # 2. Write dedicated crash log
        try:
            crash_log.parent.mkdir(parents=True, exist_ok=True)
            crash_log.write_text(report, encoding="utf-8")
        except OSError:
            pass 

        # 3. Show dialog if QApplication exists
        app = QApplication.instance()
        if app is not None:
            QMessageBox.critical(
                None,
                "Axiom AI — Unexpected Error",
                f"<b>An unexpected error occurred:</b><br><br>"
                f"<code>{exc_type.__name__}: {exc_value}</code><br><br>"
                f"A crash log has been saved to:<br>"
                f"<code>{crash_log}</code><br><br>"
                "Please report this issue.",
            )
        sys.exit(1)

    sys.excepthook = _hook


def main() -> None:
    """Application entry point."""
    # Phase 1: Robust Startup Validation
    # We run a quick check of imports and core components before starting Qt.
    from debug.startup_check import run_checks
    try:
        run_checks()
    except SystemExit:
        # startup_check already printed the error and sys.exit(1)
        return
    except Exception as exc:
        print(f"CRITICAL: Startup check failed with an unexpected error: {exc}")
        return

    _install_exception_hook()
    logger.info("Application starting...")

    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setApplicationName("Axiom AI")
    app.setApplicationDisplayName("Axiom AI — AI Role Playing Game")

    # Set Window Icon
    from PySide6.QtGui import QIcon
    icon_path = Path(__file__).parent / "assets" / "icon.svg"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

    app.setStyleSheet(_DARK_QSS)

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
