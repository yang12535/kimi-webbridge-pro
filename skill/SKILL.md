---
name: kimi-webbridge-pro
description: "Control the user's real logged-in browser through the local Kimi WebBridge daemon. Use when the task requires a real browser session, login state, existing tabs, screenshots, form filling, confirmed file uploads, PDF saving, or network diagnosis. Prefer a dedicated API, MCP tool, or site-specific skill when one is explicitly available and sufficient. Do not use for pure web search, factual lookup, or tasks that do not need browser state."
---

# Kimi WebBridge Pro

Control the user's live browser through the daemon at `http://127.0.0.1:10086`.

## Before every task

1. Check readiness without sending browser actions:

   ```powershell
   py -3 scripts\doctor.py --wait-connected 20
   ```

   ```bash
   python3 scripts/doctor.py --wait-connected 20
   ```

   Proceed only when the report has `"ready": true`. Otherwise read [operations.md](references/operations.md).
2. Assign one stable `session` name for the task.
3. Use `find_tab` for user-owned existing tabs, or `navigate` with `newTab:true` for task-owned tabs.

## Quick action map

Use this as the minimum dashboard. Read [protocol.md](references/protocol.md) for full action arguments, advanced actions, and response details.

| Action | Use when |
|---|---|
| `navigate` | Open a URL in the selected tab, or create a task-owned tab with `newTab:true`. |
| `find_tab` | Attach the session to an existing user-owned tab by URL. |
| `list_tabs` | Inspect tabs associated with the session before cleanup or popup diagnosis. |
| `snapshot` | Read URL, title, accessible text, and `@e` refs for the selected tab. |
| `click` | Click a snapshot ref or selector after taking a fresh snapshot. |
| `fill` | Replace text in an input, textarea, or contenteditable field. |
| `evaluate` | Read bounded page state or recover a real link when normal actions are insufficient. |
| `screenshot` | Capture the page or an element; use the helper to handle path/base64 variants. |
| `close_tab` | Close the selected task-owned tab after verification. |

Treat `close_session`, `upload`, `save_as_pdf`, and `network` as advanced actions; load [protocol.md](references/protocol.md) before using them.

## Use helpers

Read [protocol.md](references/protocol.md) before the first browser command in a task or whenever an action's arguments are uncertain.

Use the bundled helper for the current shell instead of hand-escaping JSON.

PowerShell:

```powershell
& scripts\invoke.ps1 -Session "research" -Action "navigate" -ActionArgs @{
  url = "https://example.com"
  newTab = $true
  group_title = "Research"
}
```

Bash:

```bash
scripts/invoke.sh --session research --action navigate \
  --args-json '{"url":"https://example.com","newTab":true,"group_title":"Research"}'
```

For non-ASCII or complex Bash arguments, write UTF-8 JSON to a file and pass `--args-file`. See [protocol.md](references/protocol.md).

Use [screenshot.py](scripts/screenshot.py) for cross-platform screenshots. PowerShell-only workflows may continue using [screenshot.ps1](scripts/screenshot.ps1). Both accept current path-based responses and older base64 responses without flooding context.
For large or unknown pages, use [snapshot.py](scripts/snapshot.py) in `compact` or `file` mode instead of printing the full snapshot response.
Use [doctor.py](scripts/doctor.py) for no-action readiness checks: binary presence, daemon status, port reachability, PID staleness, and extension connection.
Run Python helpers with `py -3` (or `py`) on Windows and `python3` on POSIX. Do not assume `python3` is the Windows launcher.

## Minimal workflows

Readiness smoke test, with no page changes:

```powershell
py -3 scripts\doctor.py --wait-connected 20
& scripts\invoke.ps1 -Session "kimi-webbridge-pro-smoke" -Action "list_tabs"
```

```bash
python3 scripts/doctor.py --wait-connected 20
scripts/invoke.sh --session kimi-webbridge-pro-smoke --action list_tabs
```

Task-owned tab workflow:

```powershell
& scripts\invoke.ps1 -Session "demo" -Action "navigate" -ActionArgs @{
  url = "https://example.com"
  newTab = $true
  group_title = "Demo"
}
py -3 scripts\screenshot.py --session demo
& scripts\invoke.ps1 -Session "demo" -Action "list_tabs"
& scripts\invoke.ps1 -Session "demo" -Action "close_tab"
```

```bash
scripts/invoke.sh --session demo --action navigate \
  --args-json '{"url":"https://example.com","newTab":true,"group_title":"Demo"}'
python3 scripts/screenshot.py --session demo
scripts/invoke.sh --session demo --action list_tabs
scripts/invoke.sh --session demo --action close_tab
```

User-owned tab workflow: call `find_tab`, take a compact `snapshot`, perform the requested action, and do not close the tab unless the user explicitly asks.

## Follow one task workflow

1. Assign one stable session name.
2. Use `find_tab` for a user-owned existing tab, or `navigate` with `newTab:true` for a task-owned tab.
3. Take a `snapshot`.
4. Use snapshot `@e` refs with `click` and `fill`.
5. After navigation or a click that should change the page, use [wait_for.py](scripts/wait_for.py) or poll URL/title up to three times.
6. Take a new snapshot after a substantial DOM change; old refs may be stale.
7. Use `list_tabs` before cleanup and prefer `close_tab` for task-owned tabs. Do not close user-owned tabs.

Do not assume `find_tab` visibly focuses a browser tab. It selects a matching tab for the WebBridge session; `active:true` means prefer the browser's currently active matching tab.
Treat `@e` values as WebBridge snapshot references, not DOM attributes. Do not query them with selectors such as `[data-ref="@e1"]`.
When using `wait_for.py`, the text condition flag is `--text-contains`; `--visible-text` is accepted as an alias.

## Recover when the page looks unchanged

**Check browser popup and new-window blocking before repeating the click.**

1. Compare the returned URL and take a fresh `snapshot`; SPA navigation may update in place.
2. Call `list_tabs`; the destination may be in a background tab.
3. Use `find_tab` to select the destination for the session.
4. If no tab appeared, tell the user the browser may have blocked a popup or new tab. Ask them to allow popups/new windows for that site, then retry once.
5. If a result card has nested click targets, inspect its primary `href` with `evaluate` and navigate directly.

## Preserve user state

- Treat tabs found with `find_tab` as user-owned. Do not close them unless the user explicitly asks.
- Treat tabs created with `navigate newTab:true` as task-owned. Close them when cleanup is appropriate.
- The bundled invoke helpers refuse `close_session` unless `--force` or `-Force` is supplied. Use it only after verifying every session tab is task-owned.
- Collect only the page content needed for the task. Treat snapshots, screenshots, PDFs, network captures, and page text as potentially sensitive.
- Do not inspect or return cookies, authorization headers, session tokens, password fields, browser storage, or unrelated private page content.
- Use `network` only when the task specifically requires request-level diagnosis, and avoid collecting authentication headers or unrelated bodies.
- Delete temporary screenshots and PDFs after use unless the user asked to keep them.
- Confirm before sending messages, publishing content, purchasing, deleting, changing permissions, uploading files, or submitting sensitive data.
- Do not bypass CAPTCHAs, paywalls, age gates, browser warnings, or site security controls.
- Report trusted-input and cross-origin iframe limits instead of attempting a workaround.

## Human-only background

Do not read [how-it-works.md](references/how-it-works.md) during normal task execution. It is a high-context design explanation for human maintainers, not an operational dependency.
