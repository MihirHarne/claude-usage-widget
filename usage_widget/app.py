"""Wires the fetcher, tray icon, desktop widget and login window together."""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from PySide6.QtCore import QObject, QSettings, QTimer, QUrl
from PySide6.QtGui import QAction, QDesktopServices
from PySide6.QtWebEngineCore import QWebEngineProfile
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from . import autostart
from .config import APP_NAME, ORG_NAME, USAGE_PAGE_URL, Config
from .desktop_widget import DesktopWidget
from .fetcher import UsageFetcher
from .icons import render_icon
from .login_window import LoginWindow
from .models import (
    LEVEL_RANK,
    UsageLimit,
    format_countdown,
    format_percent,
    level_for,
    pick_tray_limit,
    tooltip_text,
)

log = logging.getLogger(__name__)

COUNTDOWN_TICK_MS = 30_000
RETRY_AFTER_FAILURE_MS = 60_000


class UsageApp(QObject):
    def __init__(self, qapp: QApplication, config: Config):
        super().__init__()
        self._qapp = qapp
        self._config = config
        self._settings = QSettings(ORG_NAME, APP_NAME)
        self._limits: list[UsageLimit] = []
        self._notified_levels: dict[str, str] = {}
        self._login_window: Optional[LoginWindow] = None
        self._login_prompted = False

        # A named profile stores cookies on disk, so you stay signed in.
        self._profile = QWebEngineProfile("claude-usage-widget", self)
        self._profile.setPersistentCookiesPolicy(
            QWebEngineProfile.PersistentCookiesPolicy.ForcePersistentCookies
        )

        self._fetcher = UsageFetcher(self._profile, self._settings, self)
        self._fetcher.usage_ready.connect(self._on_usage)
        self._fetcher.login_required.connect(self._on_login_required)
        self._fetcher.failed.connect(self._on_failed)

        self._menu = self._build_menu()

        self._tray = QSystemTrayIcon(render_icon(None, None), self)
        self._tray.setToolTip("Claude usage — loading…")
        self._tray.setContextMenu(self._menu)
        self._tray.activated.connect(self._on_tray_activated)

        self._widget = DesktopWidget(
            menu=self._menu,
            settings=self._settings,
            on_refresh=self.refresh,
            level_of=self._level_of,
        )
        self._widget.setWindowIcon(render_icon(None, None))

        self._refresh_timer = QTimer(self)
        self._refresh_timer.setInterval(config.refresh_seconds * 1000)
        self._refresh_timer.timeout.connect(self.refresh)

        self._tick_timer = QTimer(self)
        self._tick_timer.setInterval(COUNTDOWN_TICK_MS)
        self._tick_timer.timeout.connect(self._on_tick)

    # --- lifecycle -------------------------------------------------------

    def start(self) -> None:
        self._tray.show()
        if self._settings.value("widget_visible", True, type=bool):
            self._widget.show()
        self._refresh_timer.start()
        self._tick_timer.start()
        self.refresh()

    def refresh(self) -> None:
        if self._login_window is not None:
            return  # wait until the user finishes signing in
        if not self._fetcher.busy:
            self._widget.set_status("Refreshing…")
        self._fetcher.refresh()

    def quit(self) -> None:
        self._refresh_timer.stop()
        self._tick_timer.stop()
        if self._login_window is not None:
            self._login_window.close()
        self._fetcher.shutdown()
        self._tray.hide()
        # Let Qt delete the web pages before the profile goes away.
        QTimer.singleShot(0, self._qapp.quit)

    # --- menu ------------------------------------------------------------

    def _build_menu(self) -> QMenu:
        menu = QMenu()

        self._toggle_widget_action = QAction("Show / hide widget", menu)
        self._toggle_widget_action.triggered.connect(self._toggle_widget)
        menu.addAction(self._toggle_widget_action)

        refresh_action = QAction("Refresh now", menu)
        refresh_action.triggered.connect(self.refresh)
        menu.addAction(refresh_action)

        open_page_action = QAction("Open usage page on claude.ai", menu)
        open_page_action.triggered.connect(lambda: QDesktopServices.openUrl(QUrl(USAGE_PAGE_URL)))
        menu.addAction(open_page_action)

        menu.addSeparator()

        on_top_action = QAction("Keep widget on top", menu)
        on_top_action.setCheckable(True)
        on_top_action.setChecked(self._settings.value("on_top", True, type=bool))
        on_top_action.toggled.connect(self._set_on_top)
        menu.addAction(on_top_action)

        if autostart.is_supported():
            autostart_action = QAction("Start with Windows", menu)
            autostart_action.setCheckable(True)
            autostart_action.setChecked(autostart.is_enabled())
            autostart_action.toggled.connect(self._set_autostart)
            menu.addAction(autostart_action)

        sign_in_action = QAction("Sign in again…", menu)
        sign_in_action.triggered.connect(self._open_login)
        menu.addAction(sign_in_action)

        menu.addSeparator()

        quit_action = QAction("Quit", menu)
        quit_action.triggered.connect(self.quit)
        menu.addAction(quit_action)
        return menu

    def _toggle_widget(self) -> None:
        visible = not self._widget.isVisible()
        self._widget.setVisible(visible)
        if visible:
            self._widget.raise_()
        self._settings.setValue("widget_visible", visible)

    def _set_on_top(self, on_top: bool) -> None:
        self._settings.setValue("on_top", on_top)
        self._widget.apply_on_top(on_top)

    def _set_autostart(self, enabled: bool) -> None:
        try:
            autostart.set_enabled(enabled)
        except OSError as exc:
            log.error("Could not change autostart: %s", exc)
            self._tray.showMessage("Claude usage", "Couldn't change the startup setting.")

    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.Trigger:  # left click
            self._toggle_widget()

    # --- fetcher results -------------------------------------------------

    def _on_usage(self, limits: list) -> None:
        self._limits = limits
        self._login_prompted = False
        self._widget.set_limits(limits, datetime.now())
        self._update_tray()
        self._notify_if_needed(limits)
        # Back to the normal interval (a failure shortens it to retry sooner).
        self._refresh_timer.start(self._config.refresh_seconds * 1000)

    def _on_login_required(self) -> None:
        self._widget.set_status("Sign-in needed — right-click → Sign in again…")
        self._tray.setIcon(render_icon(None, None))
        self._tray.setToolTip("Claude usage — sign-in needed")
        # Open the sign-in window automatically once, not on every refresh.
        if not self._login_prompted:
            self._login_prompted = True
            self._open_login()

    def _on_failed(self, message: str) -> None:
        if self._limits:
            self._widget.set_status(f"Couldn't refresh ({message}). Showing last values.")
        else:
            self._widget.set_status(f"Couldn't refresh: {message}")
        self._refresh_timer.start(RETRY_AFTER_FAILURE_MS)

    # --- sign-in ---------------------------------------------------------

    def _open_login(self) -> None:
        if self._login_window is not None:
            self._login_window.raise_()
            self._login_window.activateWindow()
            return
        self._login_window = LoginWindow(self._profile)
        self._login_window.logged_in.connect(self._on_logged_in)
        self._login_window.destroyed.connect(self._on_login_closed)
        self._login_window.show()

    def _on_login_closed(self) -> None:
        self._login_window = None

    def _on_logged_in(self) -> None:
        self._fetcher.forget_org()
        # The window is closing; refresh just after it's gone.
        QTimer.singleShot(500, self.refresh)

    # --- display helpers -------------------------------------------------

    def _level_of(self, percent: float) -> str:
        return level_for(percent, self._config.warn_percent, self._config.critical_percent)

    def _update_tray(self) -> None:
        tray_limit = pick_tray_limit(self._limits, self._config.tray_metric)
        if tray_limit is None:
            self._tray.setIcon(render_icon(None, None))
        else:
            self._tray.setIcon(render_icon(tray_limit.percent, self._level_of(tray_limit.percent)))
        self._tray.setToolTip(tooltip_text(self._limits))

    def _on_tick(self) -> None:
        self._widget.refresh_countdowns()
        if self._limits:
            self._tray.setToolTip(tooltip_text(self._limits))

    def _notify_if_needed(self, limits: list[UsageLimit]) -> None:
        for limit in limits:
            level = self._level_of(limit.percent)
            previous = self._notified_levels.get(limit.key, "ok")
            self._notified_levels[limit.key] = level
            if not self._config.notifications:
                continue
            if LEVEL_RANK[level] > LEVEL_RANK[previous]:
                icon = (
                    QSystemTrayIcon.MessageIcon.Critical
                    if level == "critical"
                    else QSystemTrayIcon.MessageIcon.Warning
                )
                body = format_countdown(limit.resets_at) or "Check claude.ai for details."
                self._tray.showMessage(
                    f"{limit.label} at {format_percent(limit.percent)}", body, icon, 8000
                )
