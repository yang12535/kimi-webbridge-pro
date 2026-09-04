# Changed

## Unreleased

### Added

- `doctor.py --probe` sends a real `list_tabs` command after the passive checks. A failed probe marks the report not ready with reason `extension connected but command probe failed` and recommends a daemon restart, catching zombie extension connections that `status` cannot detect. `--probe-timeout` is a finite wall-clock deadline (default 10s). The probe runs only when the passive checks are ready, validates the full `list_tabs` response shape, and is marked `skipped` otherwise. Transport, HTTP-body, malformed JSON, invalid UTF-8, and wrong-shape response failures are normalized so doctor still emits a JSON report.
- Added an opt-in Linux systemd user-service installer for current daemons that expose `start --foreground`, including no-change unit preview and uninstall modes.
- Added Linux and Windows GitHub Actions jobs for the full unit/mock-daemon suite, Python compilation, Bash syntax, and ShellCheck.

### Fixed

- Made `invoke.sh` compatible with curl older than 7.76 while preserving non-2xx bodies, curl exit 7/28, and actionable doctor guidance; all JSON argument sources now receive UTF-8/BOM parsing and object-shape validation.
- Gave `navigate` 45 seconds of helper transport headroom while retaining the 30-second default for other actions, so the upstream page-load timeout response is not lost in a client race.
- Made condition-less `wait_for.py` print a machine-readable `condition_required` error on stdout and exit 2; documented complete conditioned examples instead of implying a generic sleep.
- Based snapshot auto-fallback on the final compact-output byte budget (12,000 bytes), removed embedded file-mode previews, pretty-printed inline JSON, preserved the legacy raw threshold option, added chosen-path aliases/metadata/newlines, and corrected exact-limit truncation.
- Replaced shared snapshot/screenshot temp directories with per-invocation private directories.
- Moved the optional `ctypes` import into the Windows process check, warned non-blockingly when daemon/extension versions differ, and detected definite same-root plus conditional cross-root official/Pro skill coexistence.
- Documented `evaluate (code)` in the quick path and helper help, including that `expression` is not the argument key.
- Added bounded recovery guidance for controlled fields, upload `-32000`, and navigation timeouts while marking the remaining daemon/extension behavior as upstream-owned.
- Made Linux autostart install/uninstall transitions serialized and rollback-safe: unknown pre-state aborts before mutation, same-named units from other search paths are not shadowed, cached units are never started after a failed reload, active direct daemons are left untouched for explicit shutdown, effective units are verified before stop/removal, and signal or partial-systemctl failures restore and verify the previous unit and service state where possible.
- Updated installation guidance to use the official POSIX installer's `--no-skill` option when Pro will be installed separately; no existing skill is deleted automatically.
- Documented that broad wildcard `find_tab active:true` calls cannot reliably discover an unknown current tab, and require a known URL/hostname or a dedicated host-agent API instead.
- Documented the version-dependent `mouse_click`, `key_type`, `send_keys`, and high-privilege `cdp` actions observed in extension 1.10.1.
- Added a guarded `Page.bringToFront` activation workflow for known tabs when the installed versions expose `cdp`.
- Avoided unreliable multi-tab focus switching by assigning independent tabs and side lookups to independent WebBridge sessions.
- Clarified that `fill` is plain-text replacement for `contenteditable` targets, while exact-range selection plus version-dependent `send_keys` may support verified editor shortcuts.
- Made PowerShell and Bash example boundaries explicit, including Git Bash on Windows.
- Clarified that factual search may accompany a browser-state task even though a standalone lookup should not trigger WebBridge.
- Added `invoke.sh --args-stdin` and `--args-file -` so Bash callers can send UTF-8 emoji or nested JSON without temporary files.
- Made `invoke.sh` reject interactive stdin waits and empty inline JSON payloads before building a request.
- Documented the version-dependent `find_tab` URL matching contract: current releases should receive a known full URL or hostname, older Chrome-style wildcard behavior must not be assumed, and `list_tabs` only covers session-associated tabs.
- Added an operations runbook row for "extension connected but every action fails" (probe, then restart once), and guidance to prefer upgrading the extension over downgrading the daemon on version mismatch; an unknown version is not proof of being outdated.
- Aligned `doctor.py` readiness `reason` and recommendations when the daemon reports running but its port is unreachable.
- Clamped `doctor.py` and `wait_for.py` polling sleeps to the remaining timeout when `--interval` exceeds `--timeout`, and stopped `wait_for.py` from sending a final snapshot request after the deadline.
- Replaced recursive accessibility-tree walking in `snapshot.py` and `wait_for.py` with iterative traversal to avoid `RecursionError` on deeply nested pages.
- Avoided enqueueing large flat sibling lists in `snapshot.py` compact traversal before the element cap can stop collection.
- Made `invoke.sh` reject simultaneous `--args-json` and `--args-file`, matching the PowerShell helper.
- Preserved daemon error bodies from non-2xx `Invoke-RestMethod` failures in PowerShell helpers across Windows PowerShell and PowerShell 7 response shapes.

