"""Stores every usage reading in a small SQLite database.

The pace forecast and the history chart both read from here. The file lives
at %LOCALAPPDATA%\\ClaudeUsageWidget\\history.db, and readings older than
KEEP_DAYS are deleted so it never grows large.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Optional

from .forecast import Reading
from .models import UsageLimit

KEEP_DAYS = 60

SCHEMA = """
CREATE TABLE IF NOT EXISTS readings (
    ts         INTEGER NOT NULL,  -- unix seconds, UTC
    limit_key  TEXT    NOT NULL,
    percent    REAL    NOT NULL,
    resets_at  INTEGER            -- unix seconds, UTC, may be NULL
);
CREATE INDEX IF NOT EXISTS idx_readings_key_ts ON readings (limit_key, ts);
"""


def _to_unix(value: datetime) -> int:
    return int(value.timestamp())


def _from_unix(value: int) -> datetime:
    return datetime.fromtimestamp(value, tz=timezone.utc)


class HistoryStore:
    def __init__(self, path: Path | str):
        self._path = str(path)
        self._conn = sqlite3.connect(self._path)
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def add(self, limits: Iterable[UsageLimit], at: datetime) -> None:
        rows = [
            (
                _to_unix(at),
                limit.key,
                limit.percent,
                _to_unix(limit.resets_at) if limit.resets_at else None,
            )
            for limit in limits
        ]
        if not rows:
            return
        with self._conn:
            self._conn.executemany(
                "INSERT INTO readings (ts, limit_key, percent, resets_at) VALUES (?, ?, ?, ?)",
                rows,
            )

    def readings(self, key: str, since: datetime, until: Optional[datetime] = None) -> list[Reading]:
        until = until or datetime.now(timezone.utc)
        cursor = self._conn.execute(
            "SELECT ts, percent FROM readings WHERE limit_key = ? AND ts BETWEEN ? AND ? ORDER BY ts",
            (key, _to_unix(since), _to_unix(until)),
        )
        return [Reading(at=_from_unix(ts), percent=percent) for ts, percent in cursor]

    def keys(self, since: datetime) -> list[str]:
        cursor = self._conn.execute(
            "SELECT DISTINCT limit_key FROM readings WHERE ts >= ?", (_to_unix(since),)
        )
        return [row[0] for row in cursor]

    def prune(self, now: datetime, keep_days: int = KEEP_DAYS) -> int:
        cutoff = _to_unix(now - timedelta(days=keep_days))
        with self._conn:
            cursor = self._conn.execute("DELETE FROM readings WHERE ts < ?", (cutoff,))
        return cursor.rowcount
