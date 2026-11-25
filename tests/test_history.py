from datetime import datetime, timedelta, timezone

from usage_widget.history import HistoryStore
from usage_widget.models import UsageLimit

NOW = datetime(2026, 11, 25, 6, 0, tzinfo=timezone.utc)


def make_limits(session_pct, weekly_pct):
    return [
        UsageLimit("five_hour", "Current session", session_pct, NOW + timedelta(hours=2)),
        UsageLimit("seven_day", "Weekly", weekly_pct, None),
    ]


def test_add_and_read_back(tmp_path):
    store = HistoryStore(tmp_path / "history.db")
    store.add(make_limits(10, 30), NOW - timedelta(minutes=10))
    store.add(make_limits(15, 31), NOW)

    session = store.readings("five_hour", since=NOW - timedelta(hours=1), until=NOW)
    assert [r.percent for r in session] == [10, 15]
    assert session[-1].at == NOW
    assert sorted(store.keys(since=NOW - timedelta(days=1))) == ["five_hour", "seven_day"]
    store.close()


def test_readings_respect_time_range(tmp_path):
    store = HistoryStore(tmp_path / "history.db")
    store.add(make_limits(5, 5), NOW - timedelta(days=2))
    store.add(make_limits(6, 6), NOW)
    recent = store.readings("five_hour", since=NOW - timedelta(days=1), until=NOW)
    assert [r.percent for r in recent] == [6]
    store.close()


def test_prune_removes_old_rows(tmp_path):
    store = HistoryStore(tmp_path / "history.db")
    store.add(make_limits(1, 1), NOW - timedelta(days=90))
    store.add(make_limits(2, 2), NOW)
    assert store.prune(NOW, keep_days=60) == 2
    assert len(store.readings("five_hour", since=NOW - timedelta(days=365), until=NOW)) == 1
    store.close()


def test_data_survives_reopen(tmp_path):
    path = tmp_path / "history.db"
    store = HistoryStore(path)
    store.add(make_limits(12, 34), NOW)
    store.close()
    reopened = HistoryStore(path)
    assert reopened.readings("seven_day", since=NOW - timedelta(hours=1), until=NOW)[0].percent == 34
    reopened.close()
