"""The floating desktop panel with one progress bar per limit."""
from __future__ import annotations

from datetime import datetime
from typing import Callable, Optional

from PySide6.QtCore import QPoint, QRectF, QSettings, Qt
from PySide6.QtGui import QColor, QGuiApplication, QMouseEvent, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMenu,
    QProgressBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .icons import level_color
from .models import UsageLimit, format_countdown, format_percent

WIDTH = 290
PANEL_COLOR = QColor(24, 24, 27, 235)
BORDER_COLOR = QColor(255, 255, 255, 28)

STYLE = """
QLabel { color: #e4e4e7; font-family: 'Segoe UI'; }
QLabel#title { font-size: 13px; font-weight: 600; }
QLabel#limitName { font-size: 12px; }
QLabel#limitPercent { font-size: 12px; font-weight: 600; }
QLabel#reset, QLabel#status { color: #a1a1aa; font-size: 11px; }
QToolButton { color: #a1a1aa; background: transparent; border: none; font-size: 14px; padding: 0 4px; }
QToolButton:hover { color: #ffffff; }
"""

BAR_STYLE = """
QProgressBar {{ background: rgba(255, 255, 255, 30); border: none; border-radius: 3px; }}
QProgressBar::chunk {{ background: {color}; border-radius: 3px; }}
"""


class DesktopWidget(QWidget):
    def __init__(
        self,
        menu: QMenu,
        settings: QSettings,
        on_refresh: Callable[[], None],
        level_of: Callable[[float], str],
    ):
        super().__init__()
        self._menu = menu
        self._settings = settings
        self._level_of = level_of
        self._drag_offset: Optional[QPoint] = None
        self._limits: list[UsageLimit] = []

        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedWidth(WIDTH)
        self.setStyleSheet(STYLE)
        self.apply_on_top(settings.value("on_top", True, type=bool), show=False)

        title = QLabel("Claude usage")
        title.setObjectName("title")
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

    def set_limits(self, limits: list[UsageLimit], updated_at: datetime) -> None:
        self._limits = limits
        self._render_rows()
        if limits:
            self.set_status(f"Updated {updated_at.strftime('%H:%M')}")
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

        for limit in self._limits:
            self._rows.addWidget(self._make_row(limit))
        self.adjustSize()

    def _make_row(self, limit: UsageLimit) -> QWidget:
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

        bar = QProgressBar()
        bar.setRange(0, 1000)
        bar.setValue(int(limit.percent * 10))
        bar.setTextVisible(False)
        bar.setFixedHeight(6)
        bar.setStyleSheet(BAR_STYLE.format(color=color))

        row = QWidget()
        column = QVBoxLayout(row)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(4)
        column.addLayout(top)
        column.addWidget(bar)

        countdown = format_countdown(limit.resets_at)
        if countdown:
            reset = QLabel(countdown)
            reset.setObjectName("reset")
            column.addWidget(reset)
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
