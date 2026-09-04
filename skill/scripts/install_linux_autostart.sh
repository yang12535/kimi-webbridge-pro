#!/usr/bin/env bash

set -euo pipefail

mode="install"
mode_set=false
binary="${KIMI_WEBBRIDGE_BINARY:-$HOME/.kimi-webbridge/bin/kimi-webbridge}"

usage() {
  cat <<'EOF'
Usage: install_linux_autostart.sh [--binary PATH] [--print-unit | --uninstall]

Install or remove a systemd user service for Kimi WebBridge on Linux.
The installed daemon must support `start --foreground` (current v2 releases do).
The helper requires systemctl, flock, and Python 3. No root privileges are required.
EOF
}

while (($#)); do
  case "$1" in
    --binary)
      binary="${2:?missing binary path}"
      shift 2
      ;;
    --print-unit)
      if [[ "$mode_set" == true ]]; then
        echo "Use only one of --print-unit or --uninstall." >&2
        exit 2
      fi
      mode="print"
      mode_set=true
      shift
      ;;
    --uninstall)
      if [[ "$mode_set" == true ]]; then
        echo "Use only one of --print-unit or --uninstall." >&2
        exit 2
      fi
      mode="uninstall"
      mode_set=true
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

unit_dir="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
unit_file="$unit_dir/kimi-webbridge.service"
managed_marker="# Managed by kimi-webbridge-pro install_linux_autostart.sh"

