# Operations

Read this file when Kimi WebBridge is missing, stopped, disconnected, timing out, or behaving inconsistently.

## Status routing

Prefer the no-action doctor when it is available:

```powershell
py -3 scripts\doctor.py --wait-connected 20
```

```bash
python3 scripts/doctor.py --wait-connected 20
```

`doctor.py` checks the binary path, daemon status, `127.0.0.1:10086`, `daemon.pid`, and extension connection. It always prints JSON and accepts `--json` as an explicit compatibility flag for agents that require one. It does not send browser actions unless `--probe` is passed. It starts the daemon only when `--start` is explicitly passed.

Run:

```powershell
& "$env:USERPROFILE\.kimi-webbridge\bin\kimi-webbridge.exe" status
```

```bash
~/.kimi-webbridge/bin/kimi-webbridge status
```

| Observed state | Action |
|---|---|
| Binary missing | If the user asked to install it, use the official installer. Otherwise confirm before running downloaded code. |
| `running: false` | Use `doctor.py --start --wait-connected 20` when starting is appropriate. This delegates stale-PID handling to the daemon before any manual PID-file cleanup. |
| `running: true`, `extension_connected: false` | Wait briefly with `doctor.py --wait-connected 20`; if still disconnected, ask the user to open the browser and verify that the [Kimi WebBridge extension](https://chromewebstore.google.com/detail/kimi-webbridge/fldmhceldgbpfpkbgopacenieobmligc?pli=1) is installed and enabled. |
| Both fields are `true` | Return to `SKILL.md` and send browser commands. |

## Post-install verification

Use the readiness smoke test after installing or updating the skill. It checks the local daemon and lists tabs without opening, closing, or modifying browser pages.

PowerShell:

```powershell
py -3 scripts\doctor.py --wait-connected 20
& scripts\invoke.ps1 -Session "kimi-webbridge-pro-smoke" -Action "list_tabs"
```

POSIX:

```bash
python3 scripts/doctor.py --wait-connected 20
scripts/invoke.sh --session kimi-webbridge-pro-smoke --action list_tabs
```

If `extension_connected` remains false, open the browser and confirm the Kimi WebBridge extension is installed and enabled, then rerun the readiness smoke test. Run page-changing smoke tests only when you intentionally want to open a task-owned tab.

Interpret the doctor report as follows:

- `ready: true`: the daemon is running, the extension is connected, and the daemon port is reachable.
- `reason`: a short machine-readable readiness summary such as `ready`, `daemon not running`, `extension not connected`, or `daemon port not reachable`.
- `ready: false` with `status.running: false`: start the daemon, or use `doctor.py --start --wait-connected 20` when starting it is appropriate.
- `ready: false` with `status.running: true` and `status.extension_connected: false`: open Chrome, install or enable the extension, and rerun `doctor.py`.
- `pid_file.stale: true`: first use `doctor.py --start --wait-connected 20`; remove `daemon.pid` manually only if startup still fails and the recorded process is verified gone.
- `skill_conflicts[].scope: "same_root"`: the official and Pro skills definitely coexist in one root. Prefer Pro for helper-driven workflows and decide explicitly whether the official copy is still needed.
- `skill_conflicts[].scope: "multiple_roots"`: both names exist across known roots. Treat this as conditional because the roots may belong to different Agents; act only if the current Agent loads both.

Prerequisite links:

- Kimi WebBridge Pro source and issue tracker: `https://github.com/yang12535/kimi-webbridge-pro`
- Kimi WebBridge documentation and daemon setup: `https://www.kimi.com/zh-cn/features/webbridge`
- Chrome Web Store extension: `https://chromewebstore.google.com/detail/kimi-webbridge/fldmhceldgbpfpkbgopacenieobmligc?pli=1`

Official installers:

```powershell
irm https://cdn.kimi.com/webbridge/install.ps1 | iex
```

```bash
curl -fsSL https://cdn.kimi.com/webbridge/install.sh | bash -s -- --no-skill
```

The current POSIX installer otherwise installs the official `kimi-webbridge` skill as well as the daemon. When installing this Pro skill separately, pass `--no-skill` to avoid an ambiguous same-root duplicate. This option does not remove an existing official skill.

## Linux login autostart

Current v2 daemon builds expose `start --foreground`, so Linux users can opt into a supervised systemd user service without root:

```bash
# Inspect the exact unit first; this makes no changes.
scripts/install_linux_autostart.sh --print-unit

# Install, enable, and start ~/.config/systemd/user/kimi-webbridge.service.
scripts/install_linux_autostart.sh
```

The helper refuses older binaries that do not advertise `start --foreground`. Upgrade through the official installer before enabling the unit. Remove the service with `scripts/install_linux_autostart.sh --uninstall`. A user service starts at login (`default.target`); the upstream daemon remains responsible for cleaning its PID file on exit.

## Lifecycle commands

| Operation | Windows | POSIX |
|---|---|---|
| Status | `& "$env:USERPROFILE\.kimi-webbridge\bin\kimi-webbridge.exe" status` | `~/.kimi-webbridge/bin/kimi-webbridge status` |
| Start | `& "$env:USERPROFILE\.kimi-webbridge\bin\kimi-webbridge.exe" start` | `~/.kimi-webbridge/bin/kimi-webbridge start` |
| Stop | `& "$env:USERPROFILE\.kimi-webbridge\bin\kimi-webbridge.exe" stop` | `~/.kimi-webbridge/bin/kimi-webbridge stop` |
| Restart | `& "$env:USERPROFILE\.kimi-webbridge\bin\kimi-webbridge.exe" restart` | `~/.kimi-webbridge/bin/kimi-webbridge restart` |
| Recent logs | `& "$env:USERPROFILE\.kimi-webbridge\bin\kimi-webbridge.exe" logs -n 100` | `~/.kimi-webbridge/bin/kimi-webbridge logs -n 100` |
| Previous logs | `& "$env:USERPROFILE\.kimi-webbridge\bin\kimi-webbridge.exe" logs --prev` | `~/.kimi-webbridge/bin/kimi-webbridge logs --prev` |
| Doctor | `py -3 scripts\doctor.py --wait-connected 20` | `python3 scripts/doctor.py --wait-connected 20` |

## Diagnose failures

| Symptom | Action |
|---|---|
| Address already in use | Stop, then start. If it persists, identify the process listening on port `10086`. |
| Commands time out | Read recent logs for error or panic messages, then retry once after a restart. |
| Bash helper exits 7 | The daemon is unreachable. Run `doctor.py --start --wait-connected 20`; the helper preserves curl exit 7. |
| Bash helper exits 28 | The request exceeded its client deadline. Run `doctor.py --probe` before retrying; the helper preserves curl exit 28. |
| Bash helper exits 22 | The daemon returned non-2xx HTTP. The response body is preserved for diagnosis, including on curl versions older than 7.76. |
| Extension remains disconnected | Open the browser, install or enable the Chrome Web Store extension, and retry status. |
| Extension is connected but actions fail | Read logs for version, multi-browser, or extension-upgrade errors. |
| Extension connected but every action fails or times out | Run `doctor.py --probe` to confirm, then restart the daemon once (`kimi-webbridge restart`) and retry. The extension WebSocket can be a zombie that `status` cannot detect. |
| The error asks for an extension update | Update the extension from the Chrome Web Store link above; do not repeatedly retry the action. |
| An action returns `Unknown tool` | Treat it as unavailable in the installed daemon/extension pair. Check both versions and update through official channels before retrying once; do not silently replace it with unrestricted `evaluate` or `cdp`. |

`status.extension_id` may differ from the Chrome Web Store URL ID. Treat `doctor.py`'s `ready` result as the authoritative readiness signal because it includes daemon status, extension connectivity, and the `127.0.0.1:10086` port probe; use the ID only as supporting diagnostic context.

When the current v2 daemon reports `version_mismatch`, use `kimi-webbridge upgrade` without a version while that extension is connected. The official command deliberately installs the daemon release matching the browser-store extension, even when that is numerically older; exact protocol alignment is the target. A pinned `upgrade vX.Y.Z` may move in either direction. An unknown or unparsed version is not proof of being outdated.

When daemon and extension versions differ, doctor emits a non-blocking alignment recommendation. Version-sensitive actions such as upload should be retried only once after alignment. If telemetry DEBUG heartbeats dominate upstream daemon logs, filter for WebSocket, error, panic, and action lines while diagnosing; changing the daemon's default telemetry log level is outside this skill repository.

## Recover a stale PID

First run `doctor.py --start --wait-connected 20`; current daemon builds handle a verified stale PID on their normal start path. Delete `daemon.pid` manually only if startup still fails and the recorded process no longer exists. Never remove it merely because a start command failed.

```powershell
$pidFile = "$env:USERPROFILE\.kimi-webbridge\daemon.pid"
$daemonPid = [int](Get-Content -Raw -LiteralPath $pidFile)
$daemonProcess = Get-Process -Id $daemonPid -ErrorAction SilentlyContinue
if ($null -eq $daemonProcess) {
  Remove-Item -LiteralPath $pidFile
  & "$env:USERPROFILE\.kimi-webbridge\bin\kimi-webbridge.exe" start
}
```

```bash
pid_file="$HOME/.kimi-webbridge/daemon.pid"
daemon_pid="$(cat "$pid_file")"
if ! kill -0 "$daemon_pid" 2>/dev/null; then
  rm -- "$pid_file"
  "$HOME/.kimi-webbridge/bin/kimi-webbridge" start
fi
```

If the PID still resolves to a process, inspect that process and logs instead of deleting the file.
