#!/usr/bin/env bash

set -euo pipefail

action=""
session=""
args_json="{}"
args_file=""
output_path=""
daemon_url="http://127.0.0.1:10086"
timeout=30
dry_run=false
force=false

usage() {
  cat <<'EOF'
Usage: invoke.sh --action ACTION [options]

Options:
  -a, --action ACTION      WebBridge action name
  -s, --session SESSION    Stable task session name
  -j, --args-json JSON     Action arguments as JSON
  -f, --args-file PATH     UTF-8 JSON file containing action arguments
  -o, --output PATH        Save the raw response instead of printing it
  -d, --daemon-url URL     Daemon URL (default: http://127.0.0.1:10086)
  -t, --timeout SECONDS    Request timeout (default: 30)
      --dry-run            Print the request body without sending it
      --force              Allow destructive helper actions such as close_session
  -h, --help               Show this help

Use --args-file for non-ASCII text or complex JSON.
EOF
}

while (($#)); do
  case "$1" in
    -a|--action)
      action="${2:?missing action}"
      shift 2
      ;;
    -s|--session)
      session="${2:?missing session}"
      shift 2
      ;;
    -j|--args-json)
      args_json="${2:?missing JSON}"
      shift 2
      ;;
    -f|--args-file)
      args_file="${2:?missing file path}"
      shift 2
      ;;
    -o|--output)
      output_path="${2:?missing output path}"
      shift 2
      ;;
    -d|--daemon-url)
      daemon_url="${2:?missing daemon URL}"
      shift 2
      ;;
    -t|--timeout)
      timeout="${2:?missing timeout}"
      shift 2
      ;;
    --dry-run)
      dry_run=true
      shift
      ;;
    --force)
      force=true
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

[[ -n "$action" ]] || { echo "--action is required" >&2; exit 2; }
[[ "$action" =~ ^[A-Za-z0-9_.-]+$ ]] || { echo "Invalid action name" >&2; exit 2; }
[[ -z "$session" || "$session" =~ ^[A-Za-z0-9_.-]+$ ]] || {
  echo "Session names may contain letters, digits, dot, underscore, and hyphen." >&2
  exit 2
}
[[ "$timeout" =~ ^[1-9][0-9]*$ ]] || { echo "Timeout must be a positive integer." >&2; exit 2; }
if [[ "$action" == "close_session" && "$force" != true ]]; then
  echo "Refusing close_session without --force; verify every tab is task-owned." >&2
  exit 2
fi
if [[ "$action" == "close_session" && "$force" == true ]]; then
  echo "Warning: forced close_session can close every tab attached to this session. Run list_tabs first and verify they are task-owned." >&2
fi

if [[ -n "$args_file" ]]; then
  [[ -f "$args_file" ]] || { echo "Arguments file not found: $args_file" >&2; exit 2; }
  args_json="$(<"$args_file")"
fi

request_file="$(mktemp)"
trap 'rm -f "$request_file"' EXIT

# Build the envelope from a UTF-8 args file without depending on jq.
{
  printf '{"action":"%s","args":%s' "$action" "$args_json"
  if [[ -n "$session" ]]; then
    printf ',"session":"%s"' "$session"
  fi
  printf '}'
} > "$request_file"

if [[ "$dry_run" == true ]]; then
  cat "$request_file"
  printf '\n'
  exit 0
fi

curl_args=(
  --silent
  --show-error
  --fail-with-body
  --max-time "$timeout"
  --request POST
  --header "Content-Type: application/json; charset=utf-8"
  --data-binary "@$request_file"
  "$daemon_url/command"
)

if [[ -n "$output_path" ]]; then
  mkdir -p "$(dirname "$output_path")"
  curl "${curl_args[@]}" --output "$output_path"
  printf '%s\n' "$output_path"
else
  curl "${curl_args[@]}"
  printf '\n'
fi
