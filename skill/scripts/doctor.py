#!/usr/bin/env python3

import argparse
import ctypes
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

from webbridge_client import configure_utf8_output


STORE_EXTENSION_ID = "fldmhceldgbpfpkbgopacenieobmligc"


def default_binary_path():
    home = Path.home()
    if os.name == "nt":
        return home / ".kimi-webbridge" / "bin" / "kimi-webbridge.exe"
    return home / ".kimi-webbridge" / "bin" / "kimi-webbridge"


def default_pid_file():
    return Path.home() / ".kimi-webbridge" / "daemon.pid"


def parse_status_output(stdout):
    text = stdout.strip()
    if not text:
        return None, "empty status output"
    try:
        return json.loads(text), None
    except json.JSONDecodeError as error:
        return None, f"invalid status JSON: {error}"


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
    return {
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }


def process_alive(pid):
    if pid <= 0:
        return False
    if os.name == "nt":
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


def wait_for_extension(binary, daemon_host, daemon_port, timeout, interval):
    deadline = time.monotonic() + timeout
    last = status_snapshot(binary, daemon_host, daemon_port)
    while time.monotonic() < deadline:
        status = last.get("status") or {}
        if status.get("running") and status.get("extension_connected"):
            return last
        time.sleep(interval)
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
        recommendations.append("Start the daemon, then rerun doctor with --wait-connected.")
    elif not status.get("extension_connected"):
        recommendations.append(
            "Open Chrome and enable the Kimi WebBridge extension; rerun with --wait-connected before giving up."
        )
    else:
        recommendations.append("Ready: daemon is running and the browser extension is connected.")

    if pid.get("stale"):
        recommendations.append(
            "daemon.pid points to a non-running process; remove it only after verifying the PID is stale."
        )

    extension_id = status.get("extension_id")
    if extension_id and extension_id != STORE_EXTENSION_ID:
        recommendations.append(
            "Do not treat extension_id mismatch with the Chrome Web Store URL as a hard failure; status connectivity is authoritative."
        )

    if status.get("running") and not report.get("port_open"):
        recommendations.append("Daemon reports running but port 10086 is not reachable; inspect logs or restart once.")

    return recommendations


def parse_args():
    parser = argparse.ArgumentParser(
        description="Diagnose local Kimi WebBridge readiness without sending browser actions."
    )
    parser.add_argument("--binary", type=Path, default=default_binary_path())
    parser.add_argument("--pid-file", type=Path, default=default_pid_file())
    parser.add_argument("--daemon-host", default="127.0.0.1")
    parser.add_argument("--daemon-port", type=int, default=10086)
    parser.add_argument("--wait-connected", type=float, default=0)
    parser.add_argument("--interval", type=float, default=2)
    parser.add_argument(
        "--start",
        action="store_true",
        help="Start the daemon if it is installed but not running.",
    )
    return parser.parse_args()


def main():
    configure_utf8_output()
    args = parse_args()
    if args.wait_connected < 0 or args.interval <= 0:
        raise SystemExit("--wait-connected must be non-negative and --interval must be positive.")

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
    report["pid_file"] = inspect_pid_file(args.pid_file)
    report["ready"] = bool(
        (report.get("status") or {}).get("running")
        and (report.get("status") or {}).get("extension_connected")
    )
    report["recommendations"] = build_recommendations(report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(0 if report["ready"] else 1)


if __name__ == "__main__":
    main()
