"""The floating desktop panel with one bar per limit.

Each bar shows how much of the limit you've used, plus a thin white tick
showing how much of the window's *time* has passed. If the coloured fill is
past the tick, you're using the limit faster than time is passing.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable, Optional

from PySide6.QtCore import QPoint, QRectF, QSettings, QSize, Qt
from PySide6.QtGui import QColor, QGuiApplication, QMouseEvent, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMenu,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .forecast import Forecast, describe, pace_text
from .icons import level_color
from .models import UsageLimit, format_countdown, format_percent

WIDTH = 290
PANEL_COLOR = QColor(24, 24, 27, 235)
BORDER_COLOR = QColor(255, 255, 255, 28)
TRACK_COLOR = QColor(255, 255, 255, 30)
TICK_COLOR = QColor(255, 255, 255, 220)
WARN_TEXT = "#fbbf24"

STYLE = """
QLabel { color: #e4e4e7; font-family: 'Segoe UI'; }
QLabel#title { font-size: 10pt; font-weight: 600; }
QLabel#limitName { font-size: 9pt; }
QLabel#limitPercent { font-size: 9pt; font-weight: 600; }
QLabel#reset, QLabel#status { color: #a1a1aa; font-size: 8pt; }
QToolButton { color: #a1a1aa; background: transparent; border: none; font-size: 11pt; padding: 0 4px; }
QToolButton:hover { color: #ffffff; }
"""


class UsageBar(QWidget):
    """A thin progress bar with an optional "time elapsed" tick."""

    HEIGHT = 10
    TRACK_HEIGHT = 6

    def __init__(self, percent: float, color: str, elapsed_percent: Optional[float]):
        super().__init__()
        self._percent = percent
        self._color = QColor(color)
        self._elapsed = elapsed_percent
        self.setFixedHeight(self.HEIGHT)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def sizeHint(self) -> QSize:
        return QSize(200, self.HEIGHT)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        width = self.width()
        top = (self.HEIGHT - self.TRACK_HEIGHT) / 2
        radius = self.TRACK_HEIGHT / 2

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(TRACK_COLOR)
        painter.drawRoundedRect(QRectF(0, top, width, self.TRACK_HEIGHT), radius, radius)

        fill_width = width * self._percent / 100
        if fill_width > 0:
            painter.setBrush(self._color)
            painter.drawRoundedRect(
                QRectF(0, top, max(fill_width, self.TRACK_HEIGHT), self.TRACK_HEIGHT), radius, radius
            )

        if self._elapsed is not None:
            x = min(max(width * self._elapsed / 100, 1), width - 1)
            painter.setPen(QPen(TICK_COLOR, 2))
            painter.drawLine(QPoint(round(x), 0), QPoint(round(x), self.HEIGHT))


class DesktopWidget(QWidget):
    def __init__(
        self,
        menu: QMenu,
        settings: QSettings,
        on_refresh: Callable[[], None],
        on_history: Callable[[], None],
        level_of: Callable[[float], str],
    ):
        super().__init__()
        self._menu = menu
        self._settings = settings
        self._level_of = level_of
        self._drag_offset: Optional[QPoint] = None
        self._limits: list[UsageLimit] = []
        self._forecasts: dict[str, Forecast] = {}

        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedWidth(WIDTH)
        self.setStyleSheet(STYLE)
        self.apply_on_top(settings.value("on_top", True, type=bool), show=False)

        title = QLabel("Claude usage")
        title.setObjectName("title")
        history_button = QToolButton()
        history_button.setText("📈")
        history_button.setToolTip("Usage history")
        history_button.clicked.connect(on_history)
        refresh_button = QToolButton()
        refresh_button.setText("↻")
        refresh_button.setToolTip("Refresh now")
        refresh_button.clicked.connect(on_refresh)
        hide_button = QToolButton()
        hide_button.setText("–")
        hide_button.setToolTip("Hide (click the tray icon to show again)")
        hide_button.clicked.connect(self.hide)

        header = QHBoxLayout()
        header.addWidget(title)
        header.addStretch(1)
        header.addWidget(history_button)
        header.addWidget(refresh_button)
        header.addWidget(hide_button)

        self._rows = QVBoxLayout()
        self._rows.setSpacing(10)

        self._status = QLabel("Loading…")
        self._status.setObjectName("status")
        self._status.setWordWrap(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(10)
        layout.addLayout(header)
        layout.addLayout(self._rows)
        layout.addWidget(self._status)

        self._restore_position()

    # --- public API used by the app --------------------------------------

    def set_limits(
        self, limits: list[UsageLimit], forecasts: dict[str, Forecast], updated_at: datetime
    ) -> None:
        self._limits = limits
        self._forecasts = forecasts
        self._render_rows()
        if limits:
            self.set_status(f"Updated {updated_at.strftime('%H:%M')} · tick = time elapsed")
        else:
            self.set_status("claude.ai reported no limits for this account.")

    def refresh_countdowns(self) -> None:
        """Re-draw the reset timers without fetching new data."""
        if self._limits:
            self._render_rows()

    def set_status(self, text: str) -> None:
        self._status.setText(text)
        self.adjustSize()

    def apply_on_top(self, on_top: bool, show: bool = True) -> None:
        flags = Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool
        if on_top:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        was_visible = self.isVisible()
        self.setWindowFlags(flags)
        if show and was_visible:
            self.show()

    # --- drawing ---------------------------------------------------------

    def _render_rows(self) -> None:
        while self._rows.count():
            item = self._rows.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        now = datetime.now(timezone.utc)
        for limit in self._limits:
            self._rows.addWidget(self._make_row(limit, self._forecasts.get(limit.key), now))
        self.adjustSize()

    def _make_row(self, limit: UsageLimit, forecast: Optional[Forecast], now: datetime) -> QWidget:
        color = level_color(self._level_of(limit.percent))

        name = QLabel(limit.label)
        name.setObjectName("limitName")
        percent = QLabel(format_percent(limit.percent))
        percent.setObjectName("limitPercent")
        percent.setStyleSheet(f"color: {color};")

        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.addWidget(name)
        top.addStretch(1)
        top.addWidget(percent)

        bar = UsageBar(limit.percent, color, forecast.elapsed_percent if forecast else None)
        bar.setToolTip(pace_text(forecast))

        row = QWidget()
        column = QVBoxLayout(row)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(3)
        column.addLayout(top)
        column.addWidget(bar)

        parts = [format_countdown(limit.resets_at, now), describe(forecast, now)]
        detail_text = " · ".join(part for part in parts if part)
        if detail_text:
            detail = QLabel(detail_text)
            detail.setObjectName("reset")
            if forecast is not None and forecast.hits_limit_at is not None:
                detail.setStyleSheet(f"color: {WARN_TEXT};")
            column.addWidget(detail)
        return row

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 12, 12)
        painter.fillPath(path, PANEL_COLOR)
        painter.setPen(QPen(BORDER_COLOR, 1))
        painter.drawPath(path)

    # --- dragging and right-click ----------------------------------------

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drag_offset is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if self._drag_offset is not None:
            self._drag_offset = None
            self._settings.setValue("widget_pos", self.pos())

    def contextMenuEvent(self, event) -> None:
        self._menu.exec(event.globalPos())

    def _restore_position(self) -> None:
        saved = self._settings.value("widget_pos")
        if isinstance(saved, QPoint) and QGuiApplication.screenAt(saved) is not None:
            self.move(saved)
            return
        screen = QGuiApplication.primaryScreen()
        if screen is not None:
            area = screen.availableGeometry()
            self.move(area.right() - WIDTH - 24, area.top() + 24)
