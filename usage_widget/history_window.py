"""A window with a line chart of your stored usage readings."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from PySide6.QtCharts import QChart, QChartView, QDateTimeAxis, QLineSeries, QValueAxis
from PySide6.QtCore import QDateTime, QMargins, QPointF, Qt
from PySide6.QtGui import QColor, QCursor, QPainter, QPen
from PySide6.QtWidgets import (
    QButtonGroup,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QStackedLayout,
    QToolTip,
    QVBoxLayout,
    QWidget,
)

from .forecast import Reading
from .history import HistoryStore
from .models import DISPLAY_ORDER, label_for

SURFACE = "#191919"
TEXT_PRIMARY = "#efefef"
TEXT_SECONDARY = "#9c9c9c"
GRID = QColor(255, 255, 255, 22)

# Fixed colour per limit, so a limit keeps its colour whichever ones are
# visible. Validated categorical steps for a dark surface.
SERIES_COLORS = ["#338ced", "#e76624", "#00a888", "#d28e05", "#e24d8b", "#0aac23"]

RANGES = [("24 hours", timedelta(hours=24)), ("7 days", timedelta(days=7)), ("30 days", timedelta(days=30))]
MAX_POINTS_PER_SERIES = 2000

STYLE = f"""
QWidget#historyRoot {{ background: {SURFACE}; }}
QLabel {{ color: {TEXT_SECONDARY}; font-family: 'Segoe UI'; font-size: 9pt; }}
QPushButton {{
    color: {TEXT_SECONDARY}; background: transparent; border: 1px solid #3f3f46;
    border-radius: 6px; padding: 4px 12px; font-family: 'Segoe UI'; font-size: 9pt;
}}
QPushButton:checked {{ color: {TEXT_PRIMARY}; background: #27272a; border-color: #71717a; }}
"""


def series_color(key: str, index_fallback: int) -> str:
    if key in DISPLAY_ORDER:
        return SERIES_COLORS[DISPLAY_ORDER.index(key) % len(SERIES_COLORS)]
    return SERIES_COLORS[index_fallback % len(SERIES_COLORS)]


def thin(readings: list[Reading], limit: int = MAX_POINTS_PER_SERIES) -> list[Reading]:
    """Keep long ranges responsive by plotting at most `limit` points."""
    if len(readings) <= limit:
        return readings
    step = len(readings) / limit
    return [readings[int(i * step)] for i in range(limit)] + [readings[-1]]


class HistoryWindow(QWidget):
    def __init__(self, store: HistoryStore):
        super().__init__()
        self._store = store
        self._range = RANGES[0][1]
        self.setObjectName("historyRoot")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.setStyleSheet(STYLE)
        self.setWindowTitle("Claude usage history")
        self.resize(760, 440)

        buttons = QHBoxLayout()
        group = QButtonGroup(self)
        for index, (label, span) in enumerate(RANGES):
            button = QPushButton(label)
            button.setCheckable(True)
            button.setChecked(index == 0)
            button.clicked.connect(lambda _=False, s=span: self._set_range(s))
            group.addButton(button)
            buttons.addWidget(button)
        buttons.addStretch(1)
        hint = QLabel("Hover a line for exact values")
        buttons.addWidget(hint)

        self._chart = QChart()
        self._chart.setBackgroundBrush(QColor(SURFACE))
        self._chart.setPlotAreaBackgroundVisible(False)
        self._chart.setMargins(QMargins(4, 4, 4, 4))
        self._chart.legend().setAlignment(Qt.AlignmentFlag.AlignTop)
        self._chart.legend().setLabelColor(QColor(TEXT_PRIMARY))

        self._view = QChartView(self._chart)
        self._view.setRenderHint(QPainter.RenderHint.Antialiasing)
        self._view.setStyleSheet(f"background: {SURFACE}; border: none;")

        self._empty = QLabel(
            "No history yet. A reading is saved every time the widget refreshes,\n"
            "so the chart fills in while the app runs."
        )
        self._empty.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._stack = QStackedLayout()
        self._stack.addWidget(self._view)
        self._stack.addWidget(self._empty)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.addLayout(buttons)
        layout.addLayout(self._stack, 1)

    def _set_range(self, span: timedelta) -> None:
        self._range = span
        self.reload()

    def reload(self) -> None:
        now = datetime.now(timezone.utc)
        since = now - self._range

        self._chart.removeAllSeries()
        for axis in self._chart.axes():
            self._chart.removeAxis(axis)

        keys = self._store.keys(since)
        keys.sort(key=lambda k: (DISPLAY_ORDER.index(k) if k in DISPLAY_ORDER else len(DISPLAY_ORDER), k))
        if not keys:
            self._stack.setCurrentWidget(self._empty)
            return
        self._stack.setCurrentWidget(self._view)

        x_axis = QDateTimeAxis()
        x_axis.setFormat("HH:mm" if self._range <= timedelta(days=1) else "dd MMM")
        x_axis.setRange(QDateTime.fromSecsSinceEpoch(int(since.timestamp())),
                        QDateTime.fromSecsSinceEpoch(int(now.timestamp())))
        x_axis.setTickCount(8 if self._range == timedelta(days=7) else 7)
        y_axis = QValueAxis()
        y_axis.setRange(0, 100)
        y_axis.setTickCount(6)
        y_axis.setLabelFormat("%.0f%%")
        for axis in (x_axis, y_axis):
            axis.setLabelsColor(QColor(TEXT_SECONDARY))
            axis.setGridLineColor(GRID)
            axis.setLinePen(QPen(GRID))
        self._chart.addAxis(x_axis, Qt.AlignmentFlag.AlignBottom)
        self._chart.addAxis(y_axis, Qt.AlignmentFlag.AlignLeft)

        for index, key in enumerate(keys):
            readings = thin(self._store.readings(key, since=since, until=now))
            series = QLineSeries()
            series.setName(label_for(key))
            series.setPen(QPen(QColor(series_color(key, index)), 2))
            for reading in readings:
                series.append(QPointF(reading.at.timestamp() * 1000, reading.percent))
            series.hovered.connect(
                lambda point, state, name=label_for(key): self._show_tip(name, point, state)
            )
            self._chart.addSeries(series)
            series.attachAxis(x_axis)
            series.attachAxis(y_axis)

    def _show_tip(self, name: str, point: QPointF, state: bool) -> None:
        if not state:
            QToolTip.hideText()
            return
        when = datetime.fromtimestamp(point.x() / 1000).strftime("%a %d %b, %H:%M")
        QToolTip.showText(QCursor.pos(), f"{name}\n{when}: {point.y():.0f}%")

    def showEvent(self, event) -> None:
        self.reload()
        super().showEvent(event)
