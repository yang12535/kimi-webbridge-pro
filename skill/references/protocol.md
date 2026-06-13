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

- Click a submit button directly when possible. Use `evaluate` for special key events because there is no dedicated keypress action.
- Top-frame actions cannot access cross-origin iframe contents. Navigate to the iframe URL directly when appropriate.

## Tab and popup behavior

- `find_tab active:true` prefers the currently active matching browser tab; it does not mean "activate this result."
- A click may open a background tab without changing the visible page.
- If `list_tabs` shows no destination tab, the browser may have blocked the popup or new window. Ask the user to allow it for the site before retrying.
