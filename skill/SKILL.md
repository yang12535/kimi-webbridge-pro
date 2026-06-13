---
name: kimi-webbridge-pro
description: Control the user's real logged-in browser through the local Kimi WebBridge daemon. Use when the user explicitly requests Kimi WebBridge, or when an agent must operate on the user's existing browser tabs, cookies, sessions, or extensions and no purpose-built connector is more appropriate. Do not use for ordinary factual web research that does not require the user's browser state.
---

# Kimi WebBridge Pro

Control the user's live browser through the daemon at `http://127.0.0.1:10086`.

## Check health

Run the platform status command before sending browser actions:

```powershell
& "$env:USERPROFILE\.kimi-webbridge\bin\kimi-webbridge.exe" status
```

```bash
~/.kimi-webbridge/bin/kimi-webbridge status
```

Proceed only when both `running` and `extension_connected` are `true`. Otherwise read [operations.md](references/operations.md).

## Use the protocol

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

Use [screenshot.ps1](scripts/screenshot.ps1) for screenshots. It accepts both current path-based responses and older base64 responses without flooding context.
For large or unknown pages, use [snapshot.py](scripts/snapshot.py) in `compact` or `file` mode instead of printing the full snapshot response.
Run Python helpers with `py -3` (or `py`) on Windows and `python3` on POSIX. Do not assume `python3` is the Windows launcher.

## Follow one task workflow

1. Assign one stable session name.
2. Use `find_tab` for a user-owned existing tab, or `navigate` with `newTab:true` for a task-owned tab.
3. Take a `snapshot`.
4. Use snapshot `@e` refs with `click` and `fill`.
5. After navigation or a click that should change the page, wait briefly and poll URL/title or snapshot up to three times.
6. Take a new snapshot after a substantial DOM change; old refs may be stale.
7. Close only task-owned tabs when finished.

Do not assume `find_tab` visibly focuses a browser tab. It selects a matching tab for the WebBridge session; `active:true` means prefer the browser's currently active matching tab.
Treat `@e` values as WebBridge snapshot references, not DOM attributes. Do not query them with selectors such as `[data-ref="@e1"]`.

## Recover when the page looks unchanged

1. Compare the returned URL and take a fresh `snapshot`; SPA navigation may update in place.
2. Call `list_tabs`; the destination may be in a background tab.
3. Use `find_tab` to select the destination for the session.
4. If no tab appeared, tell the user the browser may have blocked a popup or new tab. Ask them to allow popups/new windows for that site, then retry once.
5. If a result card has nested click targets, inspect its primary `href` with `evaluate` and navigate directly.

## Preserve user state

- Treat tabs found with `find_tab` as user-owned. Do not close them unless the user explicitly asks.
- Treat tabs created with `navigate newTab:true` as task-owned. Close them when cleanup is appropriate.
- Collect only the page content needed for the task. Treat snapshots, screenshots, PDFs, network captures, and page text as potentially sensitive.
- Do not inspect or return cookies, authorization headers, session tokens, password fields, browser storage, or unrelated private page content.
- Use `network` only when the task specifically requires request-level diagnosis, and avoid collecting authentication headers or unrelated bodies.
- Delete temporary screenshots and PDFs after use unless the user asked to keep them.
- Confirm before sending messages, publishing content, purchasing, deleting, changing permissions, uploading files, or submitting sensitive data.
- Do not bypass CAPTCHAs, paywalls, age gates, browser warnings, or site security controls.
- Report trusted-input and cross-origin iframe limits instead of attempting a workaround.

## Human-only background

Do not read [how-it-works.md](references/how-it-works.md) during normal task execution. It is a high-context design explanation for human maintainers, not an operational dependency.
