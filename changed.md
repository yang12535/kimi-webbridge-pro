# Changed

## Unreleased

### Fixed

- Aligned `doctor.py` readiness `reason` and recommendations when the daemon reports running but its port is unreachable.
- Clamped `doctor.py` and `wait_for.py` polling sleeps to the remaining timeout when `--interval` exceeds `--timeout`, and stopped `wait_for.py` from sending a final snapshot request after the deadline.
- Replaced recursive accessibility-tree walking in `snapshot.py` and `wait_for.py` with iterative traversal to avoid `RecursionError` on deeply nested pages.
- Made `invoke.sh` reject simultaneous `--args-json` and `--args-file`, matching the PowerShell helper.
- Preserved daemon error bodies from non-2xx `Invoke-RestMethod` failures in PowerShell helpers across Windows PowerShell and PowerShell 7 response shapes.

### Validation

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
