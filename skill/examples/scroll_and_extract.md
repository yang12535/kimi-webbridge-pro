# Scroll and Extract Long Content

Use this pattern for articles, long documentation pages, and pages where compact snapshots omit important static text.

1. Start with `snapshot.py --auto`.
2. If the result is compact but the task needs article/body text, rerun:

   ```powershell
   py -3 scripts\snapshot.py --session "article-task" --mode file
   ```

3. Read only the relevant sections of the saved UTF-8 JSON file. Do not paste the whole file into the conversation.
4. For lazy-loaded pages, scroll in bounded steps, wait briefly, then take a fresh file snapshot:

   ```powershell
   & scripts\invoke.ps1 -Session "article-task" -Action "evaluate" -ArgsFile .\scroll.json
   py -3 scripts\wait_for.py --session "article-task" --text-contains "expected text" --timeout 10
   py -3 scripts\snapshot.py --session "article-task" --mode file
   ```

   Example `scroll.json`:

   ```json
   {
     "code": "(() => { window.scrollBy({ top: 900, behavior: 'instant' }); return { scrollY: window.scrollY, height: document.documentElement.scrollHeight }; })()"
   }
   ```

5. For visual evidence, use `screenshot.py` at the current scroll position. Stitching full-page images requires an image library and is intentionally not assumed by the base skill.

