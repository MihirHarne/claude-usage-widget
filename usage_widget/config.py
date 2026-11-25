"""App configuration from the .env file next to main.py (or the .exe)."""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

APP_NAME = "ClaudeUsageWidget"
ORG_NAME = "MihirHarne"
USAGE_PAGE_URL = "https://claude.ai/settings/usage"
LOGIN_URL = "https://claude.ai/login"
ORGS_API_URL = "https://claude.ai/api/organizations"
USAGE_API_URL = "https://claude.ai/api/organizations/{org_id}/usage"

# Never poll claude.ai more often than this, however .env is set.
MIN_REFRESH_SECONDS = 60


@dataclass(frozen=True)
class Config:
    refresh_seconds: int = 120
    warn_percent: float = 75.0
    critical_percent: float = 90.0
    tray_metric: str = "five_hour"
    notifications: bool = True


def app_dir() -> Path:
    """Folder that holds .env: the .exe's folder when packaged, else the project root."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def data_dir() -> Path:
    """Per-user folder for logs (%LOCALAPPDATA%\\ClaudeUsageWidget on Windows)."""
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / ".local" / "share")
    path = Path(base) / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def _get_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


def _get_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return default


def _get_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


def load_config() -> Config:
    load_dotenv(app_dir() / ".env")
    warn = _get_float("WARN_PERCENT", 75.0)
    critical = _get_float("CRITICAL_PERCENT", 90.0)
    if critical < warn:
        warn, critical = critical, warn
    return Config(
        refresh_seconds=max(MIN_REFRESH_SECONDS, _get_int("REFRESH_SECONDS", 120)),
        warn_percent=warn,
        critical_percent=critical,
        tray_metric=os.environ.get("TRAY_METRIC", "five_hour").strip() or "five_hour",
        notifications=_get_bool("NOTIFICATIONS", True),
    )