if [[ "$binary" != /* ]]; then
  echo "Binary path must be absolute: $binary" >&2
  exit 2
fi
if [[ "$binary" == *%* || "$binary" == *'$'* || "$binary" == *'"'* || "$binary" == *\\* || "$binary" == *$'\n'* || "$binary" == *$'\r'* ]]; then
  echo "Binary path contains characters that are unsafe in a systemd ExecStart directive." >&2
  exit 2
fi

render_unit() {
  cat <<EOF
$managed_marker
[Unit]
Description=Kimi WebBridge daemon
After=graphical-session.target

[Service]
Type=simple
ExecStart="$binary" start --foreground
Restart=on-failure
RestartSec=3

[Install]
WantedBy=default.target
EOF
}

if [[ "$mode" == "print" ]]; then
  render_unit
  exit 0
fi

if [[ "$unit_dir" != /* ]]; then
  echo "XDG_CONFIG_HOME must resolve to an absolute path; no changes were made." >&2
  exit 2
fi
[[ "$(uname -s)" == "Linux" ]] || {
  echo "systemd user autostart is supported only on Linux." >&2
  exit 1
}
command -v systemctl >/dev/null 2>&1 || {
  echo "systemctl is required for Linux user autostart." >&2
  exit 1
}
command -v flock >/dev/null 2>&1 || {
  echo "flock is required to serialize Linux autostart changes." >&2
  exit 1
}
probe_service_active() {
  local state rc
  set +e
  state="$(systemctl --user is-active kimi-webbridge.service 2>/dev/null)"
  rc=$?
  set -e
  case "$state:$rc" in
    active:0) return 0 ;;
    inactive:3|inactive:4|failed:3|unknown:4) return 1 ;;
    *)
      echo "Could not determine whether kimi-webbridge.service is active; no changes were made." >&2
      exit 1
      ;;
  esac
}

service_is_definitely_inactive() {
  local state rc
  set +e
  state="$(systemctl --user is-active kimi-webbridge.service 2>/dev/null)"
  rc=$?
  set -e
  case "$state:$rc" in
    inactive:3|inactive:4|failed:3|unknown:4) return 0 ;;
    *) return 1 ;;
  esac
}

service_is_definitely_active() {
  local state rc
  set +e
  state="$(systemctl --user is-active kimi-webbridge.service 2>/dev/null)"
  rc=$?
  set -e
  [[ "$state" == "active" && "$rc" == 0 ]]
}

probe_service_enabled() {
  local state rc
  set +e
  state="$(systemctl --user is-enabled kimi-webbridge.service 2>/dev/null)"
  rc=$?
  set -e
  case "$state:$rc" in
    enabled:0) probed_enable_state="enabled" ;;
    enabled-runtime:0) probed_enable_state="enabled-runtime" ;;
    disabled:1) probed_enable_state="disabled" ;;
    *)
      echo "Could not determine whether kimi-webbridge.service is enabled; no changes were made." >&2
      exit 1
      ;;
  esac
}

service_has_enable_state() {
  local expected="$1"
  local state rc
  set +e
  state="$(systemctl --user is-enabled kimi-webbridge.service 2>/dev/null)"
  rc=$?
  set -e
  case "$expected:$state:$rc" in
    enabled:enabled:0|enabled-runtime:enabled-runtime:0|disabled:disabled:1) return 0 ;;
    absent:not-found:1|absent:disabled:1) return 0 ;;
    *) return 1 ;;
  esac
}

verify_loaded_unit() {
  local fragment fragment_rc dropins dropins_rc expected_fragment
  set +e
  fragment="$(systemctl --user show kimi-webbridge.service --property=FragmentPath --value 2>/dev/null)"
  fragment_rc=$?
  dropins="$(systemctl --user show kimi-webbridge.service --property=DropInPaths --value 2>/dev/null)"
  dropins_rc=$?
  set -e
  expected_fragment="$(readlink -f -- "$unit_file" 2>/dev/null || true)"
  [[ "$fragment_rc" == 0 && "$dropins_rc" == 0 && -n "$expected_fragment" && "$fragment" == "$expected_fragment" && -z "$dropins" ]]
}

verify_no_loaded_unit() {
  local fragment fragment_rc dropins dropins_rc
  set +e
  fragment="$(systemctl --user show kimi-webbridge.service --property=FragmentPath --value 2>/dev/null)"
  fragment_rc=$?
  dropins="$(systemctl --user show kimi-webbridge.service --property=DropInPaths --value 2>/dev/null)"
  dropins_rc=$?
  set -e
  [[ "$fragment_rc" == 0 && "$dropins_rc" == 0 && -z "$fragment" && -z "$dropins" ]]
}

verify_no_competing_loaded_unit() {
  local fragment fragment_rc dropins dropins_rc expected_fragment
  set +e
  fragment="$(systemctl --user show kimi-webbridge.service --property=FragmentPath --value 2>/dev/null)"
  fragment_rc=$?
  dropins="$(systemctl --user show kimi-webbridge.service --property=DropInPaths --value 2>/dev/null)"
  dropins_rc=$?
  set -e
  expected_fragment="$(readlink -m -- "$unit_file")"
  [[ "$fragment_rc" == 0 && "$dropins_rc" == 0 && -z "$dropins" && ( -z "$fragment" || "$fragment" == "$expected_fragment" ) ]]
}

require_no_competing_unit() {
  local fragment fragment_rc dropins dropins_rc
  set +e
  fragment="$(systemctl --user show kimi-webbridge.service --property=FragmentPath --value 2>/dev/null)"
  fragment_rc=$?
  dropins="$(systemctl --user show kimi-webbridge.service --property=DropInPaths --value 2>/dev/null)"
  dropins_rc=$?
  set -e
  if [[ "$fragment_rc" != 0 || "$dropins_rc" != 0 ]]; then
    echo "Could not determine whether another kimi-webbridge.service is already loaded; no changes were made." >&2
    return 1
  fi
  if [[ -n "$fragment" || -n "$dropins" ]]; then
    echo "Refusing to shadow a kimi-webbridge.service loaded from another systemd search path; no changes were made." >&2
    return 1
  fi
}

parse_daemon_running() {
  python3 -c '
import json
import sys

try:
    payload = json.load(sys.stdin)
except (json.JSONDecodeError, UnicodeDecodeError):
    raise SystemExit(1)
if not isinstance(payload, dict) or type(payload.get("running")) is not bool:
    raise SystemExit(1)
sys.stdout.write("true" if payload["running"] else "false")
'
}

if [[ "$mode" == "uninstall" && ! -e "$unit_file" && ! -L "$unit_file" && ! -d "$unit_dir" ]]; then
  if ! verify_no_loaded_unit || ! service_is_definitely_inactive || ! service_has_enable_state absent; then
    echo "A same-named unit, enabled state, or active runtime remains although the managed unit file is missing; refusing to report a successful uninstall." >&2
    exit 1
  fi
  echo "No managed unit is installed at $unit_file"
  exit 0
fi
mkdir -p -- "$unit_dir"
exec {autostart_lock_fd}< "$unit_dir"
if ! flock -n "$autostart_lock_fd"; then
  echo "Another Kimi WebBridge autostart change is already in progress." >&2
  exit 1
fi

if [[ "$mode" == "uninstall" ]]; then
  if [[ ! -e "$unit_file" && ! -L "$unit_file" ]]; then
    if ! verify_no_loaded_unit || ! service_is_definitely_inactive || ! service_has_enable_state absent; then
      echo "A same-named unit, enabled state, or active runtime remains although the managed unit file is missing; refusing to report a successful uninstall." >&2
      exit 1
    fi
    echo "No managed unit is installed at $unit_file"
    exit 0
  fi
  if [[ -L "$unit_file" || ! -f "$unit_file" ]] || ! grep -Fqx -- "$managed_marker" "$unit_file"; then
    echo "Refusing to remove an unmanaged or non-regular unit: $unit_file" >&2
    exit 1
  fi
  if grep -Eq '^[[:space:]]*(Also|Alias)[[:space:]]*=' "$unit_file"; then
    echo "Refusing to remove a managed unit with additional install targets or aliases: $unit_file" >&2
    exit 1
  fi
  uninstall_enable_state=""
  uninstall_was_active=false
  probe_service_enabled
  uninstall_enable_state="$probed_enable_state"
  if probe_service_active; then
    uninstall_was_active=true
  fi
  if ! systemctl --user daemon-reload; then
    echo "Failed to reload the systemd user manager before uninstall; no service state or files were changed." >&2
    exit 1
  fi
  if ! verify_loaded_unit; then
    echo "Refusing to stop the service because systemd did not load the exact managed unit or reported active drop-ins." >&2
    exit 1
  fi

  disable_uninstall_unit() {
    if [[ "$uninstall_enable_state" == "enabled-runtime" ]]; then
      systemctl --user disable --runtime --now kimi-webbridge.service
    else
      systemctl --user disable --now kimi-webbridge.service
    fi
  }

  restore_uninstall_state() {
    local restored=true
    local runtime_inactive=true
    systemctl --user stop kimi-webbridge.service >/dev/null 2>&1 || true
    if ! service_is_definitely_inactive; then
      runtime_inactive=false
      restored=false
    fi
    case "$uninstall_enable_state" in
      enabled)
        systemctl --user enable kimi-webbridge.service || true
        service_has_enable_state enabled || restored=false
        ;;
      enabled-runtime)
        systemctl --user enable --runtime kimi-webbridge.service || true
        service_has_enable_state enabled-runtime || restored=false
        ;;
      disabled)
        systemctl --user disable kimi-webbridge.service || true
        service_has_enable_state disabled || restored=false
        ;;
    esac
    if [[ "$uninstall_was_active" == true ]]; then
      if [[ "$runtime_inactive" == true ]]; then
        systemctl --user start kimi-webbridge.service || true
      fi
      if [[ "$runtime_inactive" != true ]] || ! service_is_definitely_active; then
        restored=false
      fi
    elif ! service_is_definitely_inactive; then
      restored=false
    fi
    [[ "$restored" == true ]]
  }

  uninstall_backup="$(mktemp "$unit_file.uninstall.XXXXXX")"
  rollback_uninstall() {
    local files_restored=true
    local manager_reloaded=true
    local state_restored=true
    local backup_cleaned=true
    local transition_source_safe=true
    if [[ ! -e "$unit_file" && ! -L "$unit_file" ]]; then
      if ! verify_no_competing_loaded_unit; then
        transition_source_safe=false
      fi
      if [[ -f "$uninstall_backup" ]] && mv -- "$uninstall_backup" "$unit_file"; then
        if ! systemctl --user daemon-reload; then
          manager_reloaded=false
        fi
      else
        files_restored=false
        manager_reloaded=false
      fi
    else
      rm -f -- "$uninstall_backup" || backup_cleaned=false
    fi
    if [[ "$files_restored" == true && "$manager_reloaded" == true ]] && ! verify_loaded_unit; then
      manager_reloaded=false
    fi
    if [[ "$files_restored" == true && "$manager_reloaded" == true && "$transition_source_safe" == true ]]; then
      if ! restore_uninstall_state; then
        state_restored=false
      fi
    else
      state_restored=false
    fi
    [[ "$files_restored" == true && "$manager_reloaded" == true && "$state_restored" == true && "$backup_cleaned" == true && "$transition_source_safe" == true ]]
  }

  # shellcheck disable=SC2317  # Invoked asynchronously by the signal trap.
  interrupt_uninstall() {
    trap '' HUP INT TERM
    if rollback_uninstall >/dev/null 2>&1; then
      echo "Autostart uninstall was interrupted; the previous unit and service state were restored." >&2
    else
      echo "Autostart uninstall was interrupted and automatic restoration was incomplete; inspect $unit_file and the user service state." >&2
    fi
    exit 1
  }
  trap interrupt_uninstall HUP INT TERM

  if ! disable_uninstall_unit; then
    trap '' HUP INT TERM
    restored=true
    if ! rollback_uninstall; then
      restored=false
    fi
    echo "Refusing to remove the unit because systemctl could not disable and stop the service." >&2
    if [[ "$restored" != true ]]; then
      echo "Warning: systemctl partially changed the service and automatic restoration was incomplete." >&2
    fi
    exit 1
  fi
  if ! service_is_definitely_inactive; then
    trap '' HUP INT TERM
    restored=true
    if ! rollback_uninstall; then
      restored=false
    fi
    echo "Refusing to remove the unit because the service could not be confirmed inactive after disable." >&2
    if [[ "$restored" != true ]]; then
      echo "Warning: systemctl partially changed the service and automatic restoration was incomplete." >&2
    fi
    exit 1
  fi
  if ! service_has_enable_state disabled; then
    trap '' HUP INT TERM
    restored=true
    if ! rollback_uninstall; then
      restored=false
    fi
    echo "Refusing to remove the unit because the service could not be confirmed disabled." >&2
    if [[ "$restored" != true ]]; then
      echo "Warning: systemctl partially changed the service and automatic restoration was incomplete." >&2
    fi
    exit 1
  fi
  if ! mv -- "$unit_file" "$uninstall_backup"; then
    trap '' HUP INT TERM
    rollback_uninstall >/dev/null 2>&1 || true
    echo "Failed to stage the managed unit for removal; its prior service state was restored where possible." >&2
    exit 1
  fi
  if ! systemctl --user daemon-reload; then
    trap '' HUP INT TERM
    restored=true
    if ! rollback_uninstall; then
      restored=false
    fi
    echo "Failed to reload the systemd user manager; the managed unit was restored on disk where possible." >&2
    if [[ "$restored" != true ]]; then
      echo "Warning: automatic restoration was incomplete; inspect $unit_file and the user service state." >&2
    fi
    exit 1
  fi
  if ! verify_no_loaded_unit || ! service_is_definitely_inactive || ! service_has_enable_state absent; then
    trap '' HUP INT TERM
    restored=true
    if ! rollback_uninstall; then
      restored=false
    fi
    echo "Refusing to report a successful uninstall because a same-named unit, enabled state, or active runtime remained after reload." >&2
    if [[ "$restored" != true ]]; then
      echo "Warning: automatic restoration was incomplete; inspect $unit_file and the user service state." >&2
    fi
    exit 1
  fi
  trap - HUP INT TERM
  if ! rm -f -- "$uninstall_backup"; then
    echo "Warning: the service was removed, but its backup could not be deleted: $uninstall_backup" >&2
  fi
  echo "Removed $unit_file"
  exit 0
fi

command -v python3 >/dev/null 2>&1 || {
  echo "Python 3 is required to validate daemon status safely." >&2
  exit 1
}
[[ -x "$binary" ]] || {
  echo "Kimi WebBridge binary is not executable: $binary" >&2
  exit 1
}
if ! "$binary" start --help 2>&1 | grep -q -- '--foreground'; then
  echo "This daemon does not expose 'start --foreground'; upgrade it before installing autostart." >&2
  exit 1
fi

unit_tmp="$(mktemp "$unit_dir/.kimi-webbridge.service.XXXXXX")"
trap 'rm -f -- "$unit_tmp"' EXIT
render_unit > "$unit_tmp"
unit_preexisting=false
unit_changed=false
unit_enable_state="absent"
service_was_active=false
runtime_transition_started=false
backup_file=""
if [[ -e "$unit_file" || -L "$unit_file" ]]; then
  if [[ -L "$unit_file" || ! -f "$unit_file" ]] || ! grep -Fqx -- "$managed_marker" "$unit_file"; then
    echo "Refusing to overwrite an unmanaged or non-regular unit: $unit_file" >&2
    exit 1
  fi
  unit_preexisting=true
  probe_service_enabled
  unit_enable_state="$probed_enable_state"
  if ! cmp -s -- "$unit_tmp" "$unit_file"; then
    unit_changed=true
  fi
else
  require_no_competing_unit || exit 1
  if ! service_has_enable_state absent; then
    echo "A same-named enabled state remains although the managed unit file is missing; no changes were made." >&2
    exit 1
  fi
fi
if probe_service_active; then
  service_was_active=true
  if [[ "$unit_preexisting" != true ]]; then
    echo "The managed service is active but its unit file is missing; no changes were made." >&2
    exit 1
  fi
else
  set +e
  daemon_status="$("$binary" status 2>/dev/null)"
  daemon_status_rc=$?
  set -e
  if ((daemon_status_rc != 0)); then
    echo "Could not determine whether a direct Kimi WebBridge daemon is running; no changes were made." >&2
    exit 1
  fi
  if ! daemon_running="$(parse_daemon_running <<<"$daemon_status" 2>/dev/null)"; then
    echo "Daemon status did not contain a valid running boolean; no changes were made." >&2
    exit 1
  fi
  if [[ "$daemon_running" == true ]]; then
    echo "A directly started Kimi WebBridge daemon is running; stop it explicitly, verify it exited, and rerun this helper. No changes were made." >&2
    exit 1
  fi
fi

if [[ "$unit_changed" == true ]]; then
  backup_file="$(mktemp "$unit_file.backup.$(date +%Y%m%d%H%M%S).XXXXXX")"
  cp -p -- "$unit_file" "$backup_file"
  echo "Backed up the previous managed unit to $backup_file"
fi

restore_unit_file() {
  if [[ "$unit_preexisting" == true ]]; then
    if [[ "$unit_changed" == true ]]; then
      cp -p -- "$backup_file" "$unit_file"
    fi
  else
    rm -f -- "$unit_file"
  fi
}

verify_restored_install_unit() {
  if [[ "$unit_preexisting" == true ]]; then
    verify_loaded_unit
  else
    verify_no_loaded_unit
  fi
}

recover_after_failed_transition() {
  local reason="$1"
  local unit_restored=true
  local enabled_restored=true
  local manager_reloaded=false
  local recovered=false
  local new_runtime_stopped=true

  trap '' HUP INT TERM
  if [[ "$runtime_transition_started" == true ]]; then
    if verify_loaded_unit; then
      systemctl --user disable --now kimi-webbridge.service >/dev/null 2>&1 || true
    else
      new_runtime_stopped=false
    fi
    if [[ "$new_runtime_stopped" == true ]] && ! service_is_definitely_inactive; then
      new_runtime_stopped=false
    fi
  fi
  if ! restore_unit_file; then
    unit_restored=false
  fi
  if systemctl --user daemon-reload >/dev/null 2>&1 && verify_restored_install_unit; then
    manager_reloaded=true
  fi

  if [[ "$unit_restored" == true && "$manager_reloaded" == true ]]; then
    case "$unit_enable_state" in
      enabled)
        systemctl --user enable kimi-webbridge.service >/dev/null 2>&1 || true
        service_has_enable_state enabled || enabled_restored=false
        ;;
      enabled-runtime)
        systemctl --user enable --runtime kimi-webbridge.service >/dev/null 2>&1 || true
        service_has_enable_state enabled-runtime || enabled_restored=false
        ;;
      disabled)
        systemctl --user disable kimi-webbridge.service >/dev/null 2>&1 || true
        service_has_enable_state disabled || enabled_restored=false
        ;;
      absent)
        service_has_enable_state absent || enabled_restored=false
        ;;
    esac
  else
    enabled_restored=false
  fi

  if [[ "$runtime_transition_started" != true ]]; then
    recovered=true
    echo "The previous daemon runtime was not stopped before rollback." >&2
  elif [[ "$service_was_active" == true ]]; then
    if [[ "$new_runtime_stopped" == true && "$unit_restored" == true && "$manager_reloaded" == true && "$unit_preexisting" == true ]] && systemctl --user start kimi-webbridge.service && service_is_definitely_active; then
      recovered=true
      echo "Restored the previously active managed service after the failed install." >&2
    fi
  else
    if [[ "$new_runtime_stopped" == true ]]; then
      recovered=true
      echo "Restored the previous inactive runtime state; no daemon was started during rollback." >&2
    fi
  fi

  echo "$reason" >&2
  if [[ "$unit_restored" != true ]]; then
    echo "Warning: the previous unit file could not be restored from $backup_file." >&2
  fi
  if [[ "$manager_reloaded" != true ]]; then
    echo "Warning: systemd could not reload the restored unit; it was not started automatically." >&2
  fi
  if [[ "$enabled_restored" != true ]]; then
    echo "Warning: the previous enabled/disabled service state could not be restored automatically." >&2
  fi
  if [[ "$new_runtime_stopped" != true ]]; then
    echo "Warning: the new managed service could not be confirmed stopped; the previous runtime was not started." >&2
  fi
  if [[ "$recovered" != true ]]; then
    echo "Warning: automatic daemon recovery also failed; run the binary's status/logs commands." >&2
  fi
  if [[ "$unit_restored" != true || "$manager_reloaded" != true || "$enabled_restored" != true || "$new_runtime_stopped" != true || "$recovered" != true ]]; then
    echo "Warning: automatic restoration was incomplete; inspect $unit_file and the user service state." >&2
  fi
  exit 1
}

interrupt_install() {
  recover_after_failed_transition "Autostart installation was interrupted; rollback was attempted."
}
trap interrupt_install HUP INT TERM
if [[ "$unit_preexisting" != true || "$unit_changed" == true ]]; then
  mv -- "$unit_tmp" "$unit_file"
fi

if ! systemctl --user daemon-reload; then
  trap '' HUP INT TERM
  restored=true
  if ! restore_unit_file; then
    restored=false
  fi
  if ! systemctl --user daemon-reload >/dev/null 2>&1 || ! verify_restored_install_unit; then
    restored=false
  fi
  echo "Failed to reload the systemd user manager; the daemon was not stopped." >&2
  if [[ "$restored" != true ]]; then
    echo "Warning: the previous unit could not be fully restored after the reload failure." >&2
  fi
  exit 1
fi
if ! verify_loaded_unit; then
  trap '' HUP INT TERM
  restored=true
  if ! restore_unit_file; then
    restored=false
  fi
  if ! systemctl --user daemon-reload >/dev/null 2>&1 || ! verify_restored_install_unit; then
    restored=false
  fi
  echo "systemd did not load the exact managed unit or reported active drop-ins; the daemon was not stopped." >&2
  if [[ "$restored" != true ]]; then
    echo "Warning: the previous unit could not be fully restored after effective-unit validation failed." >&2
  fi
  exit 1
fi
runtime_transition_started=true
if ! systemctl --user stop kimi-webbridge.service; then
  recover_after_failed_transition "Failed to stop the previous managed service; the installed unit was rolled back."
fi
if ! service_is_definitely_inactive; then
  recover_after_failed_transition "The previous managed service could not be confirmed stopped; the installed unit was rolled back."
fi
if ! systemctl --user start kimi-webbridge.service; then
  recover_after_failed_transition "Failed to start the new managed service; the installed unit was rolled back."
fi
if ! systemctl --user is-active --quiet kimi-webbridge.service; then
  recover_after_failed_transition "The new managed service did not remain active; the installed unit was rolled back."
fi
if ! systemctl --user enable kimi-webbridge.service; then
  recover_after_failed_transition "The new managed service could not be enabled; the installed unit was rolled back."
fi
if ! service_has_enable_state enabled; then
  recover_after_failed_transition "The new managed service did not become enabled; the installed unit was rolled back."
fi
if ! systemctl --user is-active --quiet kimi-webbridge.service; then
  recover_after_failed_transition "The new managed service exited while enablement was being finalized; the installed unit was rolled back."
fi
trap - HUP INT TERM
systemctl --user --no-pager --full status kimi-webbridge.service || true
echo "Installed and enabled $unit_file"
