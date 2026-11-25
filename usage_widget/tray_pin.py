"""Keep the tray icon visible on the taskbar instead of in the ^ overflow.

Windows 11 keeps one registry entry per tray icon under
HKCU\\Control Panel\\NotifyIconSettings. Its IsPromoted value is the same
switch as Settings > Personalization > Taskbar > Other system tray icons.
We find the entry whose ExecutablePath is this program and set IsPromoted.

Windows creates the entry only after the icon has been shown once, so the
app calls this a few seconds after start-up. On Windows 10 (which uses a
different, undocumented format) nothing changes and the user can drag the
icon instead.
"""
from __future__ import annotations

import logging
import os
import sys

log = logging.getLogger(__name__)

SETTINGS_KEY = r"Control Panel\NotifyIconSettings"
IS_WINDOWS = sys.platform == "win32"
if IS_WINDOWS:
    import winreg


def _normalize(path: str) -> str:
    return os.path.normcase(os.path.normpath(path))


def candidate_paths() -> set[str]:
    """Executables that may own our tray icon.

    When packaged, that's the .exe. When run from source inside a virtual
    environment, Windows' venv python.exe launches the base interpreter, and
    the icon belongs to that base interpreter, so we include both (and their
    pythonw.exe siblings).
    """
    paths = {sys.executable, getattr(sys, "_base_executable", sys.executable)}
    for path in list(paths):
        folder, name = os.path.split(path)
        if name.lower() == "python.exe":
            paths.add(os.path.join(folder, "pythonw.exe"))
        elif name.lower() == "pythonw.exe":
            paths.add(os.path.join(folder, "python.exe"))
    return {_normalize(p) for p in paths}


def set_promoted(promoted: bool) -> int:
    """Set IsPromoted on our tray icon entries. Returns how many entries changed.

    Returns 0 on other systems, on Windows 10, or when Windows hasn't created
    the entry yet.
    """
    if not IS_WINDOWS:
        return 0
    wanted = candidate_paths()
    changed = 0
    try:
        root = winreg.OpenKey(winreg.HKEY_CURRENT_USER, SETTINGS_KEY)
    except FileNotFoundError:
        log.info("No NotifyIconSettings key (probably Windows 10); can't pin tray icon")
        return 0

    with root:
        index = 0
        while True:
            try:
                name = winreg.EnumKey(root, index)
            except OSError:
                break
            index += 1
            try:
                with winreg.OpenKey(root, name, 0, winreg.KEY_READ | winreg.KEY_SET_VALUE) as entry:
                    path, _ = winreg.QueryValueEx(entry, "ExecutablePath")
                    if _normalize(str(path)) not in wanted:
                        continue
                    try:
                        current, _ = winreg.QueryValueEx(entry, "IsPromoted")
                    except FileNotFoundError:
                        current = 0
                    if bool(current) != promoted:
                        winreg.SetValueEx(entry, "IsPromoted", 0, winreg.REG_DWORD, int(promoted))
                        changed += 1
            except OSError:
                continue
    log.info("Tray icon promoted=%s, entries changed: %d", promoted, changed)
    return changed


def entry_exists() -> bool:
    """True if Windows has a NotifyIconSettings entry for this program."""
    if not IS_WINDOWS:
        return False
    wanted = candidate_paths()
    try:
        root = winreg.OpenKey(winreg.HKEY_CURRENT_USER, SETTINGS_KEY)
    except FileNotFoundError:
        return False
    with root:
        index = 0
        while True:
            try:
                name = winreg.EnumKey(root, index)
            except OSError:
                return False
            index += 1
            try:
                with winreg.OpenKey(root, name) as entry:
                    path, _ = winreg.QueryValueEx(entry, "ExecutablePath")
                    if _normalize(str(path)) in wanted:
                        return True
            except OSError:
                continue
