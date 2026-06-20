#!/usr/bin/env python3

import base64
import json
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
            if session == "base64-shot":
                body = {
                    "ok": True,
                    "data": {
                        "data": base64.b64encode(b"fake-image-bytes").decode("ascii")
                    },
                }
            else:
                body = {"ok": True, "data": {"path": self.server.screenshot_path}}
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
        result = subprocess.run(
            [str(command), *args],
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        self.assertEqual(result.returncode, expected, result.stderr or result.stdout)
        return result

    def run_python_cli(self, script, *args, expected=0, timeout=5):
        return self.run_cli(sys.executable, str(script), *args, expected=expected, timeout=timeout)

    def test_invoke_sh_posts_to_mock_daemon(self):
        result = self.run_cli(
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
            result = self.run_cli(
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


if __name__ == "__main__":
    unittest.main()
