# Login State and Form Fill

Use this pattern when the user already has a logged-in browser tab and asks the agent to fill a page.

1. Run `doctor.py --wait-connected 20` and proceed only when `ready` is true.
2. Attach to the existing tab:

   ```powershell
   & scripts\invoke.ps1 -Session "form-task" -Action "find_tab" -ActionArgs @{
     url = "example.com"
     active = $true
   }
   ```

3. Take `snapshot.py --auto`. If it returns `mode=file`, read only the relevant controls or text from the file.
4. Use `fill` with a UTF-8 args file for non-ASCII or nested content:

   ```powershell
   @'
   {"selector":"@e10","value":"显卡日报：RTX 5090 价格"}
   '@ | Set-Content -LiteralPath .\args.json -Encoding UTF8
   & scripts\invoke.ps1 -Session "form-task" -Action "fill" -ArgsFile .\args.json
   ```

5. Before submitting, ask the user to confirm when the action sends, publishes, purchases, deletes, or changes permissions.

