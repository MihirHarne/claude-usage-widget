"""A small browser window for signing in to claude.ai once.

It shares the app's persistent browser profile with the fetcher, so after
you sign in here the fetcher is signed in too, and stays signed in across
restarts until claude.ai logs the session out.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, QUrl, Signal
from PySide6.QtWebEngineCore import QWebEngineProfile
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from .config import LOGIN_URL
from .models import is_logged_in_url
from .web_pages import PopupPage


class LoginWindow(QWidget):
    logged_in = Signal()

    def __init__(self, profile: QWebEngineProfile):
        super().__init__()
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setWindowTitle("Sign in to Claude — Usage Widget")
        self.resize(500, 760)
        self._finished = False

        hint = QLabel(
            "Sign in to claude.ai below. Google sign-in opens in a pop-up window; if "
            "Google says this browser isn't supported, use <b>Continue with email</b> "
            "instead. This window closes by itself once you're in."
        )
        hint.setWordWrap(True)

        self._view = QWebEngineView(self)
        self._page = PopupPage(profile, self._view)
        self._view.setPage(self._page)
        self._page.urlChanged.connect(self._on_url_changed)

        done_button = QPushButton("I've signed in")
        done_button.clicked.connect(self._finish)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(done_button)

        layout = QVBoxLayout(self)
        layout.addWidget(hint)
        layout.addWidget(self._view, 1)
        layout.addLayout(buttons)

        self._page.load(QUrl(LOGIN_URL))

    def _on_url_changed(self, url: QUrl) -> None:
        if is_logged_in_url(url.toString()):
            # Give the site a moment to finish writing its session cookies.
            QTimer.singleShot(1500, self._finish)

    def _finish(self) -> None:
        if self._finished:
            return
        self._finished = True
        self.logged_in.emit()
        self.close()
