# Claude Usage Widget

A small Windows app that shows your Claude plan usage (the same numbers as
claude.ai → Settings → Usage) without opening a browser:

- **Tray icon** next to the clock with your current session % drawn inside it,
  coloured green / orange / red. Hover for every limit and its reset time.
- **Desktop widget**: a floating panel with a progress bar per limit
  (current session, weekly all-models, weekly Sonnet, and any new limit
  claude.ai adds), plus reset countdowns. Drag it anywhere; it remembers
  where you put it.
- **Notifications** when a limit crosses 75% and 90% (configurable).
- **Start with Windows**, toggled from the tray menu.

## How it works

Anthropic doesn't publish an API for Pro/Max plan usage. The claude.ai
usage page loads its numbers from an internal endpoint
(`/api/organizations/<org-id>/usage`), and this app reads that same endpoint.

Instead of asking you to copy a session cookie out of your browser, the app
embeds its own Chromium browser (QtWebEngine). The first time it runs, a
sign-in window opens. You log in to claude.ai normally, and the app keeps
that session in its own browser profile on disk. After that, a hidden page
in the same profile requests the usage JSON every couple of minutes. No
password, cookie or key is ever stored in the project or in `.env`.

Because the endpoint is unofficial, a claude.ai update can break it. When
that happens the widget keeps the last values and says it couldn't refresh.

```
main.py                     entry point: single-instance lock, logging, Qt app
usage_widget/
  config.py                 .env settings and constants
  models.py                 pure logic: parse JSON, pick org, format values (unit tested)
  fetcher.py                hidden browser page that requests the usage JSON
  login_window.py           visible sign-in window sharing the same browser profile
  app.py                    wires tray, widget, fetcher, notifications, menu
  desktop_widget.py         the floating panel
  icons.py                  draws the tray icon with the number in it
  autostart.py              Start with Windows (HKCU Run registry key)
tests/test_models.py        pytest tests for models.py
```

## Setup (Windows)

```powershell
cd "D:\AI Models\claude-usage-widget"
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements-dev.txt
copy .env.example .env
python -m pytest
python main.py
```

The sign-in window opens on first run. If Google sign-in complains that
the browser isn't supported, use **Continue with email** and click the
link claude.ai sends you. Paste it into the sign-in window's page if your
mail app opens it in your normal browser instead. The window closes by
itself once you're in, and the tray icon shows your number within a few
seconds.

Left-click the tray icon to show or hide the widget. Right-click the
tray icon or the widget for the menu.

> Windows sometimes hides new tray icons in the `^` overflow area. Drag the
> icon onto the taskbar to keep it always visible.

## Settings (`.env`)

| Key | Default | Meaning |
| --- | --- | --- |
| `REFRESH_SECONDS` | `120` | How often to check (minimum 60) |
| `WARN_PERCENT` | `75` | Orange colour and first notification |
| `CRITICAL_PERCENT` | `90` | Red colour and second notification |
| `TRAY_METRIC` | `five_hour` | Number in the tray icon: `five_hour`, `seven_day`, `seven_day_sonnet` or `highest` |
| `NOTIFICATIONS` | `true` | Windows notifications on threshold crossings |

## Build an .exe

```powershell
pyinstaller --noconsole --name ClaudeUsageWidget main.py
copy .env.example dist\ClaudeUsageWidget\.env
```

Run `dist\ClaudeUsageWidget\ClaudeUsageWidget.exe`, then turn on
**Start with Windows** from the tray menu. The folder is around 200 MB
because it bundles Chromium for the sign-in browser. Use the default
one-folder build: `--onefile` starts slowly with QtWebEngine.

## Troubleshooting

- Logs: `%LOCALAPPDATA%\ClaudeUsageWidget\app.log`
- Stuck on "Sign-in needed": right-click → **Sign in again…**
- Saved settings (widget position, org id) live in the registry under
  `HKCU\Software\MihirHarne\ClaudeUsageWidget`. Delete that key to reset them.
