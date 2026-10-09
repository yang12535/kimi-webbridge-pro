# Login State and Form Fill

Use this pattern when the user already has a logged-in browser tab and asks the agent to fill a page.

1. Run `doctor.py --wait-connected 20` and proceed only when `ready` is true.
2. Try `find_tab` with the known URL in the existing session. If normal lookup misses, make one foreground lookup before prompting:

   ```powershell
   & scripts\invoke.ps1 -Session "form-task" -Action "find_tab" -ActionArgs @{
     url = "https://example.com/"
     active = $true
   }
   ```

   If both lookups miss, follow the [focus fallback](../references/protocol.md#when-normal-lookup-misses): tell an available user to keep the target active in the last-focused browser window, then retry with a bounded wait. In unattended mode, follow the protocol's auto-mode alternatives instead of indefinitely waiting for a person. The command above makes one attempt; it does not implement a 300-second wait or automatic approval.

3. Take `snapshot.py --auto` and verify the full URL/title before filling; host matching can select a different form on the same site. If it returns `mode=file`, read only the relevant controls or text from the file.
4. Use `fill` with a UTF-8 args file for non-ASCII or nested content:

   ```powershell
   @'
   {"selector":"@e10","value":"显卡日报：RTX 5090 价格"}
   '@ | Set-Content -LiteralPath .\args.json -Encoding UTF8
   & scripts\invoke.ps1 -Session "form-task" -Action "fill" -ArgsFile .\args.json
   ```

5. Before submitting, ask the user to confirm when the action sends, publishes, purchases, deletes, or changes permissions.
