from datetime import datetime, timedelta, timezone

import pytest

from usage_widget.models import (
    extract_json,
    format_countdown,
    is_error_response,
    is_logged_in_url,
    level_for,
    parse_datetime,
    parse_usage,
    pick_org_id,
    pick_tray_limit,
    tooltip_text,
)

SAMPLE_USAGE = {
    "five_hour": {"utilization": 42.0, "resets_at": "2026-11-25T09:00:00.123456789Z"},
    "seven_day": {"utilization": 61.5, "resets_at": "2026-11-28T19:00:00+00:00"},
    "seven_day_opus": None,
    "seven_day_sonnet": {"utilization": 12.0, "resets_at": None},
    "seven_day_new_thing": {"utilization": 5, "resets_at": None},
    "extra_usage": {"is_enabled": False, "utilization": None, "monthly_limit": None},
}


def test_parse_usage_orders_and_labels_limits():
    limits = parse_usage(SAMPLE_USAGE)
    assert [l.key for l in limits] == [
        "five_hour",
        "seven_day",
        "seven_day_sonnet",
        "seven_day_new_thing",
    ]
    assert limits[0].label == "Current session"
    assert limits[3].label == "Seven day new thing"
    assert limits[0].percent == 42.0
    assert limits[0].resets_at == datetime(2026, 11, 25, 9, 0, 0, 123456, tzinfo=timezone.utc)


def test_parse_usage_shows_extra_usage_only_when_enabled():
    data = {"extra_usage": {"is_enabled": True, "utilization": 20.0}}
    assert [l.key for l in parse_usage(data)] == ["extra_usage"]


def test_parse_usage_clamps_percent():
    limits = parse_usage({"five_hour": {"utilization": 130}})
    assert limits[0].percent == 100.0


def test_parse_usage_rejects_non_dict():
    with pytest.raises(ValueError):
        parse_usage([1, 2, 3])


def test_extract_json_handles_viewer_text_before_json():
    assert extract_json('Pretty-print [ ]\n{"a": 1}') == {"a": 1}
    assert extract_json('[{"uuid": "x"}]') == [{"uuid": "x"}]
    assert extract_json("<html>Just a moment...</html>") is None
    assert extract_json("") is None


def test_error_detection():
    assert is_error_response({"type": "error", "error": {"type": "permission_error"}})
    assert is_error_response({"error": "unauthorized"})
    assert not is_error_response(SAMPLE_USAGE)
    assert not is_error_response([])


def test_pick_org_prefers_chat_capability():
    orgs = [
        {"uuid": "api-org", "capabilities": ["api"]},
        {"uuid": "chat-org", "capabilities": ["chat", "claude_pro"]},
    ]
    assert pick_org_id(orgs) == "chat-org"
    assert pick_org_id([{"uuid": "only"}]) == "only"
    assert pick_org_id([]) is None
    assert pick_org_id({"type": "error"}) is None


def test_pick_tray_limit():
    limits = parse_usage(SAMPLE_USAGE)
    assert pick_tray_limit(limits, "five_hour").key == "five_hour"
    assert pick_tray_limit(limits, "highest").key == "seven_day"
    # Plan without a session limit falls back to the fullest one.
    assert pick_tray_limit(limits[1:], "five_hour").key == "seven_day"
    assert pick_tray_limit([], "five_hour") is None


def test_level_for():
    assert level_for(10, 75, 90) == "ok"
    assert level_for(75, 75, 90) == "warn"
    assert level_for(95, 75, 90) == "critical"


def test_format_countdown():
    now = datetime(2026, 11, 25, 6, 0, tzinfo=timezone.utc)
    assert format_countdown(None, now) == ""
    assert format_countdown(now - timedelta(minutes=1), now) == "Resetting…"
    assert format_countdown(now + timedelta(seconds=30), now) == "Resets in <1m"
    assert format_countdown(now + timedelta(minutes=12), now) == "Resets in 12m"
    assert format_countdown(now + timedelta(hours=2, minutes=10), now) == "Resets in 2h 10m"
    assert format_countdown(now + timedelta(days=3, hours=4), now) == "Resets in 3d 4h"


def test_parse_datetime_variants():
    assert parse_datetime("2026-11-25T09:00:00") == datetime(2026, 11, 25, 9, tzinfo=timezone.utc)
    assert parse_datetime("not a date") is None
    assert parse_datetime(None) is None


def test_tooltip_text():
    now = datetime(2026, 11, 25, 6, 0, tzinfo=timezone.utc)
    text = tooltip_text(parse_usage(SAMPLE_USAGE)[:1], now)
    assert text == "Claude usage\nCurrent session: 42% (resets in 3h 0m)"


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://claude.ai/new", True),
        ("https://claude.ai/chat/abc", True),
        ("https://claude.ai/recents", True),
        ("https://claude.ai/login", False),
        ("https://claude.ai/login?returnTo=/new", False),
        ("https://accounts.google.com/new", False),
        ("https://claude.ai/newsletter", False),
    ],
)
def test_is_logged_in_url(url, expected):
    assert is_logged_in_url(url) is expected
