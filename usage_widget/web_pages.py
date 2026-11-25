"""Browser page classes shared by the login window and the fetcher.

QuietPage sends the website's own console messages to the log file instead
of the terminal. PopupPage also lets the site open pop-up windows, which
"Continue with Google" needs: without it, QtWebEngine silently drops the
pop-up and the button appears to do nothing.
"""
from __future__ import annotations

import logging

from PySide6.QtCore import Qt
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QVBoxLayout, QWidget

log = logging.getLogger("claude.page")


class QuietPage(QWebEnginePage):
    def javaScriptConsoleMessage(self, level, message, line_number, source_id) -> None:
        log.debug("js: %s (%s:%s)", message, source_id, line_number)


class PopupPage(QuietPage):
    def __init__(self, profile: QWebEngineProfile, parent=None):
        super().__init__(profile, parent)
        self._popups: list[PopupWindow] = []

    def createWindow(self, window_type) -> QWebEnginePage:
        popup = PopupWindow(self.profile())
        self._popups.append(popup)
        popup.destroyed.connect(lambda: self._forget(popup))
        popup.show()
        return popup.page

    def _forget(self, popup: "PopupWindow") -> None:
        if popup in self._popups:
            self._popups.remove(popup)


class PopupWindow(QWidget):
    """A plain browser window for pop-ups such as Google's account chooser.

    It shares the login window's profile, so whatever it signs in to is
    visible to the rest of the app. The site closes it when it's done.
    """

    def __init__(self, profile: QWebEngineProfile):
        super().__init__()
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setWindowTitle("Sign in")
        self.resize(480, 640)

        self._view = QWebEngineView(self)
        self.page = PopupPage(profile, self._view)
        self._view.setPage(self.page)
        self.page.windowCloseRequested.connect(self.close)
        self.page.titleChanged.connect(lambda title: self.setWindowTitle(title or "Sign in"))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._view)
