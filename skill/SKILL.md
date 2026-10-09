---
name: kimi-webbridge-pro
description: "Control the user's real logged-in browser through the local Kimi WebBridge daemon with safe cross-platform helpers, bounded snapshots, conditioned waits, and recovery diagnostics. When both kimi-webbridge and kimi-webbridge-pro are installed, prefer this Pro skill for helper-driven browser workflows. Use when the task requires a real browser session, login state, existing tabs, screenshots, form filling, confirmed file uploads, PDF saving, or network diagnosis. Prefer a dedicated API, MCP tool, or site-specific skill when one is explicitly available and sufficient. Do not use for pure web search, factual lookup, or tasks that do not need browser state."
---

# Kimi WebBridge Pro

Control the user's live browser through the daemon at `http://127.0.0.1:10086`.
Project source and issue tracker: https://github.com/yang12535/kimi-webbridge-pro

## Before every task

1. Check readiness without sending browser actions:

   ```powershell
   py -3 scripts\doctor.py --wait-connected 20
   ```

   ```bash
   python3 scripts/doctor.py --wait-connected 20
   ```

   Proceed only when the report has `"ready": true`. Otherwise read [operations.md](references/operations.md).
2. Assign one stable `session` name for each controlled tab or independent workstream.
3. Use `find_tab` for existing session tabs. For user-owned tabs outside the session, follow the [scoped lookup and focus fallback](references/protocol.md#find_tab-search-scope-and-url-matching). Use `navigate` with `newTab:true` for task-owned tabs.

## Quick decision tree

- Need an existing tab? Try `find_tab` with the known URL or hostname in the same session, then verify the full URL/title in a snapshot. In extension 2.0.22, default lookup searches session tabs only; `active:true` checks only the foreground tab in the last-focused browser window.
- Normal lookup missed? Try the known URL with `active:true` once before prompting; if that also misses, follow the [fallback workflow](references/protocol.md#when-normal-lookup-misses). In unattended mode, continue independent work and use a suitable task-owned page when the task permits; automatic approval after 300 seconds and a six-hour grant require upstream support and are not implemented here.
- User says only "current tab" and gives no URL or hostname? Do not guess with a broad wildcard; ask for the URL/domain or use a dedicated current-tab API when the host agent provides one.
- Need a side tab for a lookup or analysis? Give it a different session so it cannot displace the original tab's session selection.
- Need an isolated tab you can close later? Use `navigate` with `newTab:true`.
- Page size is unknown? Start with `snapshot.py --auto`.
- Need controls only? Use `snapshot.py --mode compact`.
- Need article text, long static content, or Chinese text extraction? Use `snapshot.py --mode file` and read only the relevant file sections.
- Sending Chinese, nested JSON, or quote-heavy arguments from Bash? Use `--args-stdin`; keep `--args-file` for an existing or reusable payload.
- After `navigate` or a click that should change state? Run a conditioned wait such as `python3 scripts/wait_for.py --session research --url-contains example.com --timeout 15`, then take a fresh snapshot and inspect URL/title.
- Click appears unchanged? Check `list_tabs`, popup blocking, then recover the real link with bounded `evaluate`.

## Quick action map

Use this as the minimum dashboard. Read [protocol.md](references/protocol.md) for full action arguments, advanced actions, and response details.

| Action | Use when |
|---|---|
| `navigate` | Open a URL in the selected tab, or create a task-owned tab with `newTab:true`. |
| `find_tab` | Select a matching session tab, or borrow the matching foreground tab with `active:true`; not a browser-wide search in 2.0.22. |
| `list_tabs` | Inspect tabs associated with the session before cleanup or popup diagnosis. |
| `snapshot` | Read URL, title, accessible text, and `@e` refs for the selected tab. |
| `click` | Click a snapshot ref or selector after taking a fresh snapshot. |
| `fill` | Replace plain text in an input, textarea, or contenteditable field; it does not preserve rich-text formatting. |
| `mouse_click` | Send a CDP mouse click to an element when DOM-level `click` is rejected. |
| `key_type` | Insert arbitrary Unicode text into the focused control. |
| `send_keys` | Send named keys or shortcuts such as `Enter`, `Tab`, or `Mod+B`. |
| `evaluate (code)` | Read bounded page state or recover a real link when normal actions are insufficient; the argument key is `code`, not `expression`. |
| `screenshot` | Capture the page or an element; use the helper to handle path/base64 variants. |
| `close_tab` | Close the selected task-owned tab after verification. |

Treat `close_session`, `upload`, `save_as_pdf`, `network`, and `cdp` as advanced actions; load [protocol.md](references/protocol.md) before using them. `mouse_click`, `key_type`, `send_keys`, and `cdp` are version-dependent; if the daemon returns `Unknown tool`, follow [operations.md](references/operations.md) instead of emulating success.
For worked examples, read only the relevant file under [examples](examples/): form filling, long-page extraction, popup recovery, or network debugging.

## Use helpers

Read [protocol.md](references/protocol.md) before the first browser command in a task or whenever an action's arguments are uncertain.

Use the bundled helper for the current shell instead of hand-escaping JSON.

Match the helper to the shell that is actually running: use `invoke.ps1` only in PowerShell and `invoke.sh` only in Bash, including Git Bash on Windows. Do not paste PowerShell syntax such as `$env:USERPROFILE` or `& ...` into Bash.

PowerShell:

```powershell
& scripts\invoke.ps1 -Session "research" -Action "navigate" -ActionArgs @{
  url = "https://example.com"
  newTab = $true
  group_title = "Research"
}
```

For non-ASCII or complex PowerShell arguments, prefer a UTF-8 JSON file:

```powershell
@'
{"selector":"@e10","value":"显卡日报：RTX 5090 价格"}
'@ | Set-Content -LiteralPath .\args.json -Encoding UTF8
& scripts\invoke.ps1 -Session "research" -Action "fill" -ArgsFile .\args.json
```

Bash:

```bash
scripts/invoke.sh --session research --action navigate \
  --args-json '{"url":"https://example.com","newTab":true,"group_title":"Research"}'
```

For non-ASCII or complex Bash arguments, stream UTF-8 JSON directly instead of creating a temporary file:

```bash
scripts/invoke.sh --session research --action fill --args-stdin <<'JSON'
{"selector":"@e10","value":"月相 🌔，鸡蛋 🥚，举重 🏋️‍♂️"}
JSON
```

`--args-file PATH` remains available for reusable or generated payloads. See [protocol.md](references/protocol.md).

Use [screenshot.py](scripts/screenshot.py) for cross-platform screenshots. PowerShell-only workflows may continue using [screenshot.ps1](scripts/screenshot.ps1). Both accept current path-based responses and older base64 responses without flooding context.
For large or unknown pages, use [snapshot.py](scripts/snapshot.py) with `--auto` first. It keeps pretty-printed compact output within a 12,000-byte inline budget and otherwise returns a small file envelope. Use `--mode file --output PATH` (aliases: `--path`, `--file`) when you need the raw daemon schema at a chosen path.
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

User-owned tab workflow: try `find_tab` in the same session. After a miss, use the documented focus fallback when appropriate. Once attached, take a compact `snapshot`, verify the actual page, perform the requested action, and do not close the tab unless the user explicitly asks.

`find_tab` requires a known URL or hostname and does not visibly activate the selected browser tab. In 2.0.22, matching uses the hostname and ignores the path, so even a full URL does not uniquely select an editor or document. Do not use broad wildcards to discover an unknown current tab.

When a tab is already attached to the session and visible activation is necessary, use the advanced `cdp` action if supported. `Page.bringToFront` cannot discover or attach an unknown tab:

```powershell
& scripts\invoke.ps1 -Session "example-task" -Action "find_tab" -ActionArgs @{
  url = "https://example.com/"
}
& scripts\invoke.ps1 -Session "example-task" -Action "cdp" -ActionArgs @{
  method = "Page.bringToFront"
  params = @{}
}
py -3 scripts\snapshot.py --session "example-task" --auto
```

```bash
scripts/invoke.sh --session example-task --action find_tab --args-stdin <<'JSON'
{"url":"https://example.com/"}
JSON
scripts/invoke.sh --session example-task --action cdp --args-stdin <<'JSON'
{"method":"Page.bringToFront","params":{}}
JSON
python3 scripts/snapshot.py --session example-task --auto
```

Treat `Page.bringToFront` as version-dependent and verify the resulting URL/title. If `cdp` is unavailable, keep controlling the selected session tab without claiming that the visible browser focus changed.

## Follow one task workflow

1. Assign one stable session name per controlled tab or independent workstream.
2. Use scoped `find_tab` lookup for an existing tab; follow the documented fallback after a miss. Use `navigate` with `newTab:true` for a task-owned tab when it satisfies the task.
3. Take `snapshot.py --auto` for unknown pages, or `snapshot.py --mode compact` when you only need controls.
4. Use snapshot `@e` refs with `click` and `fill`.
5. After navigation or a click that should change the page, use [wait_for.py](scripts/wait_for.py) with an explicit expected condition, for example `--url-contains example.com` or `--text-contains Saved`.
6. Take a new snapshot after a substantial DOM change; old refs may be stale.
7. Use `list_tabs` before cleanup and prefer `close_tab` for task-owned tabs. Do not close user-owned tabs.

Do not assume `find_tab` visibly focuses a browser tab. In 2.0.22, `active:true` exclusively checks the foreground tab in the last-focused normal/popup browser window; it does not fall back to other matching tabs.
Use a known URL or hostname, and verify the full URL/title after attachment. See the protocol reference for version-specific matching and bounded recovery.
Do not use one session to alternate between an original page and a side lookup tab. Use a second session for the side tab and keep the original session bound to the original page; this avoids relying on daemon-side focus switching.
Treat `@e` values as WebBridge snapshot references, not DOM attributes. Do not query them with selectors such as `[data-ref="@e1"]`.
When using `wait_for.py`, the text condition flag is `--text-contains`; `--visible-text` is accepted as an alias.
Calling `wait_for.py` without a condition is an error, not a generic sleep; it prints JSON with code `condition_required` and exits 2.

## Recover when the page looks unchanged

**Check browser popup and new-window blocking before repeating the click.**

1. Compare the returned URL and take a fresh `snapshot`; SPA navigation may update in place.
2. Call `list_tabs`; the destination may be in a background tab.
3. Use `find_tab` to select the destination for the session.
4. If no tab appeared, tell the user the browser may have blocked a popup or new tab. Ask them to allow popups/new windows for that site, then retry once.
5. If a result card has nested click targets, inspect its primary `href` with `evaluate` and navigate directly.

## Handle rich-text editors honestly

- Treat `fill` on `contenteditable` as plain-text replacement. It may remove or flatten existing markup and cannot express "bold these characters."
- Prefer the editor's accessible toolbar buttons. When `send_keys` is available, a page-specific workflow may use bounded `evaluate` to select the exact DOM range and then `send_keys` with `Mod+B` or another editor shortcut.
- Preserve the smallest possible DOM range and verify the selected text before sending a shortcut. Take a screenshot afterward; do not use broad `document.execCommand` calls that can format the entire editor.
- If neither native controls nor a safely bounded page-specific edit is available, report the formatting step as unsupported instead of claiming success.

For framework-controlled `<input>` or `<textarea>` fields, call `fill` first and read the value back. If the installed extension still rejects the field, use only a page-specific fallback: select the exact element, call the matching native prototype value setter, dispatch one bubbling `input` event, and verify the value after the framework rerenders. Do not generalize this fallback to `contenteditable` or custom widgets, and do not hide an extension error.

## Combine browser state with factual lookup

Do not trigger WebBridge for a standalone fact lookup. A factual lookup is appropriate alongside WebBridge when its result is required to complete a stateful browser task, such as obtaining today's Wordle answer or moon phase for a game already open in the user's tab. Use a dedicated search/API for the fact, keep WebBridge for the page interaction, and verify the value before entering it.

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