### Changed

- Added the GitHub source and issue tracker link to README, the skill entrypoint, and operations troubleshooting docs.

### Validation

- Expanded the suite to cover portable Bash HTTP/error behavior, connection refusal, BOM/malformed/scalar args, forced-close refusal, navigate timeout selection, systemd unit rendering, snapshot budgets/contracts/private directories, exact truncation, condition-required JSON, version warnings, and same-root skill conflicts.
- Added a mock-daemon regression test for UTF-8 emoji and nested JSON streamed to `invoke.sh` over stdin.
- Added regression coverage for empty `--args-json` input.
- Added cross-platform mock-daemon CLI tests for `invoke.sh`, `snapshot.py`, `wait_for.py`, `screenshot.py`, `invoke.ps1`, and `screenshot.ps1`.
- Fixed the mock-daemon test harness on Windows by invoking `invoke.sh` through `bash` and decoding subprocess output as UTF-8.

## v1.0.0 - 2026-06-20

First formal release of Kimi WebBridge Pro as an agent-neutral browser-control skill.

### Added

- PowerShell `invoke.ps1 -ArgsFile` support for UTF-8 JSON argument files, including Chinese text and nested action arguments.
- `snapshot.py --auto` and `--mode auto`, which return compact snapshots for small pages and write large or overfull snapshots to a UTF-8 JSON file.
- Top-level `reason` in `doctor.py` readiness output, plus a `--json` compatibility flag for agents that explicitly request JSON output.
- A quick decision tree in `SKILL.md` for choosing tab ownership, snapshot strategy, argument passing, and post-click recovery flow.
- End-to-end examples under `skill/examples/` for form filling, long-page extraction, popup/background-tab recovery, and network debugging.

### Changed

- Updated protocol and operations guidance to prefer `wait_for.py` plus a fresh snapshot after navigation or state-changing clicks.
- Clarified when to use `snapshot.py --auto`, `--mode compact`, and `--mode file`.
- Documented UTF-8 args-file workflows for both PowerShell and Bash.
- Updated README feature and project-structure sections to reflect the helper and examples layout.

### Validation

- Unit tests: `py -3 -m unittest discover -s tests -v`
- Python script compilation for `skill/scripts/*.py`
- PowerShell parser checks for `skill/scripts/*.ps1`
- Git Bash syntax check for `skill/scripts/invoke.sh`
- `git diff --check`
- `skill-creator` quick validation for `skill/`
- Manual PowerShell dry-run for `invoke.ps1 -ArgsFile` with Chinese and nested JSON

### Deferred

- Daemon-side automatic tab switching after clicks remains outside this skill repository.
- Stitched full-page screenshots are deferred until there is a stable screenshot/scroll contract and an explicit image dependency decision.
