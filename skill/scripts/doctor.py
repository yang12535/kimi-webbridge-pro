#!/usr/bin/env python3

import argparse
import json
import math
import os
import queue
import re
import socket
import subprocess
import threading
import time
from pathlib import Path

from webbridge_client import configure_utf8_output, post_command


STORE_EXTENSION_ID = "fldmhceldgbpfpkbgopacenieobmligc"


def default_binary_path():
    home = Path.home()
    if os.name == "nt":
        return home / ".kimi-webbridge" / "bin" / "kimi-webbridge.exe"
    return home / ".kimi-webbridge" / "bin" / "kimi-webbridge"


def default_pid_file():
    return Path.home() / ".kimi-webbridge" / "daemon.pid"


def default_skills_dirs():
    home = Path.home()
    return [
        home / ".kimi-code" / "skills",
        home / ".agents" / "skills",
        home / ".codex" / "skills",
    ]


def inspect_skill_conflicts(skills_dirs):
    conflicts = []
    official_paths = []
    pro_paths = []
    for skills_dir in skills_dirs:
        root = Path(skills_dir).expanduser()
        official = root / "kimi-webbridge"
        pro = root / "kimi-webbridge-pro"
        official_present = (official / "SKILL.md").is_file()
        pro_present = (pro / "SKILL.md").is_file()
        if official_present:
            official_paths.append(str(official))
        if pro_present:
            pro_paths.append(str(pro))
        if official_present and pro_present:
            conflicts.append(
                {
                    "scope": "same_root",
                    "skills_dir": str(root),
                    "official": str(official),
                    "pro": str(pro),
                }
            )
    if not conflicts and official_paths and pro_paths:
        conflicts.append(
            {
                "scope": "multiple_roots",
                "official": official_paths,
                "pro": pro_paths,
            }
        )
    return conflicts


def numeric_version(value):
    if not isinstance(value, str):
        return None
    match = re.match(r"^[vV]?(\d+)\.(\d+)\.(\d+)", value.strip())
    if not match:
        return None
    return tuple(int(part) for part in match.groups())


def parse_status_output(stdout):
    text = stdout.strip()
    if not text:
        return None, "empty status output"
    try:
        status = json.loads(text)
    except json.JSONDecodeError as error:
        return None, f"invalid status JSON: {error}"
    if not isinstance(status, dict):
        return None, "invalid status shape: expected a JSON object"
    return status, None


