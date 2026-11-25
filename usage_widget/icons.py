"""Draws the tray icon: a coloured rounded square with the percentage in it."""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap

from .models import LEVEL_CRITICAL, LEVEL_OK, LEVEL_WARN

LEVEL_COLORS = {
    LEVEL_OK: "#16a34a",
    LEVEL_WARN: "#d97706",
    LEVEL_CRITICAL: "#dc2626",
}
UNKNOWN_COLOR = "#52525b"
ICON_SIZE = 64


def level_color(level: Optional[str]) -> str:
    return LEVEL_COLORS.get(level or "", UNKNOWN_COLOR)


def render_icon(percent: Optional[float], level: Optional[str]) -> QIcon:
    pixmap = QPixmap(ICON_SIZE, ICON_SIZE)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)

    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(level_color(level) if percent is not None else UNKNOWN_COLOR))
    painter.drawRoundedRect(QRectF(0, 0, ICON_SIZE, ICON_SIZE), 14, 14)

    text = "–" if percent is None else str(round(percent))
    font = QFont()
    font.setFamily("Segoe UI")
    font.setBold(True)
    # Three digits ("100") need a smaller font to fit in the square.
    font.setPixelSize(30 if len(text) >= 3 else 40)
    painter.setFont(font)
    painter.setPen(QColor("white"))
    painter.drawText(QRectF(0, 0, ICON_SIZE, ICON_SIZE), Qt.AlignmentFlag.AlignCenter, text)
    painter.end()

    return QIcon(pixmap)
