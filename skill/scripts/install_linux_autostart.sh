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
No root privileges are required.
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

[[ "$(uname -s)" == "Linux" ]] || {
  echo "systemd user autostart is supported only on Linux." >&2
  exit 1
}
command -v systemctl >/dev/null 2>&1 || {
  echo "systemctl is required for Linux user autostart." >&2
  exit 1
}

if [[ "$mode" == "uninstall" ]]; then
  if [[ ! -e "$unit_file" && ! -L "$unit_file" ]]; then
    echo "No managed unit is installed at $unit_file"
    exit 0
  fi
  if [[ -L "$unit_file" || ! -f "$unit_file" ]] || ! grep -Fqx -- "$managed_marker" "$unit_file"; then
    echo "Refusing to remove an unmanaged or non-regular unit: $unit_file" >&2
    exit 1
  fi
  if ! systemctl --user disable --now kimi-webbridge.service; then
    echo "Refusing to remove the unit because systemctl could not disable and stop the service." >&2
    exit 1
  fi
  rm -- "$unit_file"
  systemctl --user daemon-reload
  echo "Removed $unit_file"
  exit 0
fi

[[ -x "$binary" ]] || {
  echo "Kimi WebBridge binary is not executable: $binary" >&2
  exit 1
}
if ! "$binary" start --help 2>&1 | grep -q -- '--foreground'; then
  echo "This daemon does not expose 'start --foreground'; upgrade it before installing autostart." >&2
  exit 1
fi

mkdir -p -- "$unit_dir"
unit_tmp="$(mktemp "$unit_dir/.kimi-webbridge.service.XXXXXX")"
trap 'rm -f -- "$unit_tmp"' EXIT
render_unit > "$unit_tmp"
unit_preexisting=false
unit_changed=false
unit_was_enabled=false
backup_file=""
if [[ -e "$unit_file" || -L "$unit_file" ]]; then
  if [[ -L "$unit_file" || ! -f "$unit_file" ]] || ! grep -Fqx -- "$managed_marker" "$unit_file"; then
    echo "Refusing to overwrite an unmanaged or non-regular unit: $unit_file" >&2
    exit 1
  fi
  unit_preexisting=true
  if systemctl --user is-enabled --quiet kimi-webbridge.service 2>/dev/null; then
    unit_was_enabled=true
  fi
  if ! cmp -s -- "$unit_tmp" "$unit_file"; then
    backup_file="$(mktemp "$unit_file.backup.$(date +%Y%m%d%H%M%S).XXXXXX")"
    cp -p -- "$unit_file" "$backup_file"
    unit_changed=true
    echo "Backed up the previous managed unit to $backup_file"
  fi
fi
mv -- "$unit_tmp" "$unit_file"

restore_unit_file() {
  if [[ "$unit_preexisting" == true ]]; then
    if [[ "$unit_changed" == true ]]; then
      cp -p -- "$backup_file" "$unit_file"
    fi
  else
    rm -f -- "$unit_file"
  fi
}

recover_after_failed_transition() {
  local reason="$1"
  local restored=true
  local recovered=false

  systemctl --user disable --now kimi-webbridge.service >/dev/null 2>&1 || true
  if ! restore_unit_file; then
    restored=false
  fi
  systemctl --user daemon-reload >/dev/null 2>&1 || true

  if [[ "$restored" == true && "$unit_was_enabled" == true ]]; then
    systemctl --user enable kimi-webbridge.service >/dev/null 2>&1 || true
  fi

  if [[ "$restored" == true && "$unit_preexisting" == true ]] && systemctl --user start kimi-webbridge.service; then
    recovered=true
    echo "Restored the previous managed service after the failed install." >&2
  elif "$binary" start; then
    recovered=true
    echo "Restored daemon availability with a direct background start after the failed install." >&2
  fi

  echo "$reason" >&2
  if [[ "$restored" != true ]]; then
    echo "Warning: the previous unit file could not be restored from $backup_file." >&2
  fi
  if [[ "$recovered" != true ]]; then
    echo "Warning: automatic daemon recovery also failed; run the binary's status/logs commands." >&2
  fi
  exit 1
}

if ! systemctl --user daemon-reload; then
  restore_unit_file || true
  systemctl --user daemon-reload >/dev/null 2>&1 || true
  echo "Failed to reload the systemd user manager; the daemon was not stopped." >&2
  exit 1
fi
if ! systemctl --user stop kimi-webbridge.service; then
  recover_after_failed_transition "Failed to stop the previous managed service; the installed unit was rolled back."
fi
"$binary" stop >/dev/null 2>&1 || true
if ! systemctl --user start kimi-webbridge.service; then
  recover_after_failed_transition "Failed to start the new managed service; the installed unit was rolled back."
fi
if ! systemctl --user is-active --quiet kimi-webbridge.service; then
  recover_after_failed_transition "The new managed service did not remain active; the installed unit was rolled back."
fi
if ! systemctl --user enable kimi-webbridge.service; then
  recover_after_failed_transition "The new managed service could not be enabled; the installed unit was rolled back."
fi
systemctl --user --no-pager --full status kimi-webbridge.service || true
echo "Installed and enabled $unit_file"
