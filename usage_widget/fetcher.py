"""Fetches usage numbers through an embedded Chromium page.

Why a browser instead of `requests`: the page signs in to claude.ai exactly
like your normal browser does, keeps its own cookies on disk, and requests
the same JSON the Settings > Usage page loads. So the app never asks you to
copy a session cookie, and there is no secret for us to store.

Flow for one refresh:
    1. If we don't know your organization id yet, load /api/organizations
       and pick your claude.ai org.
    2. Load /api/organizations/<id>/usage and parse it.
    3. If claude.ai answers with an error, we're signed out -> login_required.
"""
from __future__ import annotations

import logging

from PySide6.QtCore import QObject, QSettings, QTimer, QUrl, Signal
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile

from .config import ORGS_API_URL, USAGE_API_URL
from .models import extract_json, is_error_response, parse_usage, pick_org_id
from .web_pages import QuietPage

log = logging.getLogger(__name__)

STAGE_ORGS = "orgs"
STAGE_USAGE = "usage"
REQUEST_TIMEOUT_MS = 45_000
REREAD_DELAY_MS = 3_000
MAX_REREADS = 3


class UsageFetcher(QObject):
    usage_ready = Signal(list)  # list[UsageLimit]
    login_required = Signal()
    failed = Signal(str)

    def __init__(self, profile: QWebEngineProfile, settings: QSettings, parent: QObject | None = None):
        super().__init__(parent)
        self._settings = settings
        self._page = QuietPage(profile, self)
        self._page.loadFinished.connect(self._on_load_finished)

        self._busy = False
        self._stage: str | None = None
        self._generation = 0  # ignores callbacks from an older request
        self._rereads = 0
        self._retried_orgs = False

        self._timeout = QTimer(self)
        self._timeout.setSingleShot(True)
        self._timeout.setInterval(REQUEST_TIMEOUT_MS)
        self._timeout.timeout.connect(self._on_timeout)

    @property
    def busy(self) -> bool:
        return self._busy

    def forget_org(self) -> None:
        self._settings.remove("org_id")

    def refresh(self) -> None:
        if self._busy:
            return
        self._busy = True
        self._retried_orgs = False
        org_id = self._settings.value("org_id", "", type=str)
        if org_id:
            self._load(STAGE_USAGE, USAGE_API_URL.format(org_id=org_id))
        else:
            self._load(STAGE_ORGS, ORGS_API_URL)

    def shutdown(self) -> None:
        self._timeout.stop()
        self._busy = False
        self._page.deleteLater()

    # --- internals -------------------------------------------------------

    def _load(self, stage: str, url: str) -> None:
        self._stage = stage
        self._generation += 1
        self._rereads = 0
        self._timeout.start()
        log.debug("Loading %s (%s)", url, stage)
        self._page.load(QUrl(url))

    def _on_load_finished(self, ok: bool) -> None:
        if not self._busy:
            return
        self._read_page(self._generation)

    def _read_page(self, generation: int) -> None:
        self._page.toPlainText(lambda text: self._on_text(generation, text))

    def _on_text(self, generation: int, text: str) -> None:
        if not self._busy or generation != self._generation:
            return

        data = extract_json(text)
        if data is None:
            # Not JSON yet: usually a "checking your browser" page that
            # finishes on its own and then loads the real response.
            if self._rereads < MAX_REREADS:
                self._rereads += 1
                QTimer.singleShot(REREAD_DELAY_MS, lambda: self._read_page(generation))
            return

        if self._stage == STAGE_ORGS:
            self._handle_orgs(data)
        else:
            self._handle_usage(data)

    def _handle_orgs(self, data) -> None:
        if is_error_response(data):
            log.info("Organizations request returned an error; sign-in needed")
            self._finish()
            self.login_required.emit()
            return
        org_id = pick_org_id(data)
        if not org_id:
            self._fail("No Claude organization found on this account")
            return
        self._settings.setValue("org_id", org_id)
        self._load(STAGE_USAGE, USAGE_API_URL.format(org_id=org_id))

    def _handle_usage(self, data) -> None:
        if is_error_response(data):
            if not self._retried_orgs:
                # The saved org may be stale (for example a different account
                # signed in). Look it up again once before giving up.
                self._retried_orgs = True
                self.forget_org()
                self._load(STAGE_ORGS, ORGS_API_URL)
                return
            self._finish()
            self.login_required.emit()
            return
        try:
            limits = parse_usage(data)
        except ValueError as exc:
            self._fail(str(exc))
            return
        self._finish()
        self.usage_ready.emit(limits)

    def _on_timeout(self) -> None:
        if self._busy:
            self._page.triggerAction(QWebEnginePage.WebAction.Stop)
            self._fail("claude.ai took too long to respond")

    def _fail(self, message: str) -> None:
        log.warning("Refresh failed: %s", message)
        self._finish()
        self.failed.emit(message)

    def _finish(self) -> None:
        self._timeout.stop()
        self._busy = False
        self._generation += 1
