from datetime import datetime, timedelta, timezone

import pytest

from usage_widget.forecast import (
    METHOD_AVERAGE,
    METHOD_TREND,
    PACE_AHEAD,
    PACE_ON,
    PACE_UNDER,
    Reading,
    describe,
    pace_text,
    elapsed_percent,
    forecast,
    trend_rate,
    window_hours,
)
from usage_widget.models import UsageLimit

NOW = datetime(2026, 11, 25, 6, 0, tzinfo=timezone.utc)


def session(percent, hours_left):
    return UsageLimit("five_hour", "Current session", percent, NOW + timedelta(hours=hours_left))


def test_window_hours():
    assert window_hours("five_hour") == 5
    assert window_hours("seven_day") == 168
    assert window_hours("seven_day_something_new") == 168
    assert window_hours("extra_usage") is None


def test_elapsed_percent():
    # 5h window with 3h left -> 2h of 5h elapsed = 40%
    assert elapsed_percent(session(10, 3), NOW) == pytest.approx(40)
    assert elapsed_percent(UsageLimit("five_hour", "x", 0, None), NOW) is None


def test_trend_rate_fits_a_line():
    readings = [Reading(NOW + timedelta(minutes=m), 10 + m / 6) for m in (0, 20, 40, 60)]
    assert trend_rate(readings) == pytest.approx(10.0)  # 10 points per hour


def test_trend_rate_needs_enough_data():
    assert trend_rate([Reading(NOW, 1), Reading(NOW + timedelta(minutes=30), 2)]) is None
    close_together = [Reading(NOW + timedelta(minutes=m), m) for m in (0, 2, 4)]
    assert trend_rate(close_together) is None


def test_forecast_uses_trend_and_predicts_hit_before_reset():
    limit = session(60, 3)  # 40% of time gone, 60% used -> ahead of pace
    history = [Reading(NOW - timedelta(minutes=m), 60 - m / 3) for m in (60, 40, 20, 0)]
    result = forecast(limit, history, NOW)
    assert result.method == METHOD_TREND
    assert result.pace == PACE_AHEAD
    assert result.rate_per_hour == pytest.approx(20)
    assert result.hits_limit_at == NOW + timedelta(hours=2)


def test_forecast_falls_back_to_average_rate():
    limit = session(20, 3)  # 20% over 2h -> 10/h -> 8h to 100%, after the reset
    result = forecast(limit, [], NOW)
    assert result.method == METHOD_AVERAGE
    assert result.pace == PACE_UNDER
    assert result.rate_per_hour == pytest.approx(10)
    assert result.hits_limit_at is None


def test_forecast_ignores_readings_from_previous_window():
    limit = session(42, 3)
    old_window = [Reading(NOW - timedelta(hours=h), 90) for h in (2.5, 2.4, 2.3)]
    result = forecast(limit, old_window, NOW)
    assert result.method == METHOD_AVERAGE


def test_forecast_ignores_hit_just_before_reset():
    # 40% used with 40% of the window gone: on pace, would hit 100% right at reset.
    assert forecast(session(40, 3), [], NOW).hits_limit_at is None


def test_forecast_on_pace_and_full():
    assert forecast(session(41, 3), [], NOW).pace == PACE_ON
    full = forecast(session(100, 1), [], NOW)
    assert full.hits_limit_at == NOW


def test_forecast_none_without_window():
    assert forecast(UsageLimit("extra_usage", "Extra", 50, None), [], NOW) is None


def test_describe():
    assert describe(None, NOW) == ""
    on_track = forecast(session(20, 3), [], NOW)
    assert describe(on_track, NOW) == "on track"
    hitting = forecast(session(60, 3), [], NOW)  # 30/h -> 100% in 80 min
    assert describe(hitting, NOW).startswith("limit ~")
    assert "ahead of pace" in pace_text(hitting)
    assert pace_text(None) == ""
