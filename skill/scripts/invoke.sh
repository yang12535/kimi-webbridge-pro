#!/usr/bin/env bash

set -euo pipefail

action=""
session=""
args_json="{}"
args_json_set=false
args_file=""
output_path=""
daemon_url="http://127.0.0.1:10086"
timeout=30
timeout_set=false
dry_run=false
force=false

usage() {
  cat <<'EOF'
Usage: invoke.sh --action ACTION [options]

Options:
  -a, --action ACTION      WebBridge action name
  -s, --session SESSION    Stable task session name
  -j, --args-json JSON     Action arguments as JSON
  -f, --args-file PATH     UTF-8 JSON file containing action arguments; use - for stdin
      --args-stdin         Read UTF-8 JSON action arguments from stdin
  -o, --output PATH        Save the raw response instead of printing it
  -d, --daemon-url URL     Daemon URL (default: http://127.0.0.1:10086)
  -t, --timeout SECONDS    Request timeout (default: 30; navigate: 45)
      --dry-run            Print the request body without sending it
      --force              Allow destructive helper actions such as close_session
  -h, --help               Show this help

Use --args-file - or --args-stdin for non-ASCII text or complex JSON without a temporary file.

Core action arguments:
  navigate   url, newTab, optional group_title
  find_tab  url, optional active
  click     selector
  fill      selector, value
  evaluate  code
  upload    selector, files

Read references/protocol.md before using advanced or version-dependent actions.
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
      args_json_set=true
      shift 2
      ;;
    -f|--args-file)
      args_file="${2:?missing file path}"
      shift 2
      ;;
    --args-stdin)
      args_file="-"
      shift
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
      timeout_set=true
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
[[ "$daemon_url" =~ ^https?:// ]] || { echo "Daemon URL must start with http:// or https://." >&2; exit 2; }
if [[ "$timeout_set" == false && "$action" == "navigate" ]]; then
  timeout=45
fi
if [[ "$action" == "close_session" && "$force" != true ]]; then
  echo "Refusing close_session without --force; verify every tab is task-owned." >&2
  exit 2
fi
if [[ "$action" == "close_session" && "$force" == true ]]; then
  echo "Warning: forced close_session can close every tab attached to this session. Run list_tabs first and verify they are task-owned." >&2
fi

if [[ -n "$args_file" && "$args_json_set" == true ]]; then
  echo "Use either --args-json or --args-file, not both." >&2
  exit 2
fi

if [[ -n "$args_file" ]]; then
  if [[ "$args_file" == "-" ]]; then
    if [[ -t 0 ]]; then
      echo "Refusing to wait for JSON on an interactive terminal; pipe input or use a heredoc." >&2
      exit 2
    fi
    args_json="$(cat)"
  else
    [[ -f "$args_file" ]] || { echo "Arguments file not found: $args_file" >&2; exit 2; }
    args_json="$(<"$args_file")"
  fi
fi

[[ "$args_json" =~ [^[:space:]] ]] || { echo "Arguments JSON is empty." >&2; exit 2; }
if [[ -n "$output_path" && -d "$output_path" ]]; then
  echo "Output path must be a file, not a directory: $output_path" >&2
  exit 2
fi

json_python=()
if command -v python3 >/dev/null 2>&1; then
  json_python=(python3)
elif command -v py >/dev/null 2>&1; then
  json_python=(py -3)
elif command -v python >/dev/null 2>&1; then
  json_python=(python)
else
  echo "Python 3 is required to validate action arguments." >&2
  exit 2
fi

if ! args_json="$(
  printf '%s' "$args_json" | "${json_python[@]}" -c '
import json
import sys

def reject_constant(value):
    raise ValueError(f"non-finite JSON number: {value}")

try:
    value = json.loads(
        sys.stdin.buffer.read().decode("utf-8-sig"),
        parse_constant=reject_constant,
    )
except (UnicodeError, ValueError) as error:
    print(f"Arguments must be valid UTF-8 JSON: {error}", file=sys.stderr)
    raise SystemExit(2)
if not isinstance(value, dict):
    print("Arguments JSON must be an object.", file=sys.stderr)
    raise SystemExit(2)
encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
sys.stdout.buffer.write(encoded)
'
)"; then
  exit 2
fi

request_file="$(mktemp)"
response_file="$(mktemp)"
trap 'rm -f "$request_file" "$response_file"' EXIT

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
  --globoff
  --max-time "$timeout"
  --request POST
  --header "Content-Type: application/json; charset=utf-8"
  --data-binary "@$request_file"
  --url "$daemon_url/command"
)

set +e
http_code="$(curl "${curl_args[@]}" --output "$response_file" --write-out '%{http_code}')"
curl_status=$?
set -e

if ((curl_status != 0)); then
  if [[ -s "$response_file" ]]; then
    cat "$response_file" >&2
    printf '\n' >&2
  fi
  case "$curl_status" in
    7)
      echo "WebBridge daemon is unreachable; run scripts/doctor.py --start --wait-connected 20." >&2
      ;;
    28)
      echo "WebBridge request timed out after ${timeout}s; run scripts/doctor.py --probe before retrying the action." >&2
      ;;
    *)
      echo "WebBridge request failed in curl (exit ${curl_status}); run scripts/doctor.py for diagnosis." >&2
      ;;
  esac
  exit "$curl_status"
fi

[[ "$http_code" =~ ^[0-9]{3}$ ]] || {
  echo "WebBridge returned an invalid HTTP status: $http_code" >&2
  exit 1
}

if [[ -n "$output_path" ]]; then
  mkdir -p -- "$(dirname -- "$output_path")"
  mv -- "$response_file" "$output_path"
  printf '%s\n' "$output_path"
else
  cat "$response_file"
  printf '\n'
fi

if ((http_code < 200 || http_code >= 300)); then
  if [[ -n "$output_path" ]]; then
    echo "WebBridge returned HTTP ${http_code}; the response body was saved to $output_path." >&2
  else
    echo "WebBridge returned HTTP ${http_code}; the response body above was preserved." >&2
  fi
  exit 22
fi
