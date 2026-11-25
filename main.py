"""Entry point: python main.py (or pythonw main.py for no console window)."""
from __future__ import annotations

import logging
import signal
import sys

from PySide6.QtCore import QCoreApplication, QDir, QLockFile, Qt, QTimer
from PySide6.QtWidgets import QApplication, QMessageBox, QSystemTrayIcon

# QtWebEngine must be imported before the QApplication is created,
# and usage_widget.app imports it.
from usage_widget.app import UsageApp
from usage_widget.config import APP_NAME, ORG_NAME, data_dir, load_config


def setup_logging() -> None:
    logging.basicConfig(
        filename=str(data_dir() / "app.log"),
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def main() -> int:
    setup_logging()
    QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    qapp = QApplication(sys.argv)
    qapp.setApplicationName(APP_NAME)
    qapp.setOrganizationName(ORG_NAME)
    qapp.setQuitOnLastWindowClosed(False)  # closing the login window mustn't quit

    # Only one copy should run, otherwise you'd get two tray icons.
    lock = QLockFile(QDir.tempPath() + "/claude-usage-widget.lock")
    if not lock.tryLock(100):
        logging.info("Another instance is already running; exiting")
        return 0

    if not QSystemTrayIcon.isSystemTrayAvailable():
        QMessageBox.critical(None, "Claude usage", "No system tray is available on this system.")
        return 1

    app = UsageApp(qapp, load_config())

    # Make Ctrl+C in the terminal quit cleanly. Qt's event loop doesn't let
    # Python notice the signal on its own, so a timer wakes Python up regularly.
    signal.signal(signal.SIGINT, lambda *_: app.quit())
    wake_timer = QTimer()
    wake_timer.timeout.connect(lambda: None)
    wake_timer.start(250)

    app.start()
    logging.info("Started")
    exit_code = qapp.exec()
    lock.unlock()
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