def run_binary(binary, *args, timeout=10):
    try:
        completed = subprocess.run(
            [str(binary), *args],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except FileNotFoundError:
        return {"returncode": None, "stdout": "", "stderr": "binary not found"}
    except subprocess.TimeoutExpired:
        return {"returncode": None, "stdout": "", "stderr": "command timed out"}
    except OSError as error:
        return {"returncode": None, "stdout": "", "stderr": str(error)}
    return {
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }


def process_alive(pid):
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        handle = ctypes.windll.kernel32.OpenProcess(
            PROCESS_QUERY_LIMITED_INFORMATION, False, pid
        )
        if handle:
            ctypes.windll.kernel32.CloseHandle(handle)
            return True
        return False
    try:
        os.kill(pid, 0)
        return True
    except PermissionError:
        return True
    except OSError:
        return False


def inspect_pid_file(pid_file):
    result = {"path": str(pid_file), "exists": pid_file.exists()}
    if not pid_file.exists():
        return result
    try:
        pid = int(pid_file.read_text(encoding="utf-8").strip())
    except (OSError, ValueError) as error:
        result["error"] = str(error)
        return result
    result["pid"] = pid
    result["process_alive"] = process_alive(pid)
    result["stale"] = not result["process_alive"]
    return result


def port_open(host, port, timeout=1.0):
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def format_daemon_url(host, port):
    url_host = f"[{host}]" if ":" in host and not host.startswith("[") else host
    return f"http://{url_host}:{port}"


def probe_command(daemon_host, daemon_port, timeout):
    daemon_url = format_daemon_url(daemon_host, daemon_port)
    outcome = queue.Queue(maxsize=1)

    def request_probe():
        try:
            result = post_command("list_tabs", {}, "doctor-probe", daemon_url, timeout)
        except Exception as error:
            outcome.put(("error", error))
        else:
            outcome.put(("result", result))

    worker = threading.Thread(target=request_probe, daemon=True)
    worker.start()
    worker.join(timeout)
    if worker.is_alive():
        return {"ok": False, "error": f"probe exceeded {timeout:g}s wall-clock timeout"}

    try:
        kind, value = outcome.get_nowait()
    except queue.Empty:
        return {"ok": False, "error": "probe worker exited without a result"}
    if kind == "error":
        return {"ok": False, "error": str(value)}
    result = value
    if result.get("ok") is not True:
        return {"ok": False, "error": "command response did not contain ok=true"}
    data = result.get("data")
    if not isinstance(data, dict):
        return {"ok": False, "error": "list_tabs response data is not an object"}
    if data.get("success") is not True:
        return {"ok": False, "error": data.get("error") or "command returned success=false"}
    if not isinstance(data.get("tabs"), list):
        return {"ok": False, "error": "list_tabs response did not contain a tabs array"}
    return {"ok": True, "tab_count": len(data["tabs"])}


def probe_failed(report):
    probe = report.get("probe")
    return isinstance(probe, dict) and probe.get("ok") is False


def status_snapshot(binary, daemon_host, daemon_port):
    binary_exists = Path(binary).exists()
    status = None
    status_error = None
    command_result = None
    if binary_exists:
        command_result = run_binary(binary, "status")
        if command_result["returncode"] == 0:
            status, status_error = parse_status_output(command_result["stdout"])
        else:
            status_error = command_result["stderr"] or command_result["stdout"]
    else:
        status_error = "binary not found"

    return {
        "daemon": {"host": daemon_host, "port": daemon_port},
        "binary": {"path": str(binary), "exists": binary_exists},
        "status": status,
        "status_error": status_error,
        "command_returncode": None if command_result is None else command_result["returncode"],
        "port_open": port_open(daemon_host, daemon_port),
    }


def report_ready(report):
    status = report.get("status") or {}
    if probe_failed(report):
        return False
    return bool(
        status.get("running")
        and status.get("extension_connected")
        and report.get("port_open")
    )


def readiness_reason(report):
    binary = report.get("binary") or {}
    status = report.get("status") or {}
    if not binary.get("exists"):
        return "binary not found"
    if not status:
        return report.get("status_error") or "daemon status unavailable"
    if not status.get("running"):
        return "daemon not running"
    if not report.get("port_open"):
        return "daemon port not reachable"
    if not status.get("extension_connected"):
        return "extension not connected"
    if probe_failed(report):
        return "extension connected but command probe failed"
    return "ready"


def sleep_until_deadline(deadline, interval):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        return False
    time.sleep(min(interval, remaining))
    return True


def wait_for_extension(binary, daemon_host, daemon_port, timeout, interval):
    deadline = time.monotonic() + timeout
    last = status_snapshot(binary, daemon_host, daemon_port)
    while True:
        if report_ready(last):
            return last
        if not sleep_until_deadline(deadline, interval):
            break
        last = status_snapshot(binary, daemon_host, daemon_port)
    return last


def build_recommendations(report):
    recommendations = []
    binary = report.get("binary") or {}
    status = report.get("status") or {}
    pid = report.get("pid_file") or {}

    if not binary.get("exists"):
        recommendations.append("Install Kimi WebBridge daemon before sending commands.")
    elif not status:
        recommendations.append("Read daemon status output and recent logs; status JSON was unavailable.")
    elif not status.get("running"):
        recommendations.append(
            "Run doctor.py --start --wait-connected 20. Let the daemon handle a stale PID first; "
            "remove daemon.pid manually only after verifying its process is gone."
        )
    elif not report.get("port_open"):
        port = (report.get("daemon") or {}).get("port", 10086)
        recommendations.append(
            f"Daemon reports running but port {port} is not reachable; inspect logs or restart once."
        )
    elif not status.get("extension_connected"):
        recommendations.append(
            "Open Chrome and enable the Kimi WebBridge extension; rerun with --wait-connected before giving up."
        )
    else:
        if probe_failed(report):
            recommendations.append(
                "Status looks ready but a real command failed; the extension connection may be a zombie. "
                "Restart the daemon once (kimi-webbridge restart), then retry."
            )
        else:
            recommendations.append(
                "Ready: daemon is running, the browser extension is connected, and the daemon port is reachable."
            )

    if pid.get("stale"):
        recommendations.append(
            "daemon.pid points to a non-running process. Try doctor.py --start first; remove the PID file "
            "only if that normal startup path still fails."
        )

    extension_id = status.get("extension_id")
    if extension_id and extension_id != STORE_EXTENSION_ID:
        recommendations.append(
            "Do not treat extension_id mismatch with the Chrome Web Store URL as a hard failure; status connectivity is authoritative."
        )

    daemon_version = numeric_version(status.get("version") or status.get("daemon_version"))
    extension_version = numeric_version(status.get("extension_version"))
    versions_differ = daemon_version and extension_version and daemon_version != extension_version
    if status.get("version_mismatch") or versions_differ:
        recommendations.append(
            "The daemon and browser extension versions differ. With the connected extension, run "
            "kimi-webbridge upgrade without a version to install its matching daemon release, then retry "
            "version-sensitive actions such as upload once."
        )

    for conflict in report.get("skill_conflicts") or []:
        if conflict.get("scope") == "same_root":
            recommendations.append(
                "Both kimi-webbridge and kimi-webbridge-pro are installed in "
                f"{conflict['skills_dir']}. Prefer the Pro skill for helper-driven workflows; "
                "future daemon installs should use --no-skill unless the official skill is also needed."
            )
        else:
            recommendations.append(
                "kimi-webbridge and kimi-webbridge-pro were found in different known skills roots. "
                "If the active Agent loads both roots, prefer Pro for helper-driven workflows; "
                "otherwise this may be an intentional per-Agent installation."
            )

    return recommendations


def finite_probe_timeout(value):
    try:
        timeout = float(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("must be a number") from error
    if not 0 < timeout <= 300 or timeout in (float("inf"), float("-inf")):
        raise argparse.ArgumentTypeError("must be finite and between 0 and 300 seconds")
    return timeout


def finite_nonnegative(value):
    try:
        number = float(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("must be a number") from error
    if not math.isfinite(number) or number < 0:
        raise argparse.ArgumentTypeError("must be finite and non-negative")
    return number


def finite_positive(value):
    number = finite_nonnegative(value)
    if number == 0:
        raise argparse.ArgumentTypeError("must be positive")
    return number


def parse_args():
    parser = argparse.ArgumentParser(
        description="Diagnose local Kimi WebBridge readiness; --probe optionally sends list_tabs."
    )
    parser.add_argument("--binary", type=Path, default=default_binary_path())
    parser.add_argument("--pid-file", type=Path, default=default_pid_file())
    parser.add_argument("--daemon-host", default="127.0.0.1")
    parser.add_argument("--daemon-port", type=int, default=10086)
    parser.add_argument("--wait-connected", type=finite_nonnegative, default=0)
    parser.add_argument("--interval", type=finite_positive, default=2)
    parser.add_argument(
        "--skills-dir",
        action="append",
        type=Path,
        help="Skills root to inspect for official/Pro coexistence; repeat for multiple roots.",
    )
    parser.add_argument(
        "--start",
        action="store_true",
        help="Start the daemon if it is installed but not running.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Compatibility flag; doctor output is always JSON.",
    )
    parser.add_argument(
        "--probe",
        action="store_true",
        help="Send a real list_tabs command to detect zombie extension connections.",
    )
    parser.add_argument(
        "--probe-timeout",
        type=finite_probe_timeout,
        default=10,
        help="Seconds to wait for the --probe command response.",
    )
    return parser.parse_args()


def main():
    configure_utf8_output()
    args = parse_args()
    report = status_snapshot(args.binary, args.daemon_host, args.daemon_port)
    status = report.get("status") or {}
    start_result = None
    if args.start and report["binary"]["exists"] and not status.get("running"):
        start_result = run_binary(args.binary, "start", timeout=20)
        report = status_snapshot(args.binary, args.daemon_host, args.daemon_port)
    if args.wait_connected:
        report = wait_for_extension(
            args.binary,
            args.daemon_host,
            args.daemon_port,
            timeout=args.wait_connected,
            interval=args.interval,
        )

    if start_result is not None:
        report["start"] = start_result
    if args.probe:
        if report_ready(report):
            report["probe"] = probe_command(args.daemon_host, args.daemon_port, args.probe_timeout)
        else:
            report["probe"] = {
                "skipped": True,
                "reason": f"passive checks not ready: {readiness_reason(report)}",
            }
    report["pid_file"] = inspect_pid_file(args.pid_file)
    report["skill_conflicts"] = inspect_skill_conflicts(
        args.skills_dir if args.skills_dir is not None else default_skills_dirs()
    )
    report["ready"] = report_ready(report)
    report["reason"] = readiness_reason(report)
    report["recommendations"] = build_recommendations(report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(0 if report["ready"] else 1)


if __name__ == "__main__":
    main()
