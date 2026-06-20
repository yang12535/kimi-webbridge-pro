# Command Protocol

Use `POST http://127.0.0.1:10086/command` with JSON:

```json
{
  "action": "navigate",
  "args": {
    "url": "https://example.com",
    "newTab": true
  },
  "session": "example-task"
}
```

Keep `session` at the top level and reuse one session name for the task.

## Helper scripts

PowerShell accepts a hashtable directly:

```powershell
& scripts\invoke.ps1 -Session "demo" -Action "fill" -ActionArgs @{
  selector = "@e10"
  value = "显卡日报"
}
```

For PowerShell, use a UTF-8 JSON file when arguments contain non-ASCII text, nested objects, or complex quoting:

```powershell
@'
{
  "selector": "@e10",
  "value": "显卡日报：RTX 5090 价格"
}
'@ | Set-Content -LiteralPath .\webbridge-args.json -Encoding UTF8
& scripts\invoke.ps1 -Session "demo" -Action "fill" -ArgsFile .\webbridge-args.json
Remove-Item -LiteralPath .\webbridge-args.json
```

For Bash, use a UTF-8 JSON file when arguments contain non-ASCII text or complex quoting:

```bash
printf '%s' '{"selector":"@e10","value":"显卡日报"}' > /tmp/webbridge-args.json
scripts/invoke.sh --session demo --action fill \
  --args-file /tmp/webbridge-args.json
rm -f /tmp/webbridge-args.json
```

Both invoke helpers support a no-request payload check:

```powershell
& scripts\invoke.ps1 -Session demo -Action fill -ActionArgs @{
  selector = "@e10"
  value = "显卡日报"
} -DryRun
```

```powershell
& scripts\invoke.ps1 -Session demo -Action fill -ArgsFile .\webbridge-args.json -DryRun
```

```bash
scripts/invoke.sh --session demo --action fill \
  --args-file /tmp/webbridge-args.json --dry-run
```

Use `snapshot.py` to prevent large snapshot responses from flooding context:

```powershell
# Windows: use the Python launcher
py -3 scripts\snapshot.py --session demo --auto
py -3 scripts\snapshot.py --session demo --mode compact
py -3 scripts\snapshot.py --session demo --mode file
```

```bash
# POSIX
# Auto: compact for small pages, file path for large pages
python3 scripts/snapshot.py --session demo --auto

# URL, title, headings, and actionable refs only
python3 scripts/snapshot.py --session demo --mode compact

# Full UTF-8 response saved under the system temp directory
python3 scripts/snapshot.py --session demo --mode file
```

`auto` is the recommended first choice for unfamiliar pages: it returns compact output for small snapshots and writes large or overfull snapshots to a UTF-8 JSON file. `compact` is for locating controls. Use `file` when the task requires article text or other static page content, then read only the relevant portions of that file.
On Windows, prefer `py -3` or `py`; do not assume a `python3` command exists.
The Python helpers configure UTF-8 stdout themselves. If an older shell still renders mojibake, use `--mode file` and read the UTF-8 file instead.

Use the cross-platform screenshot helper:

```powershell
py -3 scripts\screenshot.py --session demo
```

```bash
python3 scripts/screenshot.py --session demo
```

Wait for an expected URL, title, or visible accessibility text:

```powershell
py -3 scripts\wait_for.py --session demo `
  --url-contains "zhuanlan.zhihu.com" --timeout 10
py -3 scripts\wait_for.py --session demo `
  --text-contains "已保存" --timeout 10
```

```bash
python3 scripts/wait_for.py --session demo \
  --url-contains "zhuanlan.zhihu.com" --timeout 10
python3 scripts/wait_for.py --session demo \
  --text-contains "Saved" --timeout 10
```

`wait_for.py` accepts these condition flags:

| Flag | Meaning |
|---|---|
| `--url-contains` | Current tab URL contains the value. |
| `--title-contains` | Current tab title contains the value. |
| `--text-contains` | Accessibility tree text contains the value. |
| `--visible-text` | Alias for `--text-contains`; prefer `--text-contains` in docs. |

## Actions

| Action | Arguments | Purpose |
|---|---|---|
| `navigate` | `url`, `newTab`, optional `group_title` | Navigate the selected tab or create a task-owned tab. |
| `find_tab` | `url`, optional `active` | Select an existing matching tab for the session. |
| `list_tabs` | none | Inspect tabs associated with the session. |
| `snapshot` | none | Read URL, title, accessibility tree, and `@e` refs. |
| `click` | `selector` | Click an `@e` ref or CSS selector. |
| `fill` | `selector`, `value` | Replace text in inputs, textareas, or contenteditable editors. |
| `evaluate` | `code` | Read attributes or perform unsupported page logic. |
| `screenshot` | `format`, optional `quality`, optional `selector` | Capture the page or one element. Current daemons return a file path; older builds may return base64. Use the helper script. |
| `network` | `cmd`, optional `filter`, optional `requestId` | Start, stop, list, or inspect captured network traffic. |
| `upload` | `selector`, `files` | Upload confirmed local files. |
| `save_as_pdf` | optional print settings and `file_name` | Render the current page as a PDF. |
| `close_tab` | none | Close the selected task-owned tab. |
| `close_session` | none | Close all tabs associated with the session. Use only when every tab is task-owned. |

