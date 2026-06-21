#!/usr/bin/env python3

import base64
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skill" / "scripts"


class MockDaemonHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path != "/command":
            self.send_error(404)
            return

        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length).decode("utf-8"))
        action = payload.get("action")
        session = payload.get("session")

        if action == "snapshot":
            name = "nothing here" if session == "no-match" else "显卡日报 ready"
            body = {
                "ok": True,
                "data": {
                    "url": "https://example.test/gpu-daily",
                    "title": "Mock GPU Daily",
                    "tree": {
                        "role": "document",
                        "children": [
                            {"role": "heading", "name": name, "ref": "@e1"},
                            {"role": "button", "name": "Run", "ref": "@e2"},
                        ],
                    },
                },
            }
        elif action == "screenshot":
            if session == "fail-http":
                body = {"ok": False, "error": "daemon says no"}
                encoded = json.dumps(body, ensure_ascii=False).encode("utf-8")
                self.send_response(500)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)
                return
            elif session == "base64-shot":
                body = {
                    "ok": True,
                    "data": {
                        "data": base64.b64encode(b"fake-image-bytes").decode("ascii")
                    },
                }
            else:
                body = {"ok": True, "data": {"path": self.server.screenshot_path}}
        elif action == "fail-http":
            body = {"ok": False, "error": "daemon says no"}
            encoded = json.dumps(body, ensure_ascii=False).encode("utf-8")
            self.send_response(500)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)
            return
        else:
            body = {"ok": True, "data": {"success": True, "echo": payload}}

        encoded = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, _format, *args):
        return


class MockDaemonCliTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tempdir = tempfile.TemporaryDirectory()
        cls.screenshot_path = Path(cls.tempdir.name) / "mock.png"
        cls.screenshot_path.write_bytes(b"mock-png")
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), MockDaemonHandler)
        cls.server.screenshot_path = str(cls.screenshot_path)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        host, port = cls.server.server_address
        cls.daemon_url = f"http://{host}:{port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.tempdir.cleanup()

    def run_cli(self, command, *args, expected=0, timeout=5):
        env = os.environ.copy()
        env.setdefault("PYTHONIOENCODING", "utf-8")
        result = subprocess.run(
            [str(command), *args],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            timeout=timeout,
        )
        self.assertEqual(result.returncode, expected, result.stderr or result.stdout)
        return result

    def run_python_cli(self, script, *args, expected=0, timeout=5):
        return self.run_cli(sys.executable, str(script), *args, expected=expected, timeout=timeout)

    def bash_executable(self):
        candidates = []
        if os.name == "nt":
            # Prefer Git for Windows Bash. The Windows WSL launcher is also named
            # bash.exe but can fail before reaching the script when WSL is disabled.
            candidates.extend(
                [
                    Path("C:/Program Files/Git/bin/bash.exe"),
                    Path("C:/Program Files/Git/usr/bin/bash.exe"),
                ]
            )
        executable = shutil.which("bash")
        if executable:
            candidates.append(Path(executable))
        for candidate in candidates:
            if candidate.exists() and "system32" not in str(candidate).lower():
                return str(candidate)
        self.skipTest("bash is not available")

    def pwsh_executable(self):
        executable = shutil.which("pwsh")
        if not executable:
            self.skipTest("pwsh is not available")
        return executable

    def run_bash_cli(self, script, *args, expected=0, timeout=5):
        return self.run_cli(
            self.bash_executable(),
            str(script),
            *args,
            expected=expected,
            timeout=timeout,
        )

    def run_pwsh_cli(self, *args, expected=0, timeout=5):
        return self.run_cli(
            self.pwsh_executable(),
            "-NoLogo",
            "-NoProfile",
            *args,
            expected=expected,
            timeout=timeout,
        )

    def test_invoke_sh_posts_to_mock_daemon(self):
        result = self.run_bash_cli(
            SCRIPTS / "invoke.sh",
            "--daemon-url",
            self.daemon_url,
            "--action",
            "snapshot",
            "--session",
            "mock",
        )

        response = json.loads(result.stdout)
        self.assertTrue(response["ok"])
        self.assertEqual(response["data"]["title"], "Mock GPU Daily")

    def test_invoke_sh_rejects_args_json_and_args_file_together(self):
        with tempfile.NamedTemporaryFile("w", encoding="utf-8") as handle:
            handle.write("{}")
            handle.flush()
            result = self.run_bash_cli(
                SCRIPTS / "invoke.sh",
                "--action",
                "snapshot",
                "--args-json",
                "{}",
                "--args-file",
                handle.name,
                "--dry-run",
                expected=2,
            )

        self.assertIn("Use either --args-json or --args-file, not both.", result.stderr)

    def test_invoke_ps1_args_file_posts_utf8_json_to_mock_daemon(self):
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", suffix=".json", delete=False
        ) as handle:
            json.dump(
                {
                    "selector": "@e1",
                    "value": "显卡日报",
                    "nested": {"enabled": True, "count": 2},
                },
                handle,
                ensure_ascii=False,
            )
            args_path = Path(handle.name)

        try:
            result = self.run_pwsh_cli(
                "-File",
                str(SCRIPTS / "invoke.ps1"),
                "-DaemonUrl",
                self.daemon_url,
                "-Action",
                "fill",
                "-Session",
                "mock",
                "-ArgsFile",
                str(args_path),
            )
        finally:
            args_path.unlink(missing_ok=True)

        response = json.loads(result.stdout)
        echo = response["data"]["echo"]
        self.assertEqual(echo["session"], "mock")
        self.assertEqual(echo["args"]["selector"], "@e1")
        self.assertEqual(echo["args"]["value"], "显卡日报")
        self.assertEqual(echo["args"]["nested"], {"enabled": True, "count": 2})

    def test_invoke_ps1_action_args_dry_run_serializes_hashtable(self):
        command = (
            f"& '{SCRIPTS / 'invoke.ps1'}' "
            "-Action fill "
            "-ActionArgs @{selector='@e1'; value='显卡日报'; nested=@{enabled=$true; count=2}} "
            "-Session demo "
            "-DryRun"
        )

        result = self.run_pwsh_cli("-Command", command)

        payload = json.loads(result.stdout)
        self.assertEqual(payload["action"], "fill")
        self.assertEqual(payload["session"], "demo")
        self.assertEqual(payload["args"]["value"], "显卡日报")
        self.assertEqual(payload["args"]["nested"], {"enabled": True, "count": 2})

    def test_invoke_ps1_preserves_http_error_body(self):
        result = self.run_pwsh_cli(
            "-File",
            str(SCRIPTS / "invoke.ps1"),
            "-DaemonUrl",
            self.daemon_url,
            "-Action",
            "fail-http",
            expected=1,
        )

        self.assertIn("daemon says no", result.stderr)

    def test_snapshot_py_reads_compact_snapshot(self):
        result = self.run_python_cli(
            SCRIPTS / "snapshot.py",
            "--daemon-url",
            self.daemon_url,
            "--session",
            "mock",
            "--mode",
            "compact",
        )

        response = json.loads(result.stdout)
        self.assertEqual(response["elements"][0]["name"], "显卡日报 ready")
        self.assertEqual(response["elements"][0]["usage"], "use selector @e1 with click or fill")

    def test_wait_for_py_matches_visible_text(self):
        result = self.run_python_cli(
            SCRIPTS / "wait_for.py",
            "--daemon-url",
            self.daemon_url,
            "--session",
            "mock",
            "--text-contains",
            "显卡日报",
            "--timeout",
            "1",
            "--interval",
            "10",
        )

        response = json.loads(result.stdout)
        self.assertTrue(response["matched"])

    def test_wait_for_py_timeout_is_not_extended_by_large_interval(self):
        started = time.monotonic()
        result = self.run_python_cli(
            SCRIPTS / "wait_for.py",
            "--daemon-url",
            self.daemon_url,
            "--session",
            "no-match",
            "--text-contains",
            "显卡日报",
            "--timeout",
            "0.2",
            "--interval",
            "10",
            expected=1,
            timeout=2,
        )
        elapsed = time.monotonic() - started

        response = json.loads(result.stdout)
        self.assertFalse(response["matched"])
        self.assertLess(elapsed, 1.0)

    def test_screenshot_py_accepts_path_response(self):
        result = self.run_python_cli(
            SCRIPTS / "screenshot.py",
            "--daemon-url",
            self.daemon_url,
            "--session",
            "mock",
        )

        self.assertEqual(Path(result.stdout.strip()), self.screenshot_path.resolve())

    def test_screenshot_py_accepts_base64_response(self):
        output_path = Path(self.tempdir.name) / "base64.png"
        result = self.run_python_cli(
            SCRIPTS / "screenshot.py",
            "--daemon-url",
            self.daemon_url,
            "--session",
            "base64-shot",
            "--output",
            str(output_path),
        )

        self.assertEqual(Path(result.stdout.strip()), output_path.resolve())
        self.assertEqual(output_path.read_bytes(), b"fake-image-bytes")

    def test_screenshot_ps1_accepts_path_response(self):
        result = self.run_pwsh_cli(
            "-File",
            str(SCRIPTS / "screenshot.ps1"),
            "-DaemonUrl",
            self.daemon_url,
            "-Session",
            "mock",
        )

        self.assertEqual(Path(result.stdout.strip()), self.screenshot_path.resolve())

    def test_screenshot_ps1_accepts_base64_response(self):
        output_path = Path(self.tempdir.name) / "base64-ps1.png"
        result = self.run_pwsh_cli(
            "-File",
            str(SCRIPTS / "screenshot.ps1"),
            "-DaemonUrl",
            self.daemon_url,
            "-Session",
            "base64-shot",
            "-OutputPath",
            str(output_path),
        )

        self.assertEqual(Path(result.stdout.strip()), output_path.resolve())
        self.assertEqual(output_path.read_bytes(), b"fake-image-bytes")

    def test_screenshot_ps1_preserves_http_error_body(self):
        result = self.run_pwsh_cli(
            "-File",
            str(SCRIPTS / "screenshot.ps1"),
            "-DaemonUrl",
            self.daemon_url,
            "-Session",
            "fail-http",
            expected=1,
        )

        self.assertIn("daemon says no", result.stderr)


if __name__ == "__main__":
    unittest.main()
