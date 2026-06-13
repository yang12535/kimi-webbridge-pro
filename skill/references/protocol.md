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

For Bash, use a UTF-8 JSON file when arguments contain non-ASCII text or complex quoting:

```bash
printf '%s' '{"selector":"@e10","value":"显卡日报"}' > /tmp/webbridge-args.json
scripts/invoke.sh --session demo --action fill \
  --args-file /tmp/webbridge-args.json
rm -f /tmp/webbridge-args.json
```

Use `snapshot.py` to prevent large snapshot responses from flooding context:

```powershell
# Windows: use the Python launcher
py -3 scripts\snapshot.py --session demo --mode compact
py -3 scripts\snapshot.py --session demo --mode file
```

```bash
# POSIX
# URL, title, headings, and actionable refs only
python3 scripts/snapshot.py --session demo --mode compact

# Full UTF-8 response saved under the system temp directory
python3 scripts/snapshot.py --session demo --mode file
```

`compact` is for locating controls. Use `file` when the task requires article text or other static page content, then read only the relevant portions of that file.
On Windows, prefer `py -3` or `py`; do not assume a `python3` command exists.

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

## Waiting and retrying

- After `navigate` or a click that should change the page, wait about one second, then inspect URL/title or take a new snapshot.
- Retry the observation up to three times with a short delay when the page is still loading.
- Do not blindly repeat the click while waiting. Repeated clicks can open duplicate tabs or submit an action twice.
- If the page remains unchanged, follow the tab and popup recovery flow below.

## Tab and popup behavior

- `find_tab active:true` prefers the currently active matching browser tab; it does not mean "activate this result."
- A click may open a background tab without changing the visible page.
- If `list_tabs` shows no destination tab, the browser may have blocked the popup or new window. Ask the user to allow it for the site before retrying.
- If no tab appears and the clicked element is a link, use `evaluate` to read its real `href`, then call `navigate` directly.