## Privacy constraints

- Request only the minimum snapshot, screenshot, PDF, evaluation result, or network data needed for the task.
- Never use `evaluate` to read cookies, password values, authentication tokens, browser storage, or unrelated private page state.
- Treat network headers and bodies as sensitive. Do not collect `Cookie`, `Set-Cookie`, `Authorization`, or token-bearing payloads.
- Keep large or sensitive artifacts on disk rather than returning their contents in command output.
- Remove temporary artifacts after inspection unless the user requested a retained file.

### Advanced action privacy

- Use `upload` only for local files the user explicitly confirmed. Do not construct hidden upload requests.
- Treat `save_as_pdf` outputs as sensitive artifacts. Delete temporary PDFs after use unless the user asked to keep them.
- Use `network` only for task-scoped diagnosis. Filter narrowly and avoid unrelated request bodies.

## Interaction rules

- Prefer snapshot refs over CSS selectors.
- Snapshot refs such as `@e10` are WebBridge references, not DOM attributes. They work with `click` and `fill`, but selectors such as `[data-ref="@e10"]` usually do not exist.
- Refresh the snapshot after navigation or major DOM changes.
- Treat `click` and `fill` as synthetic DOM events. Sites requiring `event.isTrusted` may reject them.
- Treat `fill` as clear-and-replace. Read and concatenate the existing value before filling when appending.
- Wrap repeated `evaluate` code in an IIFE to avoid top-level `const` or `let` redeclaration:

```javascript
(() => {
  const link = document.querySelector("a");
  return link?.href ?? null;
})()
```

- To recover a link when an `@e` click does not navigate, locate the DOM link by stable visible text or another real attribute and return only its URL:

```javascript
(() => {
  const link = Array.from(document.querySelectorAll("a"))
    .find((item) => item.textContent?.includes("显卡日报"));
  return link?.href ?? null;
})()
```

- Click a submit button directly when possible. Use `evaluate` for special key events because there is no dedicated keypress action.
- Top-frame actions cannot access cross-origin iframe contents. Navigate to the iframe URL directly when appropriate.
- For long pages, scroll in bounded steps and take a fresh snapshot afterward:

```javascript
(() => {
  window.scrollBy({ top: 800, behavior: "instant" });
  return { scrollY: window.scrollY, height: document.documentElement.scrollHeight };
})()
```

## Waiting and retrying

- After `navigate` or a click that should change the page, run `wait_for.py` for the expected URL, title, or visible text; then take a fresh snapshot and inspect URL/title.
- Retry the observation up to three times with a short delay when the page is still loading.
- Do not blindly repeat the click while waiting. Repeated clicks can open duplicate tabs or submit an action twice.
- If the page remains unchanged, follow the tab and popup recovery flow below.
- `wait_for.py` polls snapshots and exits nonzero on timeout; it does not repeat the original click.

## Tab and popup behavior

- `find_tab active:true` prefers the currently active matching browser tab; it does not mean "activate this result."
- A click may open a background tab without changing the visible page.
- **If `list_tabs` shows no destination tab, the browser may have blocked the popup or new window. Ask the user to allow it for the site before retrying.**
- If no tab appears and the clicked element is a link, use `evaluate` to read its real `href`, then call `navigate` directly.

## Closing sessions safely

The invoke helpers require an explicit force flag for `close_session`:

```powershell
& scripts\invoke.ps1 -Session demo -Action close_session -Force
```

```bash
scripts/invoke.sh --session demo --action close_session --force
```

Before forcing the close, call `list_tabs` and verify that every listed tab was created for the task. Prefer `close_tab` when ownership is mixed or uncertain.

## Local web app smoke-test recipe

For localhost apps where the task owns a fresh tab:

1. Run `doctor.py --wait-connected 20`; proceed only when ready.
2. Call `navigate` with `newTab:true` and a stable `group_title`.
3. Take `snapshot.py --mode compact` and use `@e` refs for login, edit, or toolbar controls.
4. After every click that should open a modal or update an SPA, call `wait_for.py --text-contains ...` or take a fresh compact snapshot.
5. Use `evaluate` only for bounded state checks such as `location.href`, modal class names, title text, or console error arrays.
6. Call `list_tabs`; if the selected tab is task-owned, close it with `close_tab`. Use forced `close_session` only for advanced batch cleanup after verifying every session tab is task-owned.
