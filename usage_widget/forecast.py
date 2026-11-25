"""Pace and "when will I hit the limit" forecasting. Pure logic, unit tested.

Each limit is a rolling window: 5 hours for the session, 7 days for the
weekly limits. claude.ai tells us when the window resets, so we know how far
through the window we are. Two questions follow:

Pace:     have I used more of the limit than of the time? Using 60% of the
          limit when only 40% of the window has passed means you're ahead of
          pace and likely to run out early.

Forecast: at my current rate, when does usage reach 100%? We fit a straight
          line (least squares) through the recent readings in this window.
          With too few readings we fall back to the average rate since the
          window started (usage so far divided by time elapsed).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional, Sequence

from .models import UsageLimit

WINDOW_HOURS = {
    "five_hour": 5.0,
    "seven_day": 168.0,
    "seven_day_sonnet": 168.0,
    "seven_day_opus": 168.0,
}
# How far back the trend line looks, per window length.
TREND_LOOKBACK_HOURS = {5.0: 1.0, 168.0: 24.0}
MIN_TREND_POINTS = 3
MIN_TREND_SPAN_MINUTES = 10
PACE_TOLERANCE = 5.0  # percentage points either side of "on pace"
# Only warn if the limit would be hit at least this share of the window before
# the reset; hitting it minutes before a reset isn't worth a warning.
HIT_MARGIN_FRACTION = 0.03

PACE_AHEAD = "ahead"  # using faster than the window allows
PACE_ON = "on"
PACE_UNDER = "under"

METHOD_TREND = "trend"
METHOD_AVERAGE = "average"


@dataclass(frozen=True)
class Reading:
    """One stored measurement of one limit."""

    at: datetime
    percent: float


@dataclass(frozen=True)
class Forecast:
    elapsed_percent: float          # how much of the window's time has passed, 0-100
    pace: str                       # PACE_AHEAD / PACE_ON / PACE_UNDER
    rate_per_hour: Optional[float]  # percentage points per hour
    hits_limit_at: Optional[datetime]  # None when the limit won't be reached before reset
    method: str                     # METHOD_TREND or METHOD_AVERAGE


def window_hours(key: str) -> Optional[float]:
    if key in WINDOW_HOURS:
        return WINDOW_HOURS[key]
    if key.startswith("seven_day"):
        return 168.0
    return None


def window_start(limit: UsageLimit) -> Optional[datetime]:
    hours = window_hours(limit.key)
    if hours is None or limit.resets_at is None:
        return None
    return limit.resets_at - timedelta(hours=hours)


def elapsed_percent(limit: UsageLimit, now: datetime) -> Optional[float]:
    hours = window_hours(limit.key)
    if hours is None or limit.resets_at is None:
        return None
    remaining = (limit.resets_at - now).total_seconds() / 3600
    elapsed = 100.0 * (1.0 - remaining / hours)
    return max(0.0, min(100.0, elapsed))


def pace_for(percent: float, elapsed: float) -> str:
    if percent > elapsed + PACE_TOLERANCE:
        return PACE_AHEAD
    if percent < elapsed - PACE_TOLERANCE:
        return PACE_UNDER
    return PACE_ON


def trend_rate(readings: Sequence[Reading]) -> Optional[float]:
    """Least-squares slope through the readings, in percentage points per hour.

    Returns None when there isn't enough data for a trustworthy line.
    """
    if len(readings) < MIN_TREND_POINTS:
        return None
    start = readings[0].at
    xs = [(r.at - start).total_seconds() / 3600 for r in readings]
    ys = [r.percent for r in readings]
    if (xs[-1] - xs[0]) * 60 < MIN_TREND_SPAN_MINUTES:
        return None
    mean_x = sum(xs) / len(xs)
    mean_y = sum(ys) / len(ys)
    denominator = sum((x - mean_x) ** 2 for x in xs)
    if denominator == 0:
        return None
    numerator = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    return numerator / denominator


def forecast(limit: UsageLimit, history: Sequence[Reading], now: datetime) -> Optional[Forecast]:
    """Pace and limit-hit estimate for one limit, or None if it has no window."""
    hours = window_hours(limit.key)
    start = window_start(limit)
    elapsed = elapsed_percent(limit, now)
    if hours is None or start is None or elapsed is None or limit.resets_at is None:
        return None

    # Only readings from the current window, within the trend lookback.
    lookback_from = max(start, now - timedelta(hours=TREND_LOOKBACK_HOURS.get(hours, hours)))
    recent = sorted(
        (r for r in history if lookback_from <= r.at <= now),
        key=lambda r: r.at,
    )

    rate = trend_rate(recent)
    method = METHOD_TREND
    if rate is None:
        method = METHOD_AVERAGE
        elapsed_hours = hours * elapsed / 100
        rate = limit.percent / elapsed_hours if elapsed_hours > 0 else None

    hits_at: Optional[datetime] = None
    if limit.percent >= 100:
        hits_at = now
    elif rate is not None and rate > 0:
        candidate = now + timedelta(hours=(100 - limit.percent) / rate)
        margin = timedelta(hours=hours * HIT_MARGIN_FRACTION)
        if candidate < limit.resets_at - margin:
            hits_at = candidate

    return Forecast(
        elapsed_percent=elapsed,
        pace=pace_for(limit.percent, elapsed),
        rate_per_hour=rate,
        hits_limit_at=hits_at,
        method=method,
    )


def describe(forecast_value: Optional[Forecast], now: datetime) -> str:
    """Short text for the widget: "on track" or "limit ~3:40 pm"."""
    if forecast_value is None:
        return ""
    if forecast_value.hits_limit_at is None:
        return "on track"
    local_hit = forecast_value.hits_limit_at.astimezone()
    local_now = now.astimezone()
    time_text = local_hit.strftime("%I:%M %p").lstrip("0").lower()
    if local_hit.date() != local_now.date():
        time_text = local_hit.strftime("%a ") + time_text
    return f"limit ~{time_text}"


def pace_text(forecast_value: Optional[Forecast]) -> str:
    """Longer explanation for the bar's hover tooltip."""
    if forecast_value is None:
        return ""
    pace_words = {
        PACE_AHEAD: "ahead of pace (using it faster than time passes)",
        PACE_ON: "on pace",
        PACE_UNDER: "under pace",
    }[forecast_value.pace]
    lines = [f"{forecast_value.elapsed_percent:.0f}% of this window has passed — {pace_words}"]
    if forecast_value.rate_per_hour is not None:
        basis = "recent trend" if forecast_value.method == METHOD_TREND else "average so far"
        lines.append(f"Rate: {forecast_value.rate_per_hour:.1f}% per hour ({basis})")
    return "\n".join(lines)
