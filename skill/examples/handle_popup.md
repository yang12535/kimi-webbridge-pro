# Handle Popup or Background Tab

Use this pattern after clicking a link or button that appears to do nothing.

1. Do not repeat the original click immediately.
2. Run `wait_for.py` for the expected URL, title, or visible text.
3. Take a fresh `snapshot.py --auto` and compare URL/title.
4. Call `list_tabs`:

   ```powershell
   & scripts\invoke.ps1 -Session "popup-task" -Action "list_tabs"
   ```

5. If a new destination tab exists, use `find_tab` to select it for the session.
6. If no tab appears, the browser may have blocked a popup or new window. Ask the user to allow popups for that site, then retry once.
7. If the clicked element is a link, recover its real `href` with bounded `evaluate`, then call `navigate` directly.

