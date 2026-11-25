"""Pure data logic: parsing claude.ai responses and formatting values.

Nothing in this module touches Qt, so all of it is covered by unit tests.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable, Optional
from urllib.parse import urlparse

# Friendly names for the limits claude.ai reports today. Any new limit that
# shows up later is still displayed, with a label generated from its key.
KNOWN_LABELS = {
    "five_hour": "Current session",
    "seven_day": "Weekly · all models",
    "seven_day_sonnet": "Weekly · Sonnet",
    "seven_day_opus": "Weekly · Opus",
    "extra_usage": "Extra usage",
}
DISPLAY_ORDER = list(KNOWN_LABELS)

LEVEL_OK = "ok"
LEVEL_WARN = "warn"
LEVEL_CRITICAL = "critical"
LEVEL_RANK = {LEVEL_OK: 0, LEVEL_WARN: 1, LEVEL_CRITICAL: 2}

_LOGGED_IN_PATHS = ("/new", "/chat", "/recents", "/project", "/settings")
_FRACTION_RE = re.compile(r"(\.\d{6})\d+")


@dataclass(frozen=True)
class UsageLimit:
    key: str
    label: str
    percent: float
    resets_at: Optional[datetime]


def extract_json(text: Optional[str]) -> Any:
    """Pull the JSON value out of a page's plain text.

    The browser renders a JSON response as text, and some Chromium versions
    put extra UI text (such as a "Pretty-print" toggle) before it, so we look
    for the first position where a JSON object or array can be decoded.
    """
    if not text:
        return None
    decoder = json.JSONDecoder()
    first_empty: Any = None
    tried = 0
    for index, char in enumerate(text):
        if char not in "{[":
            continue
        tried += 1
        if tried > 20:
            break
        try:
            value, _ = decoder.raw_decode(text, index)
        except json.JSONDecodeError:
            continue
        if value:
            return value
        # An empty [] or {} might be stray UI text; keep looking, but
        # fall back to it if nothing better turns up.
        if first_empty is None:
            first_empty = value
    return first_empty


def is_error_response(data: Any) -> bool:
    """claude.ai API errors look like {"type": "error", "error": {...}}."""
    if not isinstance(data, dict):
        return False
    if data.get("type") == "error":
        return True
    return "error" in data and isinstance(data["error"], (dict, str))


def pick_org_id(orgs: Any) -> Optional[str]:
    """Choose the organization whose usage we should show.

    Prefer an org that has the "chat" capability (your claude.ai plan);
    otherwise fall back to the first org that has a uuid.
    """
    if not isinstance(orgs, list):
        return None
    candidates = [o for o in orgs if isinstance(o, dict) and o.get("uuid")]
    for org in candidates:
        capabilities = org.get("capabilities") or []
        if "chat" in capabilities:
            return str(org["uuid"])
    return str(candidates[0]["uuid"]) if candidates else None


def parse_datetime(value: Any) -> Optional[datetime]:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    text = _FRACTION_RE.sub(r"\1", text)
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def label_for(key: str) -> str:
    return KNOWN_LABELS.get(key, key.replace("_", " ").capitalize())


def parse_usage(data: Any) -> list[UsageLimit]:
    """Turn the usage endpoint's JSON into a sorted list of limits.

    Every top-level entry that carries a numeric "utilization" is a limit.
    Entries that are null (limit doesn't apply to your plan) are skipped, and
    extra usage is only shown when it is switched on.
    """
    if not isinstance(data, dict):
        raise ValueError("Unexpected usage response")

    limits: list[UsageLimit] = []
    for key, value in data.items():
        if not isinstance(value, dict):
            continue
        utilization = value.get("utilization")
        if utilization is None:
            continue
        if key == "extra_usage" and not value.get("is_enabled", False):
            continue
        try:
            percent = float(utilization)
        except (TypeError, ValueError):
            continue
        percent = max(0.0, min(100.0, percent))
        limits.append(
            UsageLimit(
                key=key,
                label=label_for(key),
                percent=percent,
                resets_at=parse_datetime(value.get("resets_at")),
            )
        )

    def sort_key(limit: UsageLimit) -> tuple[int, str]:
        if limit.key in DISPLAY_ORDER:
            return DISPLAY_ORDER.index(limit.key), limit.key
        return len(DISPLAY_ORDER), limit.key

    limits.sort(key=sort_key)
    return limits


def pick_tray_limit(limits: Iterable[UsageLimit], preferred_key: str) -> Optional[UsageLimit]:
    """The limit whose number is drawn in the tray icon.

    Uses the preferred key (the 5-hour session by default). If your plan
    doesn't have that limit, shows whichever limit is closest to full.
    """
    limits = list(limits)
    if not limits:
        return None
    if preferred_key != "highest":
        for limit in limits:
            if limit.key == preferred_key:
                return limit
    return max(limits, key=lambda limit: limit.percent)


def level_for(percent: float, warn_percent: float, critical_percent: float) -> str:
    if percent >= critical_percent:
        return LEVEL_CRITICAL
    if percent >= warn_percent:
        return LEVEL_WARN
    return LEVEL_OK


def format_countdown(resets_at: Optional[datetime], now: Optional[datetime] = None) -> str:
    if resets_at is None:
        return ""
    now = now or datetime.now(timezone.utc)
    seconds = int((resets_at - now).total_seconds())
    if seconds <= 0:
        return "Resetting…"
    days, remainder = divmod(seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes = remainder // 60
    if days:
        return f"Resets in {days}d {hours}h"
    if hours:
        return f"Resets in {hours}h {minutes}m"
    if minutes:
        return f"Resets in {minutes}m"
    return "Resets in <1m"


def format_percent(percent: float) -> str:
    return f"{round(percent)}%"


def tooltip_text(limits: Iterable[UsageLimit], now: Optional[datetime] = None) -> str:
    lines = ["Claude usage"]
    for limit in limits:
        line = f"{limit.label}: {format_percent(limit.percent)}"
        countdown = format_countdown(limit.resets_at, now)
        if countdown:
            line += f" ({countdown.lower()})"
        lines.append(line)
    return "\n".join(lines)


def is_logged_in_url(url: str) -> bool:
    """True once the login window has landed on a normal claude.ai page."""
    parsed = urlparse(url)
    if parsed.hostname not in ("claude.ai", "www.claude.ai"):
        return False
    path = parsed.path or "/"
    return any(path == p or path.startswith(p + "/") for p in _LOGGED_IN_PATHS)
