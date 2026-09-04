#!/usr/bin/env python3

import base64
import json
import os
import shutil
import socket
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

    def run_cli(
        self,
        command,
        *args,
        expected=0,
        timeout=5,
        input_text=None,
        env_extra=None,
        cwd=None,
    ):
        env = os.environ.copy()
        env.setdefault("PYTHONIOENCODING", "utf-8")
        if env_extra:
            env.update(env_extra)
        result = subprocess.run(
            [str(command), *args],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            timeout=timeout,
            input=input_text,
            cwd=cwd,
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

    def run_bash_cli(
        self,
        script,
        *args,
        expected=0,
        timeout=5,
        input_text=None,
        env_extra=None,
        cwd=None,
    ):
        executable = self.bash_executable()
        if os.name == "nt":
            # Passing JSON directly from CreateProcess to MSYS2 bash loses or
            # rewrites brace/quote-heavy argv values. Reconstruct exact argv
            # inside Bash from environment variables, which matches an
            # interactive Git Bash invocation.
            bash_env = dict(env_extra or {})
            bash_env["WB_TEST_SCRIPT"] = str(script)
            bash_env["WB_TEST_ARGC"] = str(len(args))
            for index, value in enumerate(args):
                bash_env[f"WB_TEST_ARG_{index:04d}"] = str(value)
            wrapper = r'''
script="$(cygpath -u "$WB_TEST_SCRIPT")"
if [[ -n "${WB_TEST_PREPEND_PATH:-}" ]]; then
  export PATH="$(cygpath -u "$WB_TEST_PREPEND_PATH"):$PATH"
fi
if [[ -n "${WB_TEST_CURL_ARGS_LOG:-}" ]]; then
  export CURL_ARGS_LOG="$(cygpath -u "$WB_TEST_CURL_ARGS_LOG")"
fi
argv=()
for ((index=0; index<WB_TEST_ARGC; index++)); do
  name="$(printf 'WB_TEST_ARG_%04d' "$index")"
  argv+=("${!name}")
done
exec bash "$script" "${argv[@]}"
'''
            return self.run_cli(
                executable,
                "-c",
                wrapper,
                expected=expected,
                timeout=timeout,
                input_text=input_text,
                env_extra=bash_env,
                cwd=cwd,
            )
        return self.run_cli(
            executable,
            str(script),
            *args,
            expected=expected,
            timeout=timeout,
            input_text=input_text,
            env_extra=env_extra,
            cwd=cwd,
        )

    def run_pwsh_cli(self, *args, expected=0, timeout=15):
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

    def test_invoke_sh_rejects_empty_inline_json(self):
        result = self.run_bash_cli(
            SCRIPTS / "invoke.sh",
            "--action",
            "snapshot",
            "--args-json",
            "   ",
            "--dry-run",
            expected=2,
        )

        self.assertIn("Arguments JSON is empty.", result.stderr)

    def test_invoke_sh_rejects_malformed_and_non_object_json(self):
        for value, message in (
            ("{", "valid UTF-8 JSON"),
            ("[]", "must be an object"),
            ('{"value":NaN}', "non-finite JSON number"),
            ('{"value":Infinity}', "non-finite JSON number"),
            ('{"value":-Infinity}', "non-finite JSON number"),
        ):
            with self.subTest(value=value):
                result = self.run_bash_cli(
                    SCRIPTS / "invoke.sh",
                    "--action",
                    "snapshot",
                    "--args-json",
                    value,
                    "--dry-run",
                    expected=2,
                )
                self.assertIn(message, result.stderr)

    def test_invoke_sh_accepts_utf8_bom_args_file(self):
        with tempfile.NamedTemporaryFile("wb", delete=False) as handle:
            handle.write(b"\xef\xbb\xbf" + '{"code":"document.title"}'.encode("utf-8"))
            args_path = Path(handle.name)
        try:
            result = self.run_bash_cli(
                SCRIPTS / "invoke.sh",
                "--action",
                "evaluate",
                "--args-file",
                str(args_path),
                "--dry-run",
            )
        finally:
            args_path.unlink(missing_ok=True)

        self.assertEqual(json.loads(result.stdout)["args"]["code"], "document.title")

    def test_invoke_sh_refuses_close_session_without_force(self):
        result = self.run_bash_cli(
            SCRIPTS / "invoke.sh",
            "--action",
            "close_session",
            expected=2,
        )

        self.assertIn("Refusing close_session", result.stderr)

    def test_invoke_sh_help_lists_evaluate_code_argument(self):
        result = self.run_bash_cli(SCRIPTS / "invoke.sh", "--help")

        self.assertIn("evaluate  code", result.stdout)

    def test_invoke_sh_preserves_http_error_body_without_fail_with_body(self):
        result = self.run_bash_cli(
            SCRIPTS / "invoke.sh",
            "--daemon-url",
            self.daemon_url,
            "--action",
            "fail-http",
            expected=22,
        )

        self.assertIn("daemon says no", result.stdout)
        self.assertIn("HTTP 500", result.stderr)
        self.assertNotIn("--fail-with-body", (SCRIPTS / "invoke.sh").read_text())

    def test_invoke_sh_rejects_directory_output_target(self):
        with tempfile.TemporaryDirectory() as directory:
            result = self.run_bash_cli(
                SCRIPTS / "invoke.sh",
                "--action",
                "list_tabs",
                "--output",
                directory,
                expected=2,
            )

        self.assertIn("must be a file, not a directory", result.stderr)

    def test_invoke_sh_output_parent_starting_with_dash_is_not_an_option(self):
        with tempfile.TemporaryDirectory() as directory:
            result = self.run_bash_cli(
                SCRIPTS / "invoke.sh",
                "--daemon-url",
                self.daemon_url,
                "--action",
                "list_tabs",
                "--output",
                "-result/response.json",
                cwd=directory,
            )
            output = Path(directory) / "-result" / "response.json"
            response = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(result.stdout.strip(), "-result/response.json")
        self.assertTrue(response["ok"])

    def test_invoke_sh_rejects_non_http_daemon_url(self):
        result = self.run_bash_cli(
            SCRIPTS / "invoke.sh",
            "--daemon-url",
            "-K/tmp/curl-config",
            "--action",
            "list_tabs",
            "--dry-run",
            expected=2,
        )

        self.assertIn("must start with http:// or https://", result.stderr)

    def test_invoke_sh_preserves_connection_refused_exit_and_adds_guidance(self):
        with socket.socket() as reserved:
            reserved.bind(("127.0.0.1", 0))
            port = reserved.getsockname()[1]
            result = self.run_bash_cli(
                SCRIPTS / "invoke.sh",
                "--daemon-url",
                f"http://127.0.0.1:{port}",
                "--action",
                "list_tabs",
                expected=7,
            )

        self.assertIn("daemon is unreachable", result.stderr)
        self.assertIn("doctor.py --start --wait-connected 20", result.stderr)

    def test_invoke_sh_gives_navigate_transport_headroom(self):
        with tempfile.TemporaryDirectory() as directory:
            fake_dir = Path(directory)
            args_log = fake_dir / "curl-args.txt"
            fake_curl = fake_dir / "curl"
            fake_curl.write_text(
                """#!/usr/bin/env bash
printf '%s\\n' "$@" > "$CURL_ARGS_LOG"
output=""
while (($#)); do
  case "$1" in
    --output) output="$2"; shift 2 ;;
    --write-out) shift 2 ;;
    *) shift ;;
  esac
done
printf '{"ok":true}' > "$output"
printf '200'
""",
                encoding="utf-8",
            )
            fake_curl.chmod(0o755)
            result = self.run_bash_cli(
                SCRIPTS / "invoke.sh",
                "--action",
                "navigate",
                "--args-json",
                '{"url":"https://example.com"}',
                env_extra={
                    "PATH": f"{fake_dir}{os.pathsep}{os.environ['PATH']}",
                    "CURL_ARGS_LOG": str(args_log),
                    "WB_TEST_PREPEND_PATH": str(fake_dir),
                    "WB_TEST_CURL_ARGS_LOG": str(args_log),
                },
            )

            curl_args = args_log.read_text(encoding="utf-8").splitlines()

        self.assertEqual(json.loads(result.stdout), {"ok": True})
        self.assertEqual(curl_args[curl_args.index("--max-time") + 1], "45")
        self.assertIn("--globoff", curl_args)
        self.assertEqual(curl_args[curl_args.index("--url") + 1], "http://127.0.0.1:10086/command")

    def test_linux_autostart_helper_can_print_unit_without_changes(self):
        result = self.run_bash_cli(
            SCRIPTS / "install_linux_autostart.sh",
            "--binary",
            "/opt/kimi webbridge/kimi-webbridge",
            "--print-unit",
        )

        self.assertIn(
            'ExecStart="/opt/kimi webbridge/kimi-webbridge" start --foreground',
            result.stdout,
        )
        self.assertIn("WantedBy=default.target", result.stdout)
        self.assertIn("Managed by kimi-webbridge-pro", result.stdout)

    def test_linux_autostart_helper_rejects_unsafe_systemd_path(self):
        result = self.run_bash_cli(
            SCRIPTS / "install_linux_autostart.sh",
            "--binary",
            "/opt/%bad/kimi-webbridge",
            "--print-unit",
            expected=2,
        )

        self.assertIn("unsafe in a systemd", result.stderr)

    @unittest.skipUnless(sys.platform == "linux", "systemd user units are Linux-specific")
    def test_linux_autostart_helper_rejects_relative_config_home_without_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = self.run_bash_cli(
                SCRIPTS / "install_linux_autostart.sh",
                "--binary",
                "/missing/kimi-webbridge",
                expected=2,
                env_extra={"XDG_CONFIG_HOME": "relative-config"},
                cwd=root,
            )

            self.assertFalse((root / "relative-config").exists())

        self.assertIn("absolute path", result.stderr)

    @unittest.skipUnless(sys.platform == "linux", "flock directory locking is Linux-specific")
    def test_linux_autostart_refuses_concurrent_changes(self):
        import fcntl

        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "config"
            unit_dir = config / "systemd" / "user"
            unit_dir.mkdir(parents=True)
            lock_fd = os.open(unit_dir, os.O_RDONLY)
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                result = self.run_bash_cli(
                    SCRIPTS / "install_linux_autostart.sh",
                    "--uninstall",
                    expected=1,
                    env_extra={"XDG_CONFIG_HOME": str(config)},
                )
            finally:
                os.close(lock_fd)

        self.assertIn("already in progress", result.stderr)

    @unittest.skipUnless(sys.platform == "linux", "systemd user units are Linux-specific")
    def test_linux_autostart_modes_are_mutually_exclusive_without_side_effects(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "config"
            fake_bin = root / "bin"
            fake_bin.mkdir()
            systemctl_log = root / "systemctl.log"
            fake_systemctl = fake_bin / "systemctl"
            fake_systemctl.write_text(
                """#!/usr/bin/env bash
printf '%s\n' "$*" >> "$SYSTEMCTL_LOG"
if [[ "$*" == "--user is-active kimi-webbridge.service" ]]; then
  printf '%s\n' inactive
  exit 3
fi
exit 0
""",
                encoding="utf-8",
            )
            fake_systemctl.chmod(0o755)
            unit = config / "systemd" / "user" / "kimi-webbridge.service"
            unit.parent.mkdir(parents=True)
            unit.write_text(
                "# Managed by kimi-webbridge-pro install_linux_autostart.sh\n",
                encoding="utf-8",
            )

            for options in (
                ("--print-unit", "--uninstall"),
                ("--uninstall", "--print-unit"),
            ):
                with self.subTest(options=options):
                    result = self.run_bash_cli(
                        SCRIPTS / "install_linux_autostart.sh",
                        *options,
                        expected=2,
                        env_extra={
                            "SYSTEMCTL_LOG": str(systemctl_log),
                            "XDG_CONFIG_HOME": str(config),
                            "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
                        },
                    )
                    self.assertIn("Use only one", result.stderr)

            self.assertTrue(unit.exists())
            self.assertFalse(systemctl_log.exists())

    @unittest.skipUnless(sys.platform == "linux", "systemd user units are Linux-specific")
    def test_linux_autostart_install_starts_before_enabling(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "config"
            fake_bin = root / "bin"
            fake_bin.mkdir()
            daemon_log = root / "daemon.log"
            systemctl_log = root / "systemctl.log"
            runtime_state = root / "runtime.state"
            enable_state = root / "enable.state"
            daemon = root / "kimi-webbridge"
            daemon.write_text(
                """#!/usr/bin/env bash
printf '%s\n' "$*" >> "$DAEMON_LOG"
if [[ "$*" == "start --help" ]]; then printf '%s\n' '--foreground'; fi
if [[ "$*" == "status" ]]; then printf '%s\n' '{"running":false}'; fi
exit 0
""",
                encoding="utf-8",
            )
            daemon.chmod(0o755)
            fake_systemctl = fake_bin / "systemctl"
            fake_systemctl.write_text(
                """#!/usr/bin/env bash
printf '%s\n' "$*" >> "$SYSTEMCTL_LOG"
if [[ "$*" == "--user show kimi-webbridge.service --property=FragmentPath --value" ]]; then
  if [[ -e "$UNIT_FILE" ]]; then printf '%s\n' "$UNIT_FILE"; fi
  exit 0
fi
if [[ "$*" == "--user show kimi-webbridge.service --property=DropInPaths --value" ]]; then exit 0; fi
if [[ "$*" == "--user is-enabled kimi-webbridge.service" ]]; then
  if [[ -f "$ENABLE_STATE" ]]; then printf '%s\n' enabled; exit 0; fi
  printf '%s\n' not-found
  exit 1
fi
if [[ "$*" == "--user is-active kimi-webbridge.service" ]]; then
  if [[ -f "$RUNTIME_STATE" ]]; then printf '%s\n' active; exit 0; fi
  printf '%s\n' inactive
  exit 3
fi
if [[ "$*" == "--user is-active --quiet kimi-webbridge.service" ]]; then [[ -f "$RUNTIME_STATE" ]]; exit $?; fi
if [[ "$*" == "--user stop kimi-webbridge.service" ]]; then rm -f -- "$RUNTIME_STATE"; exit 0; fi
if [[ "$*" == "--user start kimi-webbridge.service" ]]; then : > "$RUNTIME_STATE"; exit 0; fi
if [[ "$*" == "--user enable kimi-webbridge.service" ]]; then : > "$ENABLE_STATE"; exit 0; fi
exit 0
""",
                encoding="utf-8",
            )
            fake_systemctl.chmod(0o755)

            self.run_bash_cli(
                SCRIPTS / "install_linux_autostart.sh",
                "--binary",
                str(daemon),
                env_extra={
                    "DAEMON_LOG": str(daemon_log),
                    "ENABLE_STATE": str(enable_state),
                    "RUNTIME_STATE": str(runtime_state),
                    "SYSTEMCTL_LOG": str(systemctl_log),
                    "UNIT_FILE": str(config / "systemd" / "user" / "kimi-webbridge.service"),
                    "XDG_CONFIG_HOME": str(config),
                    "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
                },
            )

            calls = systemctl_log.read_text(encoding="utf-8").splitlines()
            unit = config / "systemd" / "user" / "kimi-webbridge.service"
            unit_exists = unit.exists()
            unit_text = unit.read_text(encoding="utf-8")

        self.assertTrue(unit_exists)
        self.assertIn(f'ExecStart="{daemon}" start --foreground', unit_text)
        self.assertLess(
            calls.index("--user start kimi-webbridge.service"),
            calls.index("--user enable kimi-webbridge.service"),
        )

    @unittest.skipUnless(sys.platform == "linux", "systemd user units are Linux-specific")
    def test_linux_autostart_install_rejects_enable_success_without_enabled_state(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "config"
            fake_bin = root / "bin"
            fake_bin.mkdir()
            daemon_log = root / "daemon.log"
            systemctl_log = root / "systemctl.log"
            daemon = root / "kimi-webbridge"
            daemon.write_text(
                """#!/usr/bin/env bash
printf '%s\n' "$*" >> "$DAEMON_LOG"
if [[ "$*" == "start --help" ]]; then printf '%s\n' '--foreground'; exit 0; fi
if [[ "$*" == "status" ]]; then printf '%s\n' '{"running":false}'; exit 0; fi
exit 99
""",
                encoding="utf-8",
            )
            daemon.chmod(0o755)
            unit = config / "systemd" / "user" / "kimi-webbridge.service"
            fake_systemctl = fake_bin / "systemctl"
            fake_systemctl.write_text(
                """#!/usr/bin/env bash
printf '%s\n' "$*" >> "$SYSTEMCTL_LOG"
if [[ "$*" == "--user show kimi-webbridge.service --property=FragmentPath --value" ]]; then
  if [[ -e "$UNIT_FILE" ]]; then printf '%s\n' "$UNIT_FILE"; fi
  exit 0
fi
if [[ "$*" == "--user show kimi-webbridge.service --property=DropInPaths --value" ]]; then exit 0; fi
if [[ "$*" == "--user is-active kimi-webbridge.service" ]]; then printf '%s\n' inactive; exit 3; fi
if [[ "$*" == "--user is-active --quiet kimi-webbridge.service" ]]; then exit 0; fi
if [[ "$*" == "--user is-enabled kimi-webbridge.service" ]]; then
  if [[ -e "$UNIT_FILE" ]]; then printf '%s\n' disabled; else printf '%s\n' not-found; fi
  exit 1
fi
if [[ "$*" == "--user daemon-reload" ]]; then exit 0; fi
if [[ "$*" == "--user stop kimi-webbridge.service" ]]; then exit 0; fi
if [[ "$*" == "--user start kimi-webbridge.service" ]]; then exit 0; fi
if [[ "$*" == "--user enable kimi-webbridge.service" ]]; then exit 0; fi
if [[ "$*" == "--user disable --now kimi-webbridge.service" ]]; then exit 0; fi
exit 99
""",
                encoding="utf-8",
            )
            fake_systemctl.chmod(0o755)

            result = self.run_bash_cli(
                SCRIPTS / "install_linux_autostart.sh",
                "--binary",
                str(daemon),
                expected=1,
                env_extra={
                    "DAEMON_LOG": str(daemon_log),
                    "SYSTEMCTL_LOG": str(systemctl_log),
                    "UNIT_FILE": str(unit),
                    "XDG_CONFIG_HOME": str(config),
                    "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
                },
            )

            unit_exists = unit.exists()

        self.assertFalse(unit_exists)
        self.assertNotIn("Installed and enabled", result.stdout)
        self.assertIn("did not become enabled", result.stderr)

    @unittest.skipUnless(sys.platform == "linux", "systemd user units are Linux-specific")
    def test_linux_autostart_install_aborts_when_service_state_is_unknown(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "config"
            fake_bin = root / "bin"
            fake_bin.mkdir()
            daemon_log = root / "daemon.log"
            systemctl_log = root / "systemctl.log"
            daemon = root / "kimi-webbridge"
            daemon.write_text(
                """#!/usr/bin/env bash
printf '%s\n' "$*" >> "$DAEMON_LOG"
if [[ "$*" == "start --help" ]]; then printf '%s\n' '--foreground'; fi
exit 0
""",
                encoding="utf-8",
            )
            daemon.chmod(0o755)
            fake_systemctl = fake_bin / "systemctl"
            fake_systemctl.write_text(
                """#!/usr/bin/env bash
printf '%s\n' "$*" >> "$SYSTEMCTL_LOG"
exit 1
""",
                encoding="utf-8",
            )
            fake_systemctl.chmod(0o755)

            result = self.run_bash_cli(
                SCRIPTS / "install_linux_autostart.sh",
                "--binary",
                str(daemon),
                expected=1,
                env_extra={
                    "DAEMON_LOG": str(daemon_log),
                    "SYSTEMCTL_LOG": str(systemctl_log),
                    "XDG_CONFIG_HOME": str(config),
                    "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
                },
            )

            unit = config / "systemd" / "user" / "kimi-webbridge.service"
            daemon_calls = daemon_log.read_text(encoding="utf-8").splitlines()

        self.assertFalse(unit.exists())
        self.assertEqual(daemon_calls, ["start --help"])
        self.assertIn("Could not determine whether", result.stderr)
        self.assertIn("no changes were made", result.stderr)

    @unittest.skipUnless(sys.platform == "linux", "systemd user units are Linux-specific")
    def test_linux_autostart_install_aborts_when_enablement_state_is_unknown(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "config"
            fake_bin = root / "bin"
            fake_bin.mkdir()
            daemon_log = root / "daemon.log"
            systemctl_log = root / "systemctl.log"
            daemon = root / "kimi-webbridge"
            daemon.write_text(
                """#!/usr/bin/env bash
printf '%s\n' "$*" >> "$DAEMON_LOG"
if [[ "$*" == "start --help" ]]; then printf '%s\n' '--foreground'; fi
exit 0
""",
                encoding="utf-8",
            )
            daemon.chmod(0o755)
            fake_systemctl = fake_bin / "systemctl"
            fake_systemctl.write_text(
                """#!/usr/bin/env bash
printf '%s\n' "$*" >> "$SYSTEMCTL_LOG"
if [[ "$*" == "--user show kimi-webbridge.service --property=FragmentPath --value" ]]; then
  printf '%s\n' "$UNIT_FILE"
  exit 0
fi
if [[ "$*" == "--user show kimi-webbridge.service --property=DropInPaths --value" ]]; then exit 0; fi
if [[ "$*" == "--user is-enabled kimi-webbridge.service" ]]; then
  printf '%s\n' masked
  exit 1
fi
exit 0
""",
                encoding="utf-8",
            )
            fake_systemctl.chmod(0o755)
            unit = config / "systemd" / "user" / "kimi-webbridge.service"
            unit.parent.mkdir(parents=True)
            previous_unit = (
                "# Managed by kimi-webbridge-pro install_linux_autostart.sh\n"
                "[Service]\nExecStart=/previous/kimi-webbridge\n"
            )
            unit.write_text(previous_unit, encoding="utf-8")

            result = self.run_bash_cli(
                SCRIPTS / "install_linux_autostart.sh",
                "--binary",
                str(daemon),
                expected=1,
                env_extra={
                    "DAEMON_LOG": str(daemon_log),
                    "SYSTEMCTL_LOG": str(systemctl_log),
                    "XDG_CONFIG_HOME": str(config),
                    "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
                },
            )

            restored_unit = unit.read_text(encoding="utf-8")
            daemon_calls = daemon_log.read_text(encoding="utf-8").splitlines()
            systemctl_calls = systemctl_log.read_text(encoding="utf-8").splitlines()

        self.assertEqual(restored_unit, previous_unit)
        self.assertEqual(daemon_calls, ["start --help"])
        self.assertEqual(
            systemctl_calls,
            ["--user is-enabled kimi-webbridge.service"],
        )
        self.assertIn("enabled", result.stderr)
        self.assertIn("no changes were made", result.stderr)

    @unittest.skipUnless(sys.platform == "linux", "systemd user units are Linux-specific")
    def test_linux_autostart_install_aborts_when_direct_status_is_unknown(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "config"
            fake_bin = root / "bin"
            fake_bin.mkdir()
            daemon_log = root / "daemon.log"
            daemon = root / "kimi-webbridge"
            daemon.write_text(
                """#!/usr/bin/env bash
printf '%s\n' "$*" >> "$DAEMON_LOG"
if [[ "$*" == "start --help" ]]; then printf '%s\n' '--foreground'; fi
if [[ "$*" == "status" ]]; then printf '%s\n' '{"running":false}' '{"running":true}'; fi
exit 0
""",
                encoding="utf-8",
            )
            daemon.chmod(0o755)
            unit = config / "systemd" / "user" / "kimi-webbridge.service"
            unit.parent.mkdir(parents=True)
            previous_unit = (
                "# Managed by kimi-webbridge-pro install_linux_autostart.sh\n"
                "[Service]\nExecStart=/previous/kimi-webbridge\n"
            )
            unit.write_text(previous_unit, encoding="utf-8")
            fake_systemctl = fake_bin / "systemctl"
            fake_systemctl.write_text(
                """#!/usr/bin/env bash
if [[ "$*" == "--user is-enabled kimi-webbridge.service" ]]; then
  printf '%s\n' disabled
  exit 1
fi
if [[ "$*" == "--user is-active kimi-webbridge.service" ]]; then
  printf '%s\n' inactive
  exit 4
fi
exit 0
""",
                encoding="utf-8",
            )
            fake_systemctl.chmod(0o755)

            result = self.run_bash_cli(
                SCRIPTS / "install_linux_autostart.sh",
                "--binary",
                str(daemon),
                expected=1,
                env_extra={
                    "DAEMON_LOG": str(daemon_log),
                    "XDG_CONFIG_HOME": str(config),
                    "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
                },
            )

            daemon_calls = daemon_log.read_text(encoding="utf-8").splitlines()
            restored_unit = unit.read_text(encoding="utf-8")
            backups = list(unit.parent.glob("kimi-webbridge.service.backup.*"))

        self.assertEqual(restored_unit, previous_unit)
        self.assertEqual(backups, [])
        self.assertEqual(daemon_calls, ["start --help", "status"])
        self.assertIn("valid running boolean", result.stderr)

    @unittest.skipUnless(sys.platform == "linux", "systemd user units are Linux-specific")
    def test_linux_autostart_install_rejects_effective_unit_dropins_before_stop(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "config"
            fake_bin = root / "bin"
            fake_bin.mkdir()
            daemon_log = root / "daemon.log"
            systemctl_log = root / "systemctl.log"
            unit = config / "systemd" / "user" / "kimi-webbridge.service"
            daemon = root / "kimi-webbridge"
            daemon.write_text(
                """#!/usr/bin/env bash
printf '%s\n' "$*" >> "$DAEMON_LOG"
if [[ "$*" == "start --help" ]]; then printf '%s\n' '--foreground'; fi
if [[ "$*" == "status" ]]; then printf '%s\n' '{"running":false}'; fi
exit 0
""",
                encoding="utf-8",
            )
            daemon.chmod(0o755)
            fake_systemctl = fake_bin / "systemctl"
            fake_systemctl.write_text(
                """#!/usr/bin/env bash
printf '%s\n' "$*" >> "$SYSTEMCTL_LOG"
if [[ "$*" == "--user is-active kimi-webbridge.service" ]]; then
  printf '%s\n' inactive
  exit 4
fi
if [[ "$*" == "--user show kimi-webbridge.service --property=FragmentPath --value" ]]; then
  printf '%s\n' "$UNIT_FILE"
  exit 0
fi
if [[ "$*" == "--user show kimi-webbridge.service --property=DropInPaths --value" ]]; then
  printf '%s\n' /etc/systemd/user/kimi-webbridge.service.d/override.conf
  exit 0
fi
exit 0
""",
                encoding="utf-8",
            )
            fake_systemctl.chmod(0o755)

            result = self.run_bash_cli(
                SCRIPTS / "install_linux_autostart.sh",
                "--binary",
                str(daemon),
                expected=1,
                env_extra={
                    "DAEMON_LOG": str(daemon_log),
                    "SYSTEMCTL_LOG": str(systemctl_log),
                    "UNIT_FILE": str(unit),
                    "XDG_CONFIG_HOME": str(config),
                    "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
                },
            )

            daemon_calls = daemon_log.read_text(encoding="utf-8").splitlines()
            systemctl_calls = systemctl_log.read_text(encoding="utf-8").splitlines()

        self.assertFalse(unit.exists())
        self.assertNotIn("stop", daemon_calls)
        self.assertNotIn("--user stop kimi-webbridge.service", systemctl_calls)
        self.assertIn("Refusing to shadow", result.stderr)
        self.assertIn("no changes were made", result.stderr)

    @unittest.skipUnless(sys.platform == "linux", "systemd user units are Linux-specific")
    def test_linux_autostart_install_restores_previously_active_service(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "config"
            fake_bin = root / "bin"
            fake_bin.mkdir()
            daemon_log = root / "daemon.log"
            systemctl_log = root / "systemctl.log"
            active_count = root / "active.count"
            daemon = root / "kimi-webbridge"
            daemon.write_text(
                """#!/usr/bin/env bash
printf '%s\n' "$*" >> "$DAEMON_LOG"
if [[ "$*" == "start --help" ]]; then printf '%s\n' '--foreground'; fi
exit 0
""",
                encoding="utf-8",
            )
            daemon.chmod(0o755)
            fake_systemctl = fake_bin / "systemctl"
            fake_systemctl.write_text(
                """#!/usr/bin/env bash
printf '%s\n' "$*" >> "$SYSTEMCTL_LOG"
if [[ "$*" == "--user show kimi-webbridge.service --property=FragmentPath --value" ]]; then
  printf '%s\n' "$UNIT_FILE"
  exit 0
fi
if [[ "$*" == "--user show kimi-webbridge.service --property=DropInPaths --value" ]]; then exit 0; fi
if [[ "$*" == "--user is-active kimi-webbridge.service" ]]; then
  count=0
  if [[ -f "$ACTIVE_COUNT" ]]; then read -r count < "$ACTIVE_COUNT"; fi
  printf '%s\n' "$((count + 1))" > "$ACTIVE_COUNT"
  if [[ "$count" == 0 || "$count" == 3 ]]; then printf '%s\n' active; exit 0; fi
  printf '%s\n' inactive
  exit 3
fi
if [[ "$*" == "--user is-enabled kimi-webbridge.service" ]]; then
  printf '%s\n' enabled-runtime
  exit 0
fi
if [[ "$*" == "--user start kimi-webbridge.service" ]]; then
  grep -Fq '/previous/kimi-webbridge' "$UNIT_FILE"
  exit $?
fi
exit 0
""",
                encoding="utf-8",
            )
            fake_systemctl.chmod(0o755)
            unit = config / "systemd" / "user" / "kimi-webbridge.service"
            unit.parent.mkdir(parents=True)
            previous_unit = (
                "# Managed by kimi-webbridge-pro install_linux_autostart.sh\n"
                "[Service]\nExecStart=\"/previous/kimi-webbridge\" start --foreground\n"
            )
            unit.write_text(previous_unit, encoding="utf-8")

            result = self.run_bash_cli(
                SCRIPTS / "install_linux_autostart.sh",
                "--binary",
                str(daemon),
                expected=1,
                env_extra={
                    "ACTIVE_COUNT": str(active_count),
                    "DAEMON_LOG": str(daemon_log),
                    "SYSTEMCTL_LOG": str(systemctl_log),
                    "UNIT_FILE": str(unit),
                    "XDG_CONFIG_HOME": str(config),
                    "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
                },
            )

            restored_unit = unit.read_text(encoding="utf-8")
            daemon_calls = daemon_log.read_text(encoding="utf-8").splitlines()
            systemctl_calls = systemctl_log.read_text(encoding="utf-8").splitlines()

        self.assertEqual(restored_unit, previous_unit)
        self.assertNotIn("start", daemon_calls)
        self.assertEqual(
            systemctl_calls.count("--user start kimi-webbridge.service"),
            2,
        )
        self.assertIn(
            "--user enable --runtime kimi-webbridge.service",
            systemctl_calls,
        )
        self.assertNotIn("--user enable kimi-webbridge.service", systemctl_calls)
        self.assertIn("rolled back", result.stderr)
        self.assertIn("Restored the previously active managed service", result.stderr)

    @unittest.skipUnless(sys.platform == "linux", "systemd user units are Linux-specific")
    def test_linux_autostart_install_does_not_start_cached_new_unit_after_reload_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "config"
            fake_bin = root / "bin"
            fake_bin.mkdir()
            daemon_log = root / "daemon.log"
            systemctl_log = root / "systemctl.log"
            reload_count = root / "reload.count"
            active_count = root / "active.count"
            daemon = root / "new-kimi-webbridge"
            daemon.write_text(
                """#!/usr/bin/env bash
printf '%s\n' "$*" >> "$DAEMON_LOG"
if [[ "$*" == "start --help" ]]; then printf '%s\n' '--foreground'; fi
exit 0
""",
                encoding="utf-8",
            )
            daemon.chmod(0o755)
            unit = config / "systemd" / "user" / "kimi-webbridge.service"
            unit.parent.mkdir(parents=True)
            previous_unit = (
                "# Managed by kimi-webbridge-pro install_linux_autostart.sh\n"
                "[Service]\nExecStart=\"/previous/kimi-webbridge\" start --foreground\n"
            )
            unit.write_text(previous_unit, encoding="utf-8")
            fake_systemctl = fake_bin / "systemctl"
            fake_systemctl.write_text(
                """#!/usr/bin/env bash
printf '%s\n' "$*" >> "$SYSTEMCTL_LOG"
if [[ "$*" == "--user show kimi-webbridge.service --property=FragmentPath --value" ]]; then
  printf '%s\n' "$UNIT_FILE"
  exit 0
fi
if [[ "$*" == "--user show kimi-webbridge.service --property=DropInPaths --value" ]]; then exit 0; fi
if [[ "$*" == "--user is-enabled kimi-webbridge.service" ]]; then
  printf '%s\n' enabled
  exit 0
fi
if [[ "$*" == "--user is-active kimi-webbridge.service" ]]; then
  count=0
  if [[ -f "$ACTIVE_COUNT" ]]; then read -r count < "$ACTIVE_COUNT"; fi
  printf '%s\n' "$((count + 1))" > "$ACTIVE_COUNT"
  if [[ "$count" == 0 ]]; then printf '%s\n' active; exit 0; fi
  printf '%s\n' inactive
  exit 3
fi
if [[ "$*" == "--user daemon-reload" ]]; then
  count=0
  if [[ -f "$RELOAD_COUNT" ]]; then read -r count < "$RELOAD_COUNT"; fi
  printf '%s\n' "$((count + 1))" > "$RELOAD_COUNT"
  if [[ "$count" != 0 ]]; then exit 1; fi
fi
if [[ "$*" == "--user start kimi-webbridge.service" ]]; then exit 1; fi
exit 0
""",
                encoding="utf-8",
            )
            fake_systemctl.chmod(0o755)

            result = self.run_bash_cli(
                SCRIPTS / "install_linux_autostart.sh",
                "--binary",
                str(daemon),
                expected=1,
                env_extra={
                    "ACTIVE_COUNT": str(active_count),
                    "DAEMON_LOG": str(daemon_log),
                    "RELOAD_COUNT": str(reload_count),
                    "SYSTEMCTL_LOG": str(systemctl_log),
                    "UNIT_FILE": str(unit),
                    "XDG_CONFIG_HOME": str(config),
                    "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
                },
            )

            restored_unit = unit.read_text(encoding="utf-8")
            daemon_calls = daemon_log.read_text(encoding="utf-8").splitlines()
            systemctl_calls = systemctl_log.read_text(encoding="utf-8").splitlines()

        self.assertEqual(restored_unit, previous_unit)
        self.assertNotIn("start", daemon_calls)
        self.assertEqual(
            systemctl_calls.count("--user start kimi-webbridge.service"),
            1,
        )
        self.assertIn("could not reload the restored unit", result.stderr)
        self.assertIn("was not started automatically", result.stderr)

    @unittest.skipUnless(sys.platform == "linux", "systemd user units are Linux-specific")
    def test_linux_autostart_install_rejects_wrong_effective_unit_after_rollback(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "config"
            fake_bin = root / "bin"
            fake_bin.mkdir()
            daemon_log = root / "daemon.log"
            systemctl_log = root / "systemctl.log"
            active_count = root / "active.count"
            show_count = root / "show.count"
            daemon = root / "new-kimi-webbridge"
            daemon.write_text(
                """#!/usr/bin/env bash
printf '%s\n' "$*" >> "$DAEMON_LOG"
if [[ "$*" == "start --help" ]]; then printf '%s\n' '--foreground'; exit 0; fi
exit 99
""",
                encoding="utf-8",
            )
            daemon.chmod(0o755)
            unit = config / "systemd" / "user" / "kimi-webbridge.service"
            unit.parent.mkdir(parents=True)
            previous_unit = (
                "# Managed by kimi-webbridge-pro install_linux_autostart.sh\n"
                "[Service]\nExecStart=/previous/kimi-webbridge\n"
            )
            unit.write_text(previous_unit, encoding="utf-8")
            fake_systemctl = fake_bin / "systemctl"
            fake_systemctl.write_text(
                """#!/usr/bin/env bash
printf '%s\n' "$*" >> "$SYSTEMCTL_LOG"
if [[ "$*" == "--user is-enabled kimi-webbridge.service" ]]; then printf '%s\n' enabled; exit 0; fi
if [[ "$*" == "--user is-active kimi-webbridge.service" ]]; then
  count=0
  if [[ -f "$ACTIVE_COUNT" ]]; then read -r count < "$ACTIVE_COUNT"; fi
  printf '%s\n' "$((count + 1))" > "$ACTIVE_COUNT"
  if [[ "$count" == 0 ]]; then printf '%s\n' active; exit 0; fi
  printf '%s\n' inactive
  exit 3
fi
if [[ "$*" == "--user show kimi-webbridge.service --property=FragmentPath --value" ]]; then
  count=0
  if [[ -f "$SHOW_COUNT" ]]; then read -r count < "$SHOW_COUNT"; fi
  printf '%s\n' "$((count + 1))" > "$SHOW_COUNT"
  if [[ "$count" == 0 ]]; then printf '%s\n' "$UNIT_FILE"; else printf '%s\n' /usr/lib/systemd/user/kimi-webbridge.service; fi
  exit 0
fi
if [[ "$*" == "--user show kimi-webbridge.service --property=DropInPaths --value" ]]; then exit 0; fi
if [[ "$*" == "--user daemon-reload" ]]; then exit 0; fi
if [[ "$*" == "--user stop kimi-webbridge.service" ]]; then exit 0; fi
if [[ "$*" == "--user start kimi-webbridge.service" ]]; then exit 1; fi
if [[ "$*" == "--user disable --now kimi-webbridge.service" ]]; then exit 0; fi
exit 99
""",
                encoding="utf-8",
            )
            fake_systemctl.chmod(0o755)

            result = self.run_bash_cli(
                SCRIPTS / "install_linux_autostart.sh",
                "--binary",
                str(daemon),
                expected=1,
                env_extra={
                    "ACTIVE_COUNT": str(active_count),
                    "DAEMON_LOG": str(daemon_log),
                    "SHOW_COUNT": str(show_count),
                    "SYSTEMCTL_LOG": str(systemctl_log),
                    "UNIT_FILE": str(unit),
                    "XDG_CONFIG_HOME": str(config),
                    "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
                },
            )

            restored_unit = unit.read_text(encoding="utf-8")
            systemctl_calls = systemctl_log.read_text(encoding="utf-8").splitlines()

        self.assertEqual(restored_unit, previous_unit)
        self.assertEqual(systemctl_calls.count("--user start kimi-webbridge.service"), 1)
        self.assertNotIn("Restored the previously active managed service", result.stderr)
        self.assertIn("could not reload the restored unit", result.stderr)
        self.assertIn("automatic restoration was incomplete", result.stderr)

    @unittest.skipUnless(sys.platform == "linux", "systemd user units are Linux-specific")
    def test_linux_autostart_install_signal_restores_unit_before_runtime_stop(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "config"
            fake_bin = root / "bin"
            fake_bin.mkdir()
            daemon_log = root / "daemon.log"
            systemctl_log = root / "systemctl.log"
            reload_count = root / "reload.count"
            daemon = root / "kimi-webbridge"
            daemon.write_text(
                """#!/usr/bin/env bash
printf '%s\n' "$*" >> "$DAEMON_LOG"
if [[ "$*" == "start --help" ]]; then printf '%s\n' '--foreground'; exit 0; fi
if [[ "$*" == "status" ]]; then printf '%s\n' '{"running":false}'; exit 0; fi
exit 99
""",
                encoding="utf-8",
            )
            daemon.chmod(0o755)
            unit = config / "systemd" / "user" / "kimi-webbridge.service"
            unit.parent.mkdir(parents=True)
            previous_unit = (
                "# Managed by kimi-webbridge-pro install_linux_autostart.sh\n"
                "[Service]\nExecStart=/previous/kimi-webbridge\n"
            )
            unit.write_text(previous_unit, encoding="utf-8")
            fake_systemctl = fake_bin / "systemctl"
            fake_systemctl.write_text(
                """#!/usr/bin/env bash
printf '%s\n' "$*" >> "$SYSTEMCTL_LOG"
if [[ "$*" == "--user is-enabled kimi-webbridge.service" ]]; then printf '%s\n' disabled; exit 1; fi
if [[ "$*" == "--user is-active kimi-webbridge.service" ]]; then printf '%s\n' inactive; exit 3; fi
if [[ "$*" == "--user daemon-reload" ]]; then
  count=0
  if [[ -f "$RELOAD_COUNT" ]]; then read -r count < "$RELOAD_COUNT"; fi
  printf '%s\n' "$((count + 1))" > "$RELOAD_COUNT"
  if [[ "$count" == 0 ]]; then kill -TERM "$PPID"; fi
  exit 0
fi
if [[ "$*" == "--user disable kimi-webbridge.service" ]]; then exit 0; fi
exit 99
""",
                encoding="utf-8",
            )
            fake_systemctl.chmod(0o755)

            result = self.run_bash_cli(
                SCRIPTS / "install_linux_autostart.sh",
                "--binary",
                str(daemon),
                expected=1,
                env_extra={
                    "DAEMON_LOG": str(daemon_log),
                    "RELOAD_COUNT": str(reload_count),
                    "SYSTEMCTL_LOG": str(systemctl_log),
                    "XDG_CONFIG_HOME": str(config),
                    "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
                },
            )

            restored_unit = unit.read_text(encoding="utf-8")
            systemctl_calls = systemctl_log.read_text(encoding="utf-8").splitlines()

        self.assertEqual(restored_unit, previous_unit)
        self.assertNotIn("--user stop kimi-webbridge.service", systemctl_calls)
        self.assertNotIn("--user start kimi-webbridge.service", systemctl_calls)
        self.assertIn("installation was interrupted", result.stderr)

    @unittest.skipUnless(sys.platform == "linux", "systemd user units are Linux-specific")
    def test_linux_autostart_install_signal_reports_incomplete_restore(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "config"
            fake_bin = root / "bin"
            fake_bin.mkdir()
            daemon_log = root / "daemon.log"
            systemctl_log = root / "systemctl.log"
            reload_count = root / "reload.count"
            copy_count = root / "copy.count"
            daemon = root / "new-kimi-webbridge"
            daemon.write_text(
                """#!/usr/bin/env bash
printf '%s\n' "$*" >> "$DAEMON_LOG"
if [[ "$*" == "start --help" ]]; then printf '%s\n' '--foreground'; exit 0; fi
exit 99
""",
                encoding="utf-8",
            )
            daemon.chmod(0o755)
            unit = config / "systemd" / "user" / "kimi-webbridge.service"
            unit.parent.mkdir(parents=True)
            previous_unit = (
                "# Managed by kimi-webbridge-pro install_linux_autostart.sh\n"
                "[Service]\nExecStart=/previous/kimi-webbridge\n"
            )
            unit.write_text(previous_unit, encoding="utf-8")
            fake_cp = fake_bin / "cp"
            fake_cp.write_text(
                """#!/usr/bin/env bash
count=0
if [[ -f "$COPY_COUNT" ]]; then read -r count < "$COPY_COUNT"; fi
printf '%s\n' "$((count + 1))" > "$COPY_COUNT"
if [[ "$count" == 0 ]]; then exec /bin/cp "$@"; fi
exit 1
""",
                encoding="utf-8",
            )
            fake_cp.chmod(0o755)
            fake_systemctl = fake_bin / "systemctl"
            fake_systemctl.write_text(
                """#!/usr/bin/env bash
printf '%s\n' "$*" >> "$SYSTEMCTL_LOG"
if [[ "$*" == "--user is-enabled kimi-webbridge.service" ]]; then printf '%s\n' enabled; exit 0; fi
if [[ "$*" == "--user is-active kimi-webbridge.service" ]]; then printf '%s\n' active; exit 0; fi
if [[ "$*" == "--user daemon-reload" ]]; then
  count=0
  if [[ -f "$RELOAD_COUNT" ]]; then read -r count < "$RELOAD_COUNT"; fi
  printf '%s\n' "$((count + 1))" > "$RELOAD_COUNT"
  if [[ "$count" == 0 ]]; then kill -TERM "$PPID"; fi
  exit 0
fi
exit 99
""",
                encoding="utf-8",
            )
            fake_systemctl.chmod(0o755)

            result = self.run_bash_cli(
                SCRIPTS / "install_linux_autostart.sh",
                "--binary",
                str(daemon),
                expected=1,
                env_extra={
                    "COPY_COUNT": str(copy_count),
                    "DAEMON_LOG": str(daemon_log),
                    "RELOAD_COUNT": str(reload_count),
                    "SYSTEMCTL_LOG": str(systemctl_log),
                    "XDG_CONFIG_HOME": str(config),
                    "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
                },
            )

            remaining_unit = unit.read_text(encoding="utf-8")

        self.assertIn(str(daemon), remaining_unit)
        self.assertIn("rollback was attempted", result.stderr)
        self.assertIn("automatic restoration was incomplete", result.stderr)
        self.assertNotIn("unit was rolled back", result.stderr)

    @unittest.skipUnless(sys.platform == "linux", "systemd user units are Linux-specific")
    def test_linux_autostart_install_never_falls_back_to_new_binary_for_old_service(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "config"
            fake_bin = root / "bin"
            fake_bin.mkdir()
            daemon_log = root / "daemon.log"
            systemctl_log = root / "systemctl.log"
            active_count = root / "active.count"
            daemon = root / "new-kimi-webbridge"
            daemon.write_text(
                """#!/usr/bin/env bash
printf '%s\n' "$*" >> "$DAEMON_LOG"
if [[ "$*" == "start --help" ]]; then printf '%s\n' '--foreground'; fi
exit 0
""",
                encoding="utf-8",
            )
            daemon.chmod(0o755)
            unit = config / "systemd" / "user" / "kimi-webbridge.service"
            unit.parent.mkdir(parents=True)
            previous_unit = (
                "# Managed by kimi-webbridge-pro install_linux_autostart.sh\n"
                "[Service]\nExecStart=\"/previous/kimi-webbridge\" start --foreground\n"
            )
            unit.write_text(previous_unit, encoding="utf-8")
            fake_systemctl = fake_bin / "systemctl"
            fake_systemctl.write_text(
                """#!/usr/bin/env bash
printf '%s\n' "$*" >> "$SYSTEMCTL_LOG"
if [[ "$*" == "--user show kimi-webbridge.service --property=FragmentPath --value" ]]; then
  printf '%s\n' "$UNIT_FILE"
  exit 0
fi
if [[ "$*" == "--user show kimi-webbridge.service --property=DropInPaths --value" ]]; then exit 0; fi
if [[ "$*" == "--user is-enabled kimi-webbridge.service" ]]; then
  printf '%s\n' enabled
  exit 0
fi
if [[ "$*" == "--user is-active kimi-webbridge.service" ]]; then
  count=0
  if [[ -f "$ACTIVE_COUNT" ]]; then read -r count < "$ACTIVE_COUNT"; fi
  printf '%s\n' "$((count + 1))" > "$ACTIVE_COUNT"
  if [[ "$count" == 0 ]]; then printf '%s\n' active; exit 0; fi
  printf '%s\n' inactive
  exit 3
fi
if [[ "$*" == "--user start kimi-webbridge.service" ]]; then exit 1; fi
exit 0
""",
                encoding="utf-8",
            )
            fake_systemctl.chmod(0o755)

            result = self.run_bash_cli(
                SCRIPTS / "install_linux_autostart.sh",
                "--binary",
                str(daemon),
                expected=1,
                env_extra={
                    "ACTIVE_COUNT": str(active_count),
                    "DAEMON_LOG": str(daemon_log),
                    "SYSTEMCTL_LOG": str(systemctl_log),
                    "UNIT_FILE": str(unit),
                    "XDG_CONFIG_HOME": str(config),
                    "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
                },
            )

            daemon_calls = daemon_log.read_text(encoding="utf-8").splitlines()
            systemctl_calls = systemctl_log.read_text(encoding="utf-8").splitlines()

        self.assertNotIn("start", daemon_calls)
        self.assertEqual(
            systemctl_calls.count("--user start kimi-webbridge.service"),
            2,
        )
        self.assertIn("automatic daemon recovery also failed", result.stderr)

    @unittest.skipUnless(sys.platform == "linux", "systemd user units are Linux-specific")
    def test_linux_autostart_install_does_not_start_old_unit_if_new_runtime_stays_active(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "config"
            fake_bin = root / "bin"
            fake_bin.mkdir()
            daemon_log = root / "daemon.log"
            systemctl_log = root / "systemctl.log"
            start_count = root / "start.count"
            active_count = root / "active.count"
            daemon = root / "new-kimi-webbridge"
            daemon.write_text(
                """#!/usr/bin/env bash
printf '%s\n' "$*" >> "$DAEMON_LOG"
if [[ "$*" == "start --help" ]]; then printf '%s\n' '--foreground'; exit 0; fi
exit 99
""",
                encoding="utf-8",
            )
            daemon.chmod(0o755)
            unit = config / "systemd" / "user" / "kimi-webbridge.service"
            unit.parent.mkdir(parents=True)
            previous_unit = (
                "# Managed by kimi-webbridge-pro install_linux_autostart.sh\n"
                "[Service]\nExecStart=/previous/kimi-webbridge start --foreground\n"
            )
            unit.write_text(previous_unit, encoding="utf-8")
            fake_systemctl = fake_bin / "systemctl"
            fake_systemctl.write_text(
                """#!/usr/bin/env bash
printf '%s\n' "$*" >> "$SYSTEMCTL_LOG"
if [[ "$*" == "--user is-enabled kimi-webbridge.service" ]]; then printf '%s\n' enabled; exit 0; fi
if [[ "$*" == "--user is-active kimi-webbridge.service" ]]; then
  count=0
  if [[ -f "$ACTIVE_COUNT" ]]; then read -r count < "$ACTIVE_COUNT"; fi
  printf '%s\n' "$((count + 1))" > "$ACTIVE_COUNT"
  if [[ "$count" == 1 ]]; then printf '%s\n' inactive; exit 3; fi
  printf '%s\n' active
  exit 0
fi
if [[ "$*" == "--user show kimi-webbridge.service --property=FragmentPath --value" ]]; then printf '%s\n' "$UNIT_FILE"; exit 0; fi
if [[ "$*" == "--user show kimi-webbridge.service --property=DropInPaths --value" ]]; then exit 0; fi
if [[ "$*" == "--user daemon-reload" ]]; then exit 0; fi
if [[ "$*" == "--user stop kimi-webbridge.service" ]]; then exit 0; fi
if [[ "$*" == "--user start kimi-webbridge.service" ]]; then
  count=0
  if [[ -f "$START_COUNT" ]]; then read -r count < "$START_COUNT"; fi
  printf '%s\n' "$((count + 1))" > "$START_COUNT"
  exit 0
fi
if [[ "$*" == "--user is-active --quiet kimi-webbridge.service" ]]; then exit 0; fi
if [[ "$*" == "--user enable kimi-webbridge.service" ]]; then exit 1; fi
if [[ "$*" == "--user disable --now kimi-webbridge.service" ]]; then exit 0; fi
exit 99
""",
                encoding="utf-8",
            )
            fake_systemctl.chmod(0o755)

            result = self.run_bash_cli(
                SCRIPTS / "install_linux_autostart.sh",
                "--binary",
                str(daemon),
                expected=1,
                env_extra={
                    "ACTIVE_COUNT": str(active_count),
                    "DAEMON_LOG": str(daemon_log),
                    "START_COUNT": str(start_count),
                    "SYSTEMCTL_LOG": str(systemctl_log),
                    "UNIT_FILE": str(unit),
                    "XDG_CONFIG_HOME": str(config),
                    "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
                },
            )

            restored_unit = unit.read_text(encoding="utf-8")
            starts = int(start_count.read_text(encoding="utf-8"))

        self.assertEqual(restored_unit, previous_unit)
        self.assertEqual(starts, 1)
        self.assertIn("could not be confirmed stopped", result.stderr)
        self.assertIn("previous runtime was not started", result.stderr)

    @unittest.skipUnless(sys.platform == "linux", "systemd user units are Linux-specific")
    def test_linux_autostart_install_aborts_if_stop_returns_success_but_stays_active(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "config"
            fake_bin = root / "bin"
            fake_bin.mkdir()
            daemon_log = root / "daemon.log"
            systemctl_log = root / "systemctl.log"
            daemon = root / "new-kimi-webbridge"
            daemon.write_text(
                """#!/usr/bin/env bash
printf '%s\n' "$*" >> "$DAEMON_LOG"
if [[ "$*" == "start --help" ]]; then printf '%s\n' '--foreground'; exit 0; fi
exit 99
""",
                encoding="utf-8",
            )
            daemon.chmod(0o755)
            unit = config / "systemd" / "user" / "kimi-webbridge.service"
            unit.parent.mkdir(parents=True)
            previous_unit = (
                "# Managed by kimi-webbridge-pro install_linux_autostart.sh\n"
                "[Service]\nExecStart=/previous/kimi-webbridge start --foreground\n"
            )
            unit.write_text(previous_unit, encoding="utf-8")
            fake_systemctl = fake_bin / "systemctl"
            fake_systemctl.write_text(
                """#!/usr/bin/env bash
printf '%s\n' "$*" >> "$SYSTEMCTL_LOG"
if [[ "$*" == "--user is-enabled kimi-webbridge.service" ]]; then printf '%s\n' enabled; exit 0; fi
if [[ "$*" == "--user is-active kimi-webbridge.service" ]]; then printf '%s\n' active; exit 0; fi
if [[ "$*" == "--user show kimi-webbridge.service --property=FragmentPath --value" ]]; then printf '%s\n' "$UNIT_FILE"; exit 0; fi
if [[ "$*" == "--user show kimi-webbridge.service --property=DropInPaths --value" ]]; then exit 0; fi
if [[ "$*" == "--user daemon-reload" ]]; then exit 0; fi
if [[ "$*" == "--user stop kimi-webbridge.service" ]]; then exit 0; fi
if [[ "$*" == "--user disable --now kimi-webbridge.service" ]]; then exit 0; fi
if [[ "$*" == "--user enable kimi-webbridge.service" ]]; then exit 0; fi
if [[ "$*" == "--user start kimi-webbridge.service" ]]; then exit 0; fi
exit 99
""",
                encoding="utf-8",
            )
            fake_systemctl.chmod(0o755)

            result = self.run_bash_cli(
                SCRIPTS / "install_linux_autostart.sh",
                "--binary",
                str(daemon),
                expected=1,
                env_extra={
                    "DAEMON_LOG": str(daemon_log),
                    "SYSTEMCTL_LOG": str(systemctl_log),
                    "UNIT_FILE": str(unit),
                    "XDG_CONFIG_HOME": str(config),
                    "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
                },
            )

            restored_unit = unit.read_text(encoding="utf-8")
            systemctl_calls = systemctl_log.read_text(encoding="utf-8").splitlines()

        self.assertEqual(restored_unit, previous_unit)
        self.assertNotIn("--user start kimi-webbridge.service", systemctl_calls)
        self.assertIn("could not be confirmed stopped", result.stderr)
        self.assertIn("automatic restoration was incomplete", result.stderr)

    @unittest.skipUnless(sys.platform == "linux", "systemd user units are Linux-specific")
    def test_linux_autostart_install_rechecks_service_after_enable(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "config"
            fake_bin = root / "bin"
            fake_bin.mkdir()
            daemon_log = root / "daemon.log"
            systemctl_log = root / "systemctl.log"
            quiet_count = root / "quiet.count"
            enable_state = root / "enable.state"
            daemon = root / "kimi-webbridge"
            daemon.write_text(
                """#!/usr/bin/env bash
printf '%s\n' "$*" >> "$DAEMON_LOG"
if [[ "$*" == "start --help" ]]; then printf '%s\n' '--foreground'; exit 0; fi
if [[ "$*" == "status" ]]; then printf '%s\n' '{"running":false}'; exit 0; fi
exit 99
""",
                encoding="utf-8",
            )
            daemon.chmod(0o755)
            unit = config / "systemd" / "user" / "kimi-webbridge.service"
            fake_systemctl = fake_bin / "systemctl"
            fake_systemctl.write_text(
                """#!/usr/bin/env bash
printf '%s\n' "$*" >> "$SYSTEMCTL_LOG"
if [[ "$*" == "--user is-active kimi-webbridge.service" ]]; then printf '%s\n' inactive; exit 4; fi
if [[ "$*" == "--user show kimi-webbridge.service --property=FragmentPath --value" ]]; then
  if [[ -e "$UNIT_FILE" ]]; then printf '%s\n' "$UNIT_FILE"; fi
  exit 0
fi
if [[ "$*" == "--user show kimi-webbridge.service --property=DropInPaths --value" ]]; then exit 0; fi
if [[ "$*" == "--user is-enabled kimi-webbridge.service" ]]; then
  if [[ -f "$ENABLE_STATE" ]]; then printf '%s\n' enabled; exit 0; fi
  printf '%s\n' not-found
  exit 1
fi
if [[ "$*" == "--user daemon-reload" ]]; then exit 0; fi
if [[ "$*" == "--user stop kimi-webbridge.service" ]]; then exit 0; fi
if [[ "$*" == "--user start kimi-webbridge.service" ]]; then exit 0; fi
if [[ "$*" == "--user is-active --quiet kimi-webbridge.service" ]]; then
  count=0
  if [[ -f "$QUIET_COUNT" ]]; then read -r count < "$QUIET_COUNT"; fi
  printf '%s\n' "$((count + 1))" > "$QUIET_COUNT"
  if [[ "$count" == 0 ]]; then exit 0; fi
  exit 3
fi
if [[ "$*" == "--user enable kimi-webbridge.service" ]]; then : > "$ENABLE_STATE"; exit 0; fi
if [[ "$*" == "--user disable --now kimi-webbridge.service" ]]; then exit 0; fi
exit 99
""",
                encoding="utf-8",
            )
            fake_systemctl.chmod(0o755)

            result = self.run_bash_cli(
                SCRIPTS / "install_linux_autostart.sh",
                "--binary",
                str(daemon),
                expected=1,
                env_extra={
                    "DAEMON_LOG": str(daemon_log),
                    "ENABLE_STATE": str(enable_state),
                    "QUIET_COUNT": str(quiet_count),
                    "SYSTEMCTL_LOG": str(systemctl_log),
                    "UNIT_FILE": str(unit),
                    "XDG_CONFIG_HOME": str(config),
                    "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
                },
            )

            unit_exists = unit.exists()
            quiet_checks = int(quiet_count.read_text(encoding="utf-8"))

        self.assertFalse(unit_exists)
        self.assertEqual(quiet_checks, 2)
        self.assertIn("exited while enablement was being finalized", result.stderr)
        self.assertIn("previous inactive runtime state", result.stderr)

    @unittest.skipUnless(sys.platform == "linux", "systemd user units are Linux-specific")
    def test_linux_autostart_install_preserves_previously_inactive_state(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "config"
            fake_bin = root / "bin"
            fake_bin.mkdir()
            daemon_log = root / "daemon.log"
            systemctl_log = root / "systemctl.log"
            daemon = root / "kimi-webbridge"
            daemon.write_text(
                """#!/usr/bin/env bash
printf '%s\n' "$*" >> "$DAEMON_LOG"
if [[ "$*" == "start --help" ]]; then printf '%s\n' '--foreground'; fi
if [[ "$*" == "status" ]]; then printf '%s\n' '{"running":false}'; fi
exit 0
""",
                encoding="utf-8",
            )
            daemon.chmod(0o755)
            fake_systemctl = fake_bin / "systemctl"
            fake_systemctl.write_text(
                """#!/usr/bin/env bash
printf '%s\n' "$*" >> "$SYSTEMCTL_LOG"
if [[ "$*" == "--user show kimi-webbridge.service --property=FragmentPath --value" ]]; then
  if [[ -e "$UNIT_FILE" ]]; then printf '%s\n' "$UNIT_FILE"; fi
  exit 0
fi
if [[ "$*" == "--user show kimi-webbridge.service --property=DropInPaths --value" ]]; then exit 0; fi
if [[ "$*" == "--user is-enabled kimi-webbridge.service" ]]; then printf '%s\n' not-found; exit 1; fi
if [[ "$*" == "--user is-active kimi-webbridge.service" ]]; then
  printf '%s\n' inactive
  exit 3
fi
if [[ "$*" == "--user start kimi-webbridge.service" ]]; then exit 1; fi
exit 0
""",
                encoding="utf-8",
            )
            fake_systemctl.chmod(0o755)

            result = self.run_bash_cli(
                SCRIPTS / "install_linux_autostart.sh",
                "--binary",
                str(daemon),
                expected=1,
                env_extra={
                    "DAEMON_LOG": str(daemon_log),
                    "SYSTEMCTL_LOG": str(systemctl_log),
                    "UNIT_FILE": str(config / "systemd" / "user" / "kimi-webbridge.service"),
                    "XDG_CONFIG_HOME": str(config),
                    "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
                },
            )

            unit = config / "systemd" / "user" / "kimi-webbridge.service"
            daemon_calls = daemon_log.read_text(encoding="utf-8").splitlines()
            systemctl_calls = systemctl_log.read_text(encoding="utf-8").splitlines()

        self.assertFalse(unit.exists())
        self.assertNotIn("start", daemon_calls)
        self.assertEqual(
            systemctl_calls.count("--user start kimi-webbridge.service"),
            1,
        )
        self.assertIn("previous inactive runtime state", result.stderr)
        self.assertNotIn("enabled/disabled service state", result.stderr)

    @unittest.skipUnless(sys.platform == "linux", "systemd user units are Linux-specific")
    def test_linux_autostart_install_refuses_unit_from_another_search_path(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "config"
            fake_bin = root / "bin"
            fake_bin.mkdir()
            daemon_log = root / "daemon.log"
            systemctl_log = root / "systemctl.log"
            daemon = root / "kimi-webbridge"
            daemon.write_text(
                """#!/usr/bin/env bash
printf '%s\n' "$*" >> "$DAEMON_LOG"
if [[ "$*" == "start --help" ]]; then printf '%s\n' '--foreground'; exit 0; fi
exit 99
""",
                encoding="utf-8",
            )
            daemon.chmod(0o755)
            fake_systemctl = fake_bin / "systemctl"
            fake_systemctl.write_text(
                """#!/usr/bin/env bash
printf '%s\n' "$*" >> "$SYSTEMCTL_LOG"
if [[ "$*" == "--user show kimi-webbridge.service --property=FragmentPath --value" ]]; then
  printf '%s\n' /usr/lib/systemd/user/kimi-webbridge.service
  exit 0
fi
if [[ "$*" == "--user show kimi-webbridge.service --property=DropInPaths --value" ]]; then exit 0; fi
exit 99
""",
                encoding="utf-8",
            )
            fake_systemctl.chmod(0o755)

            result = self.run_bash_cli(
                SCRIPTS / "install_linux_autostart.sh",
                "--binary",
                str(daemon),
                expected=1,
                env_extra={
                    "DAEMON_LOG": str(daemon_log),
                    "SYSTEMCTL_LOG": str(systemctl_log),
                    "XDG_CONFIG_HOME": str(config),
                    "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
                },
            )

            unit = config / "systemd" / "user" / "kimi-webbridge.service"
            daemon_calls = daemon_log.read_text(encoding="utf-8").splitlines()
            systemctl_calls = systemctl_log.read_text(encoding="utf-8").splitlines()

        self.assertFalse(unit.exists())
        self.assertEqual(daemon_calls, ["start --help"])
        self.assertFalse(any("is-active" in call for call in systemctl_calls))
        self.assertIn("Refusing to shadow", result.stderr)
        self.assertIn("no changes were made", result.stderr)

    @unittest.skipUnless(sys.platform == "linux", "systemd user units are Linux-specific")
    def test_linux_autostart_install_keeps_identical_unit_metadata_on_reload_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "config"
            fake_bin = root / "bin"
            fake_bin.mkdir()
            daemon_log = root / "daemon.log"
            systemctl_log = root / "systemctl.log"
            reload_count = root / "reload.count"
            daemon = root / "kimi-webbridge"
            daemon.write_text(
                """#!/usr/bin/env bash
printf '%s\n' "$*" >> "$DAEMON_LOG"
if [[ "$*" == "start --help" ]]; then printf '%s\n' '--foreground'; exit 0; fi
if [[ "$*" == "status" ]]; then printf '%s\n' '{"running":false}'; exit 0; fi
exit 99
""",
                encoding="utf-8",
            )
            daemon.chmod(0o755)
            unit = config / "systemd" / "user" / "kimi-webbridge.service"
            unit.parent.mkdir(parents=True)
            unit.write_text(
                "# Managed by kimi-webbridge-pro install_linux_autostart.sh\n"
                "[Unit]\n"
                "Description=Kimi WebBridge daemon\n"
                "After=graphical-session.target\n\n"
                "[Service]\n"
                "Type=simple\n"
                f'ExecStart="{daemon}" start --foreground\n'
                "Restart=on-failure\n"
                "RestartSec=3\n\n"
                "[Install]\n"
                "WantedBy=default.target\n",
                encoding="utf-8",
            )
            unit.chmod(0o644)
            original_inode = unit.stat().st_ino
            fake_systemctl = fake_bin / "systemctl"
            fake_systemctl.write_text(
                """#!/usr/bin/env bash
printf '%s\n' "$*" >> "$SYSTEMCTL_LOG"
if [[ "$*" == "--user is-enabled kimi-webbridge.service" ]]; then printf '%s\n' disabled; exit 1; fi
if [[ "$*" == "--user is-active kimi-webbridge.service" ]]; then printf '%s\n' inactive; exit 3; fi
if [[ "$*" == "--user daemon-reload" ]]; then
  count=0
  if [[ -f "$RELOAD_COUNT" ]]; then read -r count < "$RELOAD_COUNT"; fi
  printf '%s\n' "$((count + 1))" > "$RELOAD_COUNT"
  if [[ "$count" == 0 ]]; then exit 1; fi
  exit 0
fi
exit 99
""",
                encoding="utf-8",
            )
            fake_systemctl.chmod(0o755)

            result = self.run_bash_cli(
                SCRIPTS / "install_linux_autostart.sh",
                "--binary",
                str(daemon),
                expected=1,
                env_extra={
                    "DAEMON_LOG": str(daemon_log),
                    "RELOAD_COUNT": str(reload_count),
                    "SYSTEMCTL_LOG": str(systemctl_log),
                    "XDG_CONFIG_HOME": str(config),
                    "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
                },
            )

            final_inode = unit.stat().st_ino
            final_mode = unit.stat().st_mode & 0o777
            backups = list(unit.parent.glob("kimi-webbridge.service.backup.*"))

        self.assertEqual(final_inode, original_inode)
        self.assertEqual(final_mode, 0o644)
        self.assertEqual(backups, [])
        self.assertIn("Failed to reload", result.stderr)

    @unittest.skipUnless(sys.platform == "linux", "systemd user units are Linux-specific")
    def test_linux_autostart_install_detects_failed_old_service_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "config"
            fake_bin = root / "bin"
            fake_bin.mkdir()
            daemon_log = root / "daemon.log"
            systemctl_log = root / "systemctl.log"
            active_count = root / "active.count"
            enable_count = root / "enable.count"
            daemon = root / "new-kimi-webbridge"
            daemon.write_text(
                """#!/usr/bin/env bash
printf '%s\n' "$*" >> "$DAEMON_LOG"
if [[ "$*" == "start --help" ]]; then printf '%s\n' '--foreground'; exit 0; fi
exit 99
""",
                encoding="utf-8",
            )
            daemon.chmod(0o755)
            unit = config / "systemd" / "user" / "kimi-webbridge.service"
            unit.parent.mkdir(parents=True)
            unit.write_text(
                "# Managed by kimi-webbridge-pro install_linux_autostart.sh\n"
                "[Service]\nExecStart=/previous/kimi-webbridge\n",
                encoding="utf-8",
            )
            fake_systemctl = fake_bin / "systemctl"
            fake_systemctl.write_text(
                """#!/usr/bin/env bash
printf '%s\n' "$*" >> "$SYSTEMCTL_LOG"
if [[ "$*" == "--user is-enabled kimi-webbridge.service" ]]; then printf '%s\n' enabled; exit 0; fi
if [[ "$*" == "--user is-active kimi-webbridge.service" ]]; then
  count=0
  if [[ -f "$ACTIVE_COUNT" ]]; then read -r count < "$ACTIVE_COUNT"; fi
  printf '%s\n' "$((count + 1))" > "$ACTIVE_COUNT"
  if [[ "$count" == 0 ]]; then printf '%s\n' active; exit 0; fi
  printf '%s\n' inactive
  exit 3
fi
if [[ "$*" == "--user is-active --quiet kimi-webbridge.service" ]]; then exit 0; fi
if [[ "$*" == "--user show kimi-webbridge.service --property=FragmentPath --value" ]]; then printf '%s\n' "$UNIT_FILE"; exit 0; fi
if [[ "$*" == "--user show kimi-webbridge.service --property=DropInPaths --value" ]]; then exit 0; fi
if [[ "$*" == "--user daemon-reload" ]]; then exit 0; fi
if [[ "$*" == "--user stop kimi-webbridge.service" ]]; then exit 0; fi
if [[ "$*" == "--user start kimi-webbridge.service" ]]; then exit 0; fi
if [[ "$*" == "--user disable --now kimi-webbridge.service" ]]; then exit 0; fi
if [[ "$*" == "--user enable kimi-webbridge.service" ]]; then
  count=0
  if [[ -f "$ENABLE_COUNT" ]]; then read -r count < "$ENABLE_COUNT"; fi
  printf '%s\n' "$((count + 1))" > "$ENABLE_COUNT"
  if [[ "$count" == 0 ]]; then exit 1; fi
  exit 0
fi
exit 99
""",
                encoding="utf-8",
            )
            fake_systemctl.chmod(0o755)

            result = self.run_bash_cli(
                SCRIPTS / "install_linux_autostart.sh",
                "--binary",
                str(daemon),
                expected=1,
                env_extra={
                    "ACTIVE_COUNT": str(active_count),
                    "DAEMON_LOG": str(daemon_log),
                    "ENABLE_COUNT": str(enable_count),
                    "SYSTEMCTL_LOG": str(systemctl_log),
                    "UNIT_FILE": str(unit),
                    "XDG_CONFIG_HOME": str(config),
                    "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
                },
            )

            active_checks = active_count.read_text(encoding="utf-8").strip()

        self.assertEqual(active_checks, "4")
        self.assertNotIn("Restored the previously active managed service", result.stderr)
        self.assertIn("automatic daemon recovery also failed", result.stderr)
        self.assertIn("automatic restoration was incomplete", result.stderr)

    @unittest.skipUnless(sys.platform == "linux", "systemd user units are Linux-specific")
    def test_linux_autostart_install_detects_failed_enablement_restore(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "config"
            fake_bin = root / "bin"
            fake_bin.mkdir()
            daemon_log = root / "daemon.log"
            systemctl_log = root / "systemctl.log"
            active_count = root / "active.count"
            enable_state = root / "enable.state"
            daemon = root / "new-kimi-webbridge"
            daemon.write_text(
                """#!/usr/bin/env bash
printf '%s\n' "$*" >> "$DAEMON_LOG"
if [[ "$*" == "start --help" ]]; then printf '%s\n' '--foreground'; exit 0; fi
exit 99
""",
                encoding="utf-8",
            )
            daemon.chmod(0o755)
            unit = config / "systemd" / "user" / "kimi-webbridge.service"
            unit.parent.mkdir(parents=True)
            unit.write_text(
                "# Managed by kimi-webbridge-pro install_linux_autostart.sh\n"
                "[Service]\nExecStart=/previous/kimi-webbridge\n",
                encoding="utf-8",
            )
            fake_systemctl = fake_bin / "systemctl"
            fake_systemctl.write_text(
                """#!/usr/bin/env bash
printf '%s\n' "$*" >> "$SYSTEMCTL_LOG"
if [[ "$*" == "--user is-enabled kimi-webbridge.service" ]]; then
  if [[ -f "$ENABLE_STATE" ]]; then cat "$ENABLE_STATE"; exit 1; fi
  printf '%s\n' enabled
  exit 0
fi
if [[ "$*" == "--user is-active kimi-webbridge.service" ]]; then
  count=0
  if [[ -f "$ACTIVE_COUNT" ]]; then read -r count < "$ACTIVE_COUNT"; fi
  printf '%s\n' "$((count + 1))" > "$ACTIVE_COUNT"
  if [[ "$count" == 0 || "$count" == 3 ]]; then printf '%s\n' active; exit 0; fi
  printf '%s\n' inactive
  exit 3
fi
if [[ "$*" == "--user show kimi-webbridge.service --property=FragmentPath --value" ]]; then printf '%s\n' "$UNIT_FILE"; exit 0; fi
if [[ "$*" == "--user show kimi-webbridge.service --property=DropInPaths --value" ]]; then exit 0; fi
if [[ "$*" == "--user daemon-reload" ]]; then exit 0; fi
if [[ "$*" == "--user stop kimi-webbridge.service" ]]; then exit 0; fi
if [[ "$*" == "--user start kimi-webbridge.service" ]]; then
  grep -Fq '/previous/kimi-webbridge' "$UNIT_FILE"
  exit $?
fi
if [[ "$*" == "--user disable --now kimi-webbridge.service" ]]; then printf '%s\n' disabled > "$ENABLE_STATE"; exit 0; fi
if [[ "$*" == "--user enable kimi-webbridge.service" ]]; then exit 0; fi
exit 99
""",
                encoding="utf-8",
            )
            fake_systemctl.chmod(0o755)

            result = self.run_bash_cli(
                SCRIPTS / "install_linux_autostart.sh",
                "--binary",
                str(daemon),
                expected=1,
                env_extra={
                    "ACTIVE_COUNT": str(active_count),
                    "DAEMON_LOG": str(daemon_log),
                    "ENABLE_STATE": str(enable_state),
                    "SYSTEMCTL_LOG": str(systemctl_log),
                    "UNIT_FILE": str(unit),
                    "XDG_CONFIG_HOME": str(config),
                    "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
                },
            )

            restored_unit = unit.read_text(encoding="utf-8")

        self.assertIn("/previous/kimi-webbridge", restored_unit)
        self.assertIn("Restored the previously active managed service", result.stderr)
        self.assertIn("enabled/disabled service state could not be restored", result.stderr)
        self.assertIn("automatic restoration was incomplete", result.stderr)

    @unittest.skipUnless(sys.platform == "linux", "systemd user units are Linux-specific")
    def test_linux_autostart_install_refuses_cached_enabled_state_without_unit(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "config"
            fake_bin = root / "bin"
            fake_bin.mkdir()
            daemon_log = root / "daemon.log"
            systemctl_log = root / "systemctl.log"
            daemon = root / "kimi-webbridge"
            daemon.write_text(
                """#!/usr/bin/env bash
printf '%s\n' "$*" >> "$DAEMON_LOG"
if [[ "$*" == "start --help" ]]; then printf '%s\n' '--foreground'; fi
exit 0
""",
                encoding="utf-8",
            )
            daemon.chmod(0o755)
            fake_systemctl = fake_bin / "systemctl"
            fake_systemctl.write_text(
                """#!/usr/bin/env bash
printf '%s\n' "$*" >> "$SYSTEMCTL_LOG"
if [[ "$*" == "--user show kimi-webbridge.service --property=FragmentPath --value" ]]; then exit 0; fi
if [[ "$*" == "--user show kimi-webbridge.service --property=DropInPaths --value" ]]; then exit 0; fi
if [[ "$*" == "--user is-enabled kimi-webbridge.service" ]]; then printf '%s\n' enabled; exit 0; fi
exit 99
""",
                encoding="utf-8",
            )
            fake_systemctl.chmod(0o755)

            result = self.run_bash_cli(
                SCRIPTS / "install_linux_autostart.sh",
                "--binary",
                str(daemon),
                expected=1,
                env_extra={
                    "DAEMON_LOG": str(daemon_log),
                    "SYSTEMCTL_LOG": str(systemctl_log),
                    "XDG_CONFIG_HOME": str(config),
                    "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
                },
            )

            unit = config / "systemd" / "user" / "kimi-webbridge.service"
            unit_exists = unit.exists()
            daemon_calls = daemon_log.read_text(encoding="utf-8").splitlines()
            systemctl_calls = systemctl_log.read_text(encoding="utf-8").splitlines()

        self.assertFalse(unit_exists)
        self.assertEqual(daemon_calls, ["start --help"])
        self.assertNotIn("--user daemon-reload", systemctl_calls)
        self.assertNotIn("--user start kimi-webbridge.service", systemctl_calls)
        self.assertNotIn("--user stop kimi-webbridge.service", systemctl_calls)
        self.assertIn("enabled state remains", result.stderr)

    @unittest.skipUnless(sys.platform == "linux", "systemd user units are Linux-specific")
    def test_linux_autostart_install_refuses_running_direct_daemon_before_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "config"
            fake_bin = root / "bin"
            fake_bin.mkdir()
            daemon_log = root / "daemon.log"
            systemctl_log = root / "systemctl.log"
            daemon = root / "kimi-webbridge"
            daemon.write_text(
                """#!/usr/bin/env bash
printf '%s\n' "$*" >> "$DAEMON_LOG"
if [[ "$*" == "start --help" ]]; then printf '%s\n' '--foreground'; fi
if [[ "$*" == "status" ]]; then printf '%s\n' '{"running":true}'; fi
exit 0
""",
                encoding="utf-8",
            )
            daemon.chmod(0o755)
            fake_systemctl = fake_bin / "systemctl"
            fake_systemctl.write_text(
                """#!/usr/bin/env bash
printf '%s\n' "$*" >> "$SYSTEMCTL_LOG"
if [[ "$*" == "--user is-active kimi-webbridge.service" ]]; then
  printf '%s\n' inactive
  exit 3
fi
if [[ "$*" == "--user is-enabled kimi-webbridge.service" ]]; then
  printf '%s\n' not-found
  exit 1
fi
exit 0
""",
                encoding="utf-8",
            )
            fake_systemctl.chmod(0o755)

            result = self.run_bash_cli(
                SCRIPTS / "install_linux_autostart.sh",
                "--binary",
                str(daemon),
                expected=1,
                env_extra={
                    "DAEMON_LOG": str(daemon_log),
                    "SYSTEMCTL_LOG": str(systemctl_log),
                    "XDG_CONFIG_HOME": str(config),
                    "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
                },
            )

            unit = config / "systemd" / "user" / "kimi-webbridge.service"
            daemon_calls = daemon_log.read_text(encoding="utf-8").splitlines()
            systemctl_calls = systemctl_log.read_text(encoding="utf-8").splitlines()

        self.assertFalse(unit.exists())
        self.assertEqual(daemon_calls, ["start --help", "status"])
        self.assertEqual(
            systemctl_calls,
            [
                "--user show kimi-webbridge.service --property=FragmentPath --value",
                "--user show kimi-webbridge.service --property=DropInPaths --value",
                "--user is-enabled kimi-webbridge.service",
                "--user is-active kimi-webbridge.service",
            ],
        )
        self.assertIn("stop it explicitly", result.stderr)
        self.assertIn("No changes were made", result.stderr)

    @unittest.skipUnless(sys.platform == "linux", "systemd user units are Linux-specific")
    def test_linux_autostart_uninstall_refuses_unmanaged_unit(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory)
            unit = config / "systemd" / "user" / "kimi-webbridge.service"
            unit.parent.mkdir(parents=True)
            unit.write_text("[Service]\nExecStart=/custom/daemon\n", encoding="utf-8")

            result = self.run_bash_cli(
                SCRIPTS / "install_linux_autostart.sh",
                "--uninstall",
                expected=1,
                env_extra={"XDG_CONFIG_HOME": str(config)},
            )

            self.assertTrue(unit.exists())
            self.assertIn("Refusing to remove an unmanaged", result.stderr)

    @unittest.skipUnless(sys.platform == "linux", "systemd user units are Linux-specific")
    def test_linux_autostart_empty_uninstall_does_not_create_config_directories(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "missing-config"
            fake_bin = root / "bin"
            fake_bin.mkdir()
            fake_systemctl = fake_bin / "systemctl"
            fake_systemctl.write_text(
                """#!/usr/bin/env bash
if [[ "$*" == "--user show kimi-webbridge.service --property=FragmentPath --value" ]]; then exit 0; fi
if [[ "$*" == "--user show kimi-webbridge.service --property=DropInPaths --value" ]]; then exit 0; fi
if [[ "$*" == "--user is-active kimi-webbridge.service" ]]; then
  printf '%s\n' inactive
  exit 4
fi
if [[ "$*" == "--user is-enabled kimi-webbridge.service" ]]; then printf '%s\n' not-found; exit 1; fi
exit 99
""",
                encoding="utf-8",
            )
            fake_systemctl.chmod(0o755)

            result = self.run_bash_cli(
                SCRIPTS / "install_linux_autostart.sh",
                "--uninstall",
                env_extra={
                    "XDG_CONFIG_HOME": str(config),
                    "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
                },
            )

            config_exists = config.exists()

        self.assertFalse(config_exists)
        self.assertIn("No managed unit is installed", result.stdout)

    @unittest.skipUnless(sys.platform == "linux", "systemd user units are Linux-specific")
    def test_linux_autostart_empty_uninstall_refuses_cached_enabled_state(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "missing-config"
            fake_bin = root / "bin"
            fake_bin.mkdir()
            fake_systemctl = fake_bin / "systemctl"
            fake_systemctl.write_text(
                """#!/usr/bin/env bash
if [[ "$*" == "--user show kimi-webbridge.service --property=FragmentPath --value" ]]; then exit 0; fi
if [[ "$*" == "--user show kimi-webbridge.service --property=DropInPaths --value" ]]; then exit 0; fi
if [[ "$*" == "--user is-active kimi-webbridge.service" ]]; then printf '%s\n' inactive; exit 3; fi
if [[ "$*" == "--user is-enabled kimi-webbridge.service" ]]; then printf '%s\n' enabled; exit 0; fi
exit 99
""",
                encoding="utf-8",
            )
            fake_systemctl.chmod(0o755)

            result = self.run_bash_cli(
                SCRIPTS / "install_linux_autostart.sh",
                "--uninstall",
                expected=1,
                env_extra={
                    "XDG_CONFIG_HOME": str(config),
                    "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
                },
            )

            config_exists = config.exists()

        self.assertFalse(config_exists)
        self.assertNotIn("No managed unit", result.stdout)
        self.assertIn("enabled state", result.stderr)

    @unittest.skipUnless(sys.platform == "linux", "systemd user units are Linux-specific")
    def test_linux_autostart_uninstall_refuses_active_cached_unit_without_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "missing-config"
            fake_bin = root / "bin"
            fake_bin.mkdir()
            fake_systemctl = fake_bin / "systemctl"
            fake_systemctl.write_text(
                """#!/usr/bin/env bash
if [[ "$*" == "--user show kimi-webbridge.service --property=FragmentPath --value" ]]; then exit 0; fi
if [[ "$*" == "--user show kimi-webbridge.service --property=DropInPaths --value" ]]; then exit 0; fi
if [[ "$*" == "--user is-active kimi-webbridge.service" ]]; then
  printf '%s\n' active
  exit 0
fi
exit 99
""",
                encoding="utf-8",
            )
            fake_systemctl.chmod(0o755)

            result = self.run_bash_cli(
                SCRIPTS / "install_linux_autostart.sh",
                "--uninstall",
                expected=1,
                env_extra={
                    "XDG_CONFIG_HOME": str(config),
                    "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
                },
            )

            config_exists = config.exists()

        self.assertFalse(config_exists)
        self.assertIn("active runtime remains", result.stderr)
        self.assertNotIn("No managed unit", result.stdout)

    @unittest.skipUnless(sys.platform == "linux", "systemd user units are Linux-specific")
    def test_linux_autostart_uninstall_refuses_broken_symlink(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory)
            unit = config / "systemd" / "user" / "kimi-webbridge.service"
            unit.parent.mkdir(parents=True)
            unit.symlink_to(unit.parent / "missing.service")

            result = self.run_bash_cli(
                SCRIPTS / "install_linux_autostart.sh",
                "--uninstall",
                expected=1,
                env_extra={"XDG_CONFIG_HOME": str(config)},
            )

            unit_is_symlink = unit.is_symlink()

        self.assertTrue(unit_is_symlink)
        self.assertIn("Refusing to remove an unmanaged", result.stderr)

    @unittest.skipUnless(sys.platform == "linux", "systemd user units are Linux-specific")
    def test_linux_autostart_uninstall_removes_managed_unit_after_reload(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "config"
            fake_bin = root / "bin"
            fake_bin.mkdir()
            systemctl_log = root / "systemctl.log"
            unit = config / "systemd" / "user" / "kimi-webbridge.service"
            unit.parent.mkdir(parents=True)
            unit.write_text(
                "# Managed by kimi-webbridge-pro install_linux_autostart.sh\n"
                "[Service]\nExecStart=/mock\n",
                encoding="utf-8",
            )
            fake_systemctl = fake_bin / "systemctl"
            fake_systemctl.write_text(
                """#!/usr/bin/env bash
printf '%s\n' "$*" >> "$SYSTEMCTL_LOG"
if [[ "$*" == "--user show kimi-webbridge.service --property=FragmentPath --value" ]]; then
  if [[ -e "$UNIT_FILE" ]]; then printf '%s\n' "$UNIT_FILE"; fi
  exit 0
fi
if [[ "$*" == "--user show kimi-webbridge.service --property=DropInPaths --value" ]]; then exit 0; fi
if [[ "$*" == "--user is-enabled kimi-webbridge.service" ]]; then
  printf '%s\n' disabled
  exit 1
fi
if [[ "$*" == "--user is-active kimi-webbridge.service" ]]; then
  printf '%s\n' inactive
  exit 3
fi
exit 0
""",
                encoding="utf-8",
            )
            fake_systemctl.chmod(0o755)

            result = self.run_bash_cli(
                SCRIPTS / "install_linux_autostart.sh",
                "--uninstall",
                env_extra={
                    "SYSTEMCTL_LOG": str(systemctl_log),
                    "UNIT_FILE": str(unit),
                    "XDG_CONFIG_HOME": str(config),
                    "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
                },
            )

            backups = list(unit.parent.glob("kimi-webbridge.service.uninstall.*"))
            systemctl_calls = systemctl_log.read_text(encoding="utf-8").splitlines()

        self.assertFalse(unit.exists())
        self.assertEqual(backups, [])
        self.assertIn("--user disable --now kimi-webbridge.service", systemctl_calls)
        self.assertIn("--user daemon-reload", systemctl_calls)
        self.assertIn("Removed", result.stdout)

    @unittest.skipUnless(sys.platform == "linux", "systemd user units are Linux-specific")
    def test_linux_autostart_uninstall_refuses_if_disable_success_stays_active(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "config"
            fake_bin = root / "bin"
            fake_bin.mkdir()
            systemctl_log = root / "systemctl.log"
            active_count = root / "active.count"
            unit = config / "systemd" / "user" / "kimi-webbridge.service"
            unit.parent.mkdir(parents=True)
            unit.write_text(
                "# Managed by kimi-webbridge-pro install_linux_autostart.sh\n"
                "[Service]\nExecStart=/mock\n",
                encoding="utf-8",
            )
            fake_systemctl = fake_bin / "systemctl"
            fake_systemctl.write_text(
                """#!/usr/bin/env bash
printf '%s\n' "$*" >> "$SYSTEMCTL_LOG"
if [[ "$*" == "--user is-enabled kimi-webbridge.service" ]]; then printf '%s\n' enabled; exit 0; fi
if [[ "$*" == "--user is-active kimi-webbridge.service" ]]; then
  count=0
  if [[ -f "$ACTIVE_COUNT" ]]; then read -r count < "$ACTIVE_COUNT"; fi
  printf '%s\n' "$((count + 1))" > "$ACTIVE_COUNT"
  if [[ "$count" == 2 ]]; then printf '%s\n' inactive; exit 3; fi
  printf '%s\n' active
  exit 0
fi
if [[ "$*" == "--user daemon-reload" ]]; then exit 0; fi
if [[ "$*" == "--user show kimi-webbridge.service --property=FragmentPath --value" ]]; then printf '%s\n' "$UNIT_FILE"; exit 0; fi
if [[ "$*" == "--user show kimi-webbridge.service --property=DropInPaths --value" ]]; then exit 0; fi
if [[ "$*" == "--user disable --now kimi-webbridge.service" ]]; then exit 0; fi
if [[ "$*" == "--user enable kimi-webbridge.service" ]]; then exit 0; fi
if [[ "$*" == "--user start kimi-webbridge.service" ]]; then exit 0; fi
exit 99
""",
                encoding="utf-8",
            )
            fake_systemctl.chmod(0o755)

            result = self.run_bash_cli(
                SCRIPTS / "install_linux_autostart.sh",
                "--uninstall",
                expected=1,
                env_extra={
                    "ACTIVE_COUNT": str(active_count),
                    "SYSTEMCTL_LOG": str(systemctl_log),
                    "UNIT_FILE": str(unit),
                    "XDG_CONFIG_HOME": str(config),
                    "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
                },
            )

            unit_exists = unit.exists()
            backups = list(unit.parent.glob("kimi-webbridge.service.uninstall.*"))
            systemctl_calls = systemctl_log.read_text(encoding="utf-8").splitlines()

        self.assertTrue(unit_exists)
        self.assertEqual(backups, [])
        self.assertIn("--user enable kimi-webbridge.service", systemctl_calls)
        self.assertIn("--user start kimi-webbridge.service", systemctl_calls)
        self.assertNotIn("Removed", result.stdout)
        self.assertIn("could not be confirmed inactive", result.stderr)

    @unittest.skipUnless(sys.platform == "linux", "systemd user units are Linux-specific")
    def test_linux_autostart_uninstall_refuses_if_disable_success_stays_enabled(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "config"
            fake_bin = root / "bin"
            fake_bin.mkdir()
            systemctl_log = root / "systemctl.log"
            active_count = root / "active.count"
            unit = config / "systemd" / "user" / "kimi-webbridge.service"
            unit.parent.mkdir(parents=True)
            unit.write_text(
                "# Managed by kimi-webbridge-pro install_linux_autostart.sh\n"
                "[Service]\nExecStart=/mock\n",
                encoding="utf-8",
            )
            fake_systemctl = fake_bin / "systemctl"
            fake_systemctl.write_text(
                """#!/usr/bin/env bash
printf '%s\n' "$*" >> "$SYSTEMCTL_LOG"
if [[ "$*" == "--user is-enabled kimi-webbridge.service" ]]; then printf '%s\n' enabled; exit 0; fi
if [[ "$*" == "--user is-active kimi-webbridge.service" ]]; then
  count=0
  if [[ -f "$ACTIVE_COUNT" ]]; then read -r count < "$ACTIVE_COUNT"; fi
  printf '%s\n' "$((count + 1))" > "$ACTIVE_COUNT"
  if [[ "$count" == 1 ]]; then printf '%s\n' inactive; exit 3; fi
  printf '%s\n' active
  exit 0
fi
if [[ "$*" == "--user daemon-reload" ]]; then exit 0; fi
if [[ "$*" == "--user show kimi-webbridge.service --property=FragmentPath --value" ]]; then printf '%s\n' "$UNIT_FILE"; exit 0; fi
if [[ "$*" == "--user show kimi-webbridge.service --property=DropInPaths --value" ]]; then exit 0; fi
if [[ "$*" == "--user disable --now kimi-webbridge.service" ]]; then exit 0; fi
if [[ "$*" == "--user enable kimi-webbridge.service" ]]; then exit 0; fi
if [[ "$*" == "--user start kimi-webbridge.service" ]]; then exit 0; fi
exit 99
""",
                encoding="utf-8",
            )
            fake_systemctl.chmod(0o755)

            result = self.run_bash_cli(
                SCRIPTS / "install_linux_autostart.sh",
                "--uninstall",
                expected=1,
                env_extra={
                    "ACTIVE_COUNT": str(active_count),
                    "SYSTEMCTL_LOG": str(systemctl_log),
                    "UNIT_FILE": str(unit),
                    "XDG_CONFIG_HOME": str(config),
                    "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
                },
            )

            unit_exists = unit.exists()

        self.assertTrue(unit_exists)
        self.assertNotIn("Removed", result.stdout)
        self.assertIn("could not be confirmed disabled", result.stderr)

    @unittest.skipUnless(sys.platform == "linux", "systemd user units are Linux-specific")
    def test_linux_autostart_uninstall_rollback_restores_inactive_runtime(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "config"
            fake_bin = root / "bin"
            fake_bin.mkdir()
            systemctl_log = root / "systemctl.log"
            active_count = root / "active.count"
            enable_state = root / "enable.state"
            unit = config / "systemd" / "user" / "kimi-webbridge.service"
            unit.parent.mkdir(parents=True)
            unit.write_text(
                "# Managed by kimi-webbridge-pro install_linux_autostart.sh\n"
                "[Service]\nExecStart=/mock\n",
                encoding="utf-8",
            )
            fake_systemctl = fake_bin / "systemctl"
            fake_systemctl.write_text(
                """#!/usr/bin/env bash
printf '%s\n' "$*" >> "$SYSTEMCTL_LOG"
if [[ "$*" == "--user is-enabled kimi-webbridge.service" ]]; then
  if [[ -f "$ENABLE_STATE" ]]; then state="$(cat "$ENABLE_STATE")"; printf '%s\n' "$state"; [[ "$state" == disabled ]] && exit 1; exit 0; fi
  printf '%s\n' enabled
  exit 0
fi
if [[ "$*" == "--user is-active kimi-webbridge.service" ]]; then
  count=0
  if [[ -f "$ACTIVE_COUNT" ]]; then read -r count < "$ACTIVE_COUNT"; fi
  printf '%s\n' "$((count + 1))" > "$ACTIVE_COUNT"
  if [[ "$count" == 1 ]]; then printf '%s\n' active; exit 0; fi
  printf '%s\n' inactive
  exit 3
fi
if [[ "$*" == "--user daemon-reload" ]]; then exit 0; fi
if [[ "$*" == "--user show kimi-webbridge.service --property=FragmentPath --value" ]]; then printf '%s\n' "$UNIT_FILE"; exit 0; fi
if [[ "$*" == "--user show kimi-webbridge.service --property=DropInPaths --value" ]]; then exit 0; fi
if [[ "$*" == "--user disable --now kimi-webbridge.service" ]]; then printf '%s\n' disabled > "$ENABLE_STATE"; exit 0; fi
if [[ "$*" == "--user enable kimi-webbridge.service" ]]; then printf '%s\n' enabled > "$ENABLE_STATE"; exit 0; fi
if [[ "$*" == "--user stop kimi-webbridge.service" ]]; then exit 0; fi
if [[ "$*" == "--user start kimi-webbridge.service" ]]; then exit 99; fi
exit 99
""",
                encoding="utf-8",
            )
            fake_systemctl.chmod(0o755)

            result = self.run_bash_cli(
                SCRIPTS / "install_linux_autostart.sh",
                "--uninstall",
                expected=1,
                env_extra={
                    "ACTIVE_COUNT": str(active_count),
                    "ENABLE_STATE": str(enable_state),
                    "SYSTEMCTL_LOG": str(systemctl_log),
                    "UNIT_FILE": str(unit),
                    "XDG_CONFIG_HOME": str(config),
                    "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
                },
            )

            active_checks = active_count.read_text(encoding="utf-8").strip()
            systemctl_calls = systemctl_log.read_text(encoding="utf-8").splitlines()

        self.assertEqual(active_checks, "4")
        self.assertNotIn("--user start kimi-webbridge.service", systemctl_calls)
        self.assertNotIn("automatic restoration was incomplete", result.stderr)

    @unittest.skipUnless(sys.platform == "linux", "systemd user units are Linux-specific")
    def test_linux_autostart_uninstall_rolls_back_external_unit_takeover(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "config"
            fake_bin = root / "bin"
            fake_bin.mkdir()
            systemctl_log = root / "systemctl.log"
            unit = config / "systemd" / "user" / "kimi-webbridge.service"
            unit.parent.mkdir(parents=True)
            previous_unit = (
                "# Managed by kimi-webbridge-pro install_linux_autostart.sh\n"
                "[Service]\nExecStart=/mock\n"
            )
            unit.write_text(previous_unit, encoding="utf-8")
            fake_systemctl = fake_bin / "systemctl"
            fake_systemctl.write_text(
                """#!/usr/bin/env bash
printf '%s\n' "$*" >> "$SYSTEMCTL_LOG"
if [[ "$*" == "--user is-enabled kimi-webbridge.service" ]]; then printf '%s\n' disabled; exit 1; fi
if [[ "$*" == "--user is-active kimi-webbridge.service" ]]; then printf '%s\n' inactive; exit 3; fi
if [[ "$*" == "--user daemon-reload" ]]; then exit 0; fi
if [[ "$*" == "--user show kimi-webbridge.service --property=FragmentPath --value" ]]; then
  if [[ -e "$UNIT_FILE" ]]; then printf '%s\n' "$UNIT_FILE"; else printf '%s\n' /usr/lib/systemd/user/kimi-webbridge.service; fi
  exit 0
fi
if [[ "$*" == "--user show kimi-webbridge.service --property=DropInPaths --value" ]]; then exit 0; fi
if [[ "$*" == "--user disable --now kimi-webbridge.service" ]]; then exit 0; fi
if [[ "$*" == "--user disable kimi-webbridge.service" ]]; then exit 0; fi
if [[ "$*" == "--user stop kimi-webbridge.service" ]]; then exit 0; fi
exit 99
""",
                encoding="utf-8",
            )
            fake_systemctl.chmod(0o755)

            result = self.run_bash_cli(
                SCRIPTS / "install_linux_autostart.sh",
                "--uninstall",
                expected=1,
                env_extra={
                    "SYSTEMCTL_LOG": str(systemctl_log),
                    "UNIT_FILE": str(unit),
                    "XDG_CONFIG_HOME": str(config),
                    "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
                },
            )

            restored_unit = unit.read_text(encoding="utf-8")
            systemctl_calls = systemctl_log.read_text(encoding="utf-8").splitlines()

        self.assertEqual(restored_unit, previous_unit)
        self.assertNotIn("--user stop kimi-webbridge.service", systemctl_calls)
        self.assertNotIn("Removed", result.stdout)
        self.assertIn("same-named unit", result.stderr)

    @unittest.skipUnless(sys.platform == "linux", "systemd user units are Linux-specific")
    def test_linux_autostart_uninstall_rejects_wrong_effective_unit_after_rollback(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "config"
            fake_bin = root / "bin"
            fake_bin.mkdir()
            systemctl_log = root / "systemctl.log"
            active_count = root / "active.count"
            enable_state = root / "enable.state"
            show_count = root / "show.count"
            unit = config / "systemd" / "user" / "kimi-webbridge.service"
            unit.parent.mkdir(parents=True)
            previous_unit = (
                "# Managed by kimi-webbridge-pro install_linux_autostart.sh\n"
                "[Service]\nExecStart=/mock\n"
            )
            unit.write_text(previous_unit, encoding="utf-8")
            fake_systemctl = fake_bin / "systemctl"
            fake_systemctl.write_text(
                """#!/usr/bin/env bash
printf '%s\n' "$*" >> "$SYSTEMCTL_LOG"
if [[ "$*" == "--user is-enabled kimi-webbridge.service" ]]; then
  if [[ -f "$ENABLE_STATE" ]]; then printf '%s\n' disabled; exit 1; fi
  printf '%s\n' enabled
  exit 0
fi
if [[ "$*" == "--user is-active kimi-webbridge.service" ]]; then
  count=0
  if [[ -f "$ACTIVE_COUNT" ]]; then read -r count < "$ACTIVE_COUNT"; fi
  printf '%s\n' "$((count + 1))" > "$ACTIVE_COUNT"
  if [[ "$count" == 0 ]]; then printf '%s\n' active; exit 0; fi
  printf '%s\n' inactive
  exit 3
fi
if [[ "$*" == "--user show kimi-webbridge.service --property=FragmentPath --value" ]]; then
  count=0
  if [[ -f "$SHOW_COUNT" ]]; then read -r count < "$SHOW_COUNT"; fi
  printf '%s\n' "$((count + 1))" > "$SHOW_COUNT"
  if [[ "$count" == 0 ]]; then printf '%s\n' "$UNIT_FILE"; else printf '%s\n' /usr/lib/systemd/user/kimi-webbridge.service; fi
  exit 0
fi
if [[ "$*" == "--user show kimi-webbridge.service --property=DropInPaths --value" ]]; then exit 0; fi
if [[ "$*" == "--user daemon-reload" ]]; then exit 0; fi
if [[ "$*" == "--user disable --now kimi-webbridge.service" ]]; then printf '%s\n' disabled > "$ENABLE_STATE"; exit 0; fi
if [[ "$*" == "--user stop kimi-webbridge.service" ]]; then exit 0; fi
if [[ "$*" == "--user enable kimi-webbridge.service" ]]; then exit 0; fi
if [[ "$*" == "--user start kimi-webbridge.service" ]]; then exit 0; fi
exit 99
""",
                encoding="utf-8",
            )
            fake_systemctl.chmod(0o755)

            result = self.run_bash_cli(
                SCRIPTS / "install_linux_autostart.sh",
                "--uninstall",
                expected=1,
                env_extra={
                    "ACTIVE_COUNT": str(active_count),
                    "ENABLE_STATE": str(enable_state),
                    "SHOW_COUNT": str(show_count),
                    "SYSTEMCTL_LOG": str(systemctl_log),
                    "UNIT_FILE": str(unit),
                    "XDG_CONFIG_HOME": str(config),
                    "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
                },
            )

            restored_unit = unit.read_text(encoding="utf-8")
            systemctl_calls = systemctl_log.read_text(encoding="utf-8").splitlines()

        self.assertEqual(restored_unit, previous_unit)
        self.assertNotIn("--user start kimi-webbridge.service", systemctl_calls)
        self.assertNotIn("Removed", result.stdout)
        self.assertIn("automatic restoration was incomplete", result.stderr)

    @unittest.skipUnless(sys.platform == "linux", "systemd user units are Linux-specific")
    def test_linux_autostart_uninstall_rejects_wrong_effective_unit_before_stop(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "config"
            fake_bin = root / "bin"
            fake_bin.mkdir()
            systemctl_log = root / "systemctl.log"
            unit = config / "systemd" / "user" / "kimi-webbridge.service"
            unit.parent.mkdir(parents=True)
            unit.write_text(
                "# Managed by kimi-webbridge-pro install_linux_autostart.sh\n"
                "[Service]\nExecStart=/mock\n",
                encoding="utf-8",
            )
            fake_systemctl = fake_bin / "systemctl"
            fake_systemctl.write_text(
                """#!/usr/bin/env bash
printf '%s\n' "$*" >> "$SYSTEMCTL_LOG"
if [[ "$*" == "--user is-enabled kimi-webbridge.service" ]]; then
  printf '%s\n' disabled
  exit 1
fi
if [[ "$*" == "--user is-active kimi-webbridge.service" ]]; then
  printf '%s\n' inactive
  exit 3
fi
if [[ "$*" == "--user show kimi-webbridge.service --property=FragmentPath --value" ]]; then
  printf '%s\n' /different/kimi-webbridge.service
  exit 0
fi
if [[ "$*" == "--user show kimi-webbridge.service --property=DropInPaths --value" ]]; then exit 0; fi
exit 0
""",
                encoding="utf-8",
            )
            fake_systemctl.chmod(0o755)

            result = self.run_bash_cli(
                SCRIPTS / "install_linux_autostart.sh",
                "--uninstall",
                expected=1,
                env_extra={
                    "SYSTEMCTL_LOG": str(systemctl_log),
                    "XDG_CONFIG_HOME": str(config),
                    "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
                },
            )

            unit_exists = unit.exists()
            systemctl_calls = systemctl_log.read_text(encoding="utf-8").splitlines()

        self.assertTrue(unit_exists)
        self.assertFalse(any("disable" in call for call in systemctl_calls))
        self.assertIn("did not load the exact managed unit", result.stderr)

    @unittest.skipUnless(sys.platform == "linux", "systemd user units are Linux-specific")
    def test_linux_autostart_uninstall_keeps_unit_if_disable_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "config"
            fake_bin = root / "bin"
            fake_bin.mkdir()
            systemctl_log = root / "systemctl.log"
            active_count = root / "active.count"
            unit = config / "systemd" / "user" / "kimi-webbridge.service"
            unit.parent.mkdir(parents=True)
            unit.write_text(
                "# Managed by kimi-webbridge-pro install_linux_autostart.sh\n"
                "[Service]\nExecStart=/mock\n",
                encoding="utf-8",
            )
            fake_systemctl = fake_bin / "systemctl"
            fake_systemctl.write_text(
                """#!/usr/bin/env bash
printf '%s\n' "$*" >> "$SYSTEMCTL_LOG"
if [[ "$*" == "--user show kimi-webbridge.service --property=FragmentPath --value" ]]; then
  printf '%s\n' "$UNIT_FILE"
  exit 0
fi
if [[ "$*" == "--user show kimi-webbridge.service --property=DropInPaths --value" ]]; then exit 0; fi
if [[ "$*" == "--user is-enabled kimi-webbridge.service" ]]; then
  printf '%s\n' enabled
  exit 0
fi
if [[ "$*" == "--user is-active kimi-webbridge.service" ]]; then
  count=0
  if [[ -f "$ACTIVE_COUNT" ]]; then read -r count < "$ACTIVE_COUNT"; fi
  printf '%s\n' "$((count + 1))" > "$ACTIVE_COUNT"
  if [[ "$count" == 1 ]]; then printf '%s\n' inactive; exit 3; fi
  printf '%s\n' active
  exit 0
fi
if [[ "$*" == *"disable --now"* ]]; then exit 1; fi
exit 0
""",
                encoding="utf-8",
            )
            fake_systemctl.chmod(0o755)

            result = self.run_bash_cli(
                SCRIPTS / "install_linux_autostart.sh",
                "--uninstall",
                expected=1,
                env_extra={
                    "ACTIVE_COUNT": str(active_count),
                    "SYSTEMCTL_LOG": str(systemctl_log),
                    "UNIT_FILE": str(unit),
                    "XDG_CONFIG_HOME": str(config),
                    "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
                },
            )

            self.assertTrue(unit.exists())
            self.assertEqual(
                list(unit.parent.glob("kimi-webbridge.service.uninstall.*")),
                [],
            )
            systemctl_calls = systemctl_log.read_text(encoding="utf-8").splitlines()
            self.assertIn("--user enable kimi-webbridge.service", systemctl_calls)
            self.assertIn("--user start kimi-webbridge.service", systemctl_calls)
            self.assertIn("could not disable and stop", result.stderr)

    @unittest.skipUnless(sys.platform == "linux", "systemd user units are Linux-specific")
    def test_linux_autostart_uninstall_restores_state_if_backup_cleanup_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "config"
            fake_bin = root / "bin"
            fake_bin.mkdir()
            systemctl_log = root / "systemctl.log"
            active_count = root / "active.count"
            unit = config / "systemd" / "user" / "kimi-webbridge.service"
            unit.parent.mkdir(parents=True)
            unit.write_text(
                "# Managed by kimi-webbridge-pro install_linux_autostart.sh\n"
                "[Service]\nExecStart=/mock\n",
                encoding="utf-8",
            )
            fake_rm = fake_bin / "rm"
            fake_rm.write_text("#!/usr/bin/env bash\nexit 1\n", encoding="utf-8")
            fake_rm.chmod(0o755)
            fake_systemctl = fake_bin / "systemctl"
            fake_systemctl.write_text(
                """#!/usr/bin/env bash
printf '%s\n' "$*" >> "$SYSTEMCTL_LOG"
if [[ "$*" == "--user is-enabled kimi-webbridge.service" ]]; then printf '%s\n' enabled; exit 0; fi
if [[ "$*" == "--user is-active kimi-webbridge.service" ]]; then
  count=0
  if [[ -f "$ACTIVE_COUNT" ]]; then read -r count < "$ACTIVE_COUNT"; fi
  printf '%s\n' "$((count + 1))" > "$ACTIVE_COUNT"
  if [[ "$count" == 1 ]]; then printf '%s\n' inactive; exit 3; fi
  printf '%s\n' active
  exit 0
fi
if [[ "$*" == "--user daemon-reload" ]]; then exit 0; fi
if [[ "$*" == "--user show kimi-webbridge.service --property=FragmentPath --value" ]]; then printf '%s\n' "$UNIT_FILE"; exit 0; fi
if [[ "$*" == "--user show kimi-webbridge.service --property=DropInPaths --value" ]]; then exit 0; fi
if [[ "$*" == "--user disable --now kimi-webbridge.service" ]]; then exit 1; fi
if [[ "$*" == "--user enable kimi-webbridge.service" ]]; then exit 0; fi
if [[ "$*" == "--user start kimi-webbridge.service" ]]; then exit 0; fi
exit 99
""",
                encoding="utf-8",
            )
            fake_systemctl.chmod(0o755)

            result = self.run_bash_cli(
                SCRIPTS / "install_linux_autostart.sh",
                "--uninstall",
                expected=1,
                env_extra={
                    "ACTIVE_COUNT": str(active_count),
                    "SYSTEMCTL_LOG": str(systemctl_log),
                    "UNIT_FILE": str(unit),
                    "XDG_CONFIG_HOME": str(config),
                    "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
                },
            )

            unit_exists = unit.exists()
            backups = list(unit.parent.glob("kimi-webbridge.service.uninstall.*"))
            systemctl_calls = systemctl_log.read_text(encoding="utf-8").splitlines()

        self.assertTrue(unit_exists)
        self.assertEqual(len(backups), 1)
        self.assertIn("--user enable kimi-webbridge.service", systemctl_calls)
        self.assertIn("--user start kimi-webbridge.service", systemctl_calls)
        self.assertIn("automatic restoration was incomplete", result.stderr)

    @unittest.skipUnless(sys.platform == "linux", "systemd user units are Linux-specific")
    def test_linux_autostart_uninstall_detects_failed_service_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "config"
            fake_bin = root / "bin"
            fake_bin.mkdir()
            systemctl_log = root / "systemctl.log"
            active_count = root / "active.count"
            unit = config / "systemd" / "user" / "kimi-webbridge.service"
            unit.parent.mkdir(parents=True)
            unit.write_text(
                "# Managed by kimi-webbridge-pro install_linux_autostart.sh\n"
                "[Service]\nExecStart=/mock\n",
                encoding="utf-8",
            )
            fake_systemctl = fake_bin / "systemctl"
            fake_systemctl.write_text(
                """#!/usr/bin/env bash
printf '%s\n' "$*" >> "$SYSTEMCTL_LOG"
if [[ "$*" == "--user is-enabled kimi-webbridge.service" ]]; then printf '%s\n' enabled; exit 0; fi
if [[ "$*" == "--user is-active kimi-webbridge.service" ]]; then
  count=0
  if [[ -f "$ACTIVE_COUNT" ]]; then read -r count < "$ACTIVE_COUNT"; fi
  printf '%s\n' "$((count + 1))" > "$ACTIVE_COUNT"
  if [[ "$count" == 0 ]]; then printf '%s\n' active; exit 0; fi
  printf '%s\n' inactive
  exit 3
fi
if [[ "$*" == "--user daemon-reload" ]]; then exit 0; fi
if [[ "$*" == "--user show kimi-webbridge.service --property=FragmentPath --value" ]]; then printf '%s\n' "$UNIT_FILE"; exit 0; fi
if [[ "$*" == "--user show kimi-webbridge.service --property=DropInPaths --value" ]]; then exit 0; fi
if [[ "$*" == "--user disable --now kimi-webbridge.service" ]]; then exit 1; fi
if [[ "$*" == "--user enable kimi-webbridge.service" ]]; then exit 0; fi
if [[ "$*" == "--user start kimi-webbridge.service" ]]; then exit 0; fi
exit 99
""",
                encoding="utf-8",
            )
            fake_systemctl.chmod(0o755)

            result = self.run_bash_cli(
                SCRIPTS / "install_linux_autostart.sh",
                "--uninstall",
                expected=1,
                env_extra={
                    "ACTIVE_COUNT": str(active_count),
                    "SYSTEMCTL_LOG": str(systemctl_log),
                    "UNIT_FILE": str(unit),
                    "XDG_CONFIG_HOME": str(config),
                    "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
                },
            )

            active_checks = active_count.read_text(encoding="utf-8").strip()

        self.assertEqual(active_checks, "3")
        self.assertIn("automatic restoration was incomplete", result.stderr)

    @unittest.skipUnless(sys.platform == "linux", "systemd user units are Linux-specific")
    def test_linux_autostart_uninstall_restores_unit_if_reload_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "config"
            fake_bin = root / "bin"
            fake_bin.mkdir()
            systemctl_log = root / "systemctl.log"
            reload_count = root / "reload.count"
            active_count = root / "active.count"
            enable_state = root / "enable.state"
            unit = config / "systemd" / "user" / "kimi-webbridge.service"
            unit.parent.mkdir(parents=True)
            previous_unit = (
                "# Managed by kimi-webbridge-pro install_linux_autostart.sh\n"
                "[Service]\nExecStart=/mock\n"
            )
            unit.write_text(previous_unit, encoding="utf-8")
            fake_systemctl = fake_bin / "systemctl"
            fake_systemctl.write_text(
                """#!/usr/bin/env bash
printf '%s\n' "$*" >> "$SYSTEMCTL_LOG"
if [[ "$*" == "--user show kimi-webbridge.service --property=FragmentPath --value" ]]; then
  printf '%s\n' "$UNIT_FILE"
  exit 0
fi
if [[ "$*" == "--user show kimi-webbridge.service --property=DropInPaths --value" ]]; then exit 0; fi
if [[ "$*" == "--user is-enabled kimi-webbridge.service" ]]; then
  if [[ -f "$ENABLE_STATE" ]]; then state="$(cat "$ENABLE_STATE")"; printf '%s\n' "$state"; [[ "$state" == disabled ]] && exit 1; exit 0; fi
  printf '%s\n' enabled-runtime
  exit 0
fi
if [[ "$*" == "--user is-active kimi-webbridge.service" ]]; then
  count=0
  if [[ -f "$ACTIVE_COUNT" ]]; then read -r count < "$ACTIVE_COUNT"; fi
  printf '%s\n' "$((count + 1))" > "$ACTIVE_COUNT"
  if [[ "$count" == 1 || "$count" == 2 ]]; then printf '%s\n' inactive; exit 3; fi
  printf '%s\n' active
  exit 0
fi
if [[ "$*" == "--user daemon-reload" ]]; then
  count=0
  if [[ -f "$RELOAD_COUNT" ]]; then read -r count < "$RELOAD_COUNT"; fi
  printf '%s\n' "$((count + 1))" > "$RELOAD_COUNT"
  if [[ "$count" == 1 ]]; then exit 1; fi
fi
if [[ "$*" == "--user disable --runtime --now kimi-webbridge.service" ]]; then printf '%s\n' disabled > "$ENABLE_STATE"; exit 0; fi
if [[ "$*" == "--user enable --runtime kimi-webbridge.service" ]]; then printf '%s\n' enabled-runtime > "$ENABLE_STATE"; exit 0; fi
exit 0
""",
                encoding="utf-8",
            )
            fake_systemctl.chmod(0o755)

            result = self.run_bash_cli(
                SCRIPTS / "install_linux_autostart.sh",
                "--uninstall",
                expected=1,
                env_extra={
                    "ACTIVE_COUNT": str(active_count),
                    "ENABLE_STATE": str(enable_state),
                    "RELOAD_COUNT": str(reload_count),
                    "SYSTEMCTL_LOG": str(systemctl_log),
                    "UNIT_FILE": str(unit),
                    "XDG_CONFIG_HOME": str(config),
                    "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
                },
            )

            restored_unit = unit.read_text(encoding="utf-8")
            backups = list(unit.parent.glob("kimi-webbridge.service.uninstall.*"))
            systemctl_calls = systemctl_log.read_text(encoding="utf-8").splitlines()

        self.assertEqual(restored_unit, previous_unit)
        self.assertEqual(backups, [])
        self.assertEqual(systemctl_calls.count("--user daemon-reload"), 3)
        self.assertIn("--user disable --runtime --now kimi-webbridge.service", systemctl_calls)
        self.assertIn("--user enable --runtime kimi-webbridge.service", systemctl_calls)
        self.assertNotIn("--user enable kimi-webbridge.service", systemctl_calls)
        self.assertIn("--user start kimi-webbridge.service", systemctl_calls)
        self.assertIn("managed unit was restored", result.stderr)

    @unittest.skipUnless(sys.platform == "linux", "systemd user units are Linux-specific")
    def test_linux_autostart_uninstall_does_not_start_if_rollback_reload_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "config"
            fake_bin = root / "bin"
            fake_bin.mkdir()
            systemctl_log = root / "systemctl.log"
            reload_count = root / "reload.count"
            active_count = root / "active.count"
            enable_state = root / "enable.state"
            unit = config / "systemd" / "user" / "kimi-webbridge.service"
            unit.parent.mkdir(parents=True)
            previous_unit = (
                "# Managed by kimi-webbridge-pro install_linux_autostart.sh\n"
                "[Service]\nExecStart=/mock\n"
            )
            unit.write_text(previous_unit, encoding="utf-8")
            fake_systemctl = fake_bin / "systemctl"
            fake_systemctl.write_text(
                """#!/usr/bin/env bash
printf '%s\n' "$*" >> "$SYSTEMCTL_LOG"
if [[ "$*" == "--user show kimi-webbridge.service --property=FragmentPath --value" ]]; then
  printf '%s\n' "$UNIT_FILE"
  exit 0
fi
if [[ "$*" == "--user show kimi-webbridge.service --property=DropInPaths --value" ]]; then exit 0; fi
if [[ "$*" == "--user is-enabled kimi-webbridge.service" ]]; then
  if [[ -f "$ENABLE_STATE" ]]; then state="$(cat "$ENABLE_STATE")"; printf '%s\n' "$state"; [[ "$state" == disabled ]] && exit 1; exit 0; fi
  printf '%s\n' enabled
  exit 0
fi
if [[ "$*" == "--user is-active kimi-webbridge.service" ]]; then
  count=0
  if [[ -f "$ACTIVE_COUNT" ]]; then read -r count < "$ACTIVE_COUNT"; fi
  printf '%s\n' "$((count + 1))" > "$ACTIVE_COUNT"
  if [[ "$count" == 0 ]]; then printf '%s\n' active; exit 0; fi
  printf '%s\n' inactive
  exit 3
fi
if [[ "$*" == "--user daemon-reload" ]]; then
  count=0
  if [[ -f "$RELOAD_COUNT" ]]; then read -r count < "$RELOAD_COUNT"; fi
  printf '%s\n' "$((count + 1))" > "$RELOAD_COUNT"
  if [[ "$count" != 0 ]]; then exit 1; fi
fi
if [[ "$*" == "--user disable --now kimi-webbridge.service" ]]; then printf '%s\n' disabled > "$ENABLE_STATE"; exit 0; fi
if [[ "$*" == "--user enable kimi-webbridge.service" ]]; then printf '%s\n' enabled > "$ENABLE_STATE"; exit 0; fi
exit 0
""",
                encoding="utf-8",
            )
            fake_systemctl.chmod(0o755)

            result = self.run_bash_cli(
                SCRIPTS / "install_linux_autostart.sh",
                "--uninstall",
                expected=1,
                env_extra={
                    "ACTIVE_COUNT": str(active_count),
                    "ENABLE_STATE": str(enable_state),
                    "RELOAD_COUNT": str(reload_count),
                    "SYSTEMCTL_LOG": str(systemctl_log),
                    "UNIT_FILE": str(unit),
                    "XDG_CONFIG_HOME": str(config),
                    "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
                },
            )

            restored_unit = unit.read_text(encoding="utf-8")
            systemctl_calls = systemctl_log.read_text(encoding="utf-8").splitlines()

        self.assertEqual(restored_unit, previous_unit)
        self.assertEqual(systemctl_calls.count("--user daemon-reload"), 3)
        self.assertNotIn("--user enable kimi-webbridge.service", systemctl_calls)
        self.assertNotIn("--user start kimi-webbridge.service", systemctl_calls)
        self.assertIn("automatic restoration was incomplete", result.stderr)

    @unittest.skipUnless(sys.platform == "linux", "systemd user units are Linux-specific")
    def test_linux_autostart_uninstall_signal_restores_unit_and_runtime_state(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "config"
            fake_bin = root / "bin"
            fake_bin.mkdir()
            systemctl_log = root / "systemctl.log"
            reload_count = root / "reload.count"
            active_count = root / "active.count"
            enable_state = root / "enable.state"
            unit = config / "systemd" / "user" / "kimi-webbridge.service"
            unit.parent.mkdir(parents=True)
            previous_unit = (
                "# Managed by kimi-webbridge-pro install_linux_autostart.sh\n"
                "[Service]\nExecStart=/mock\n"
            )
            unit.write_text(previous_unit, encoding="utf-8")
            fake_systemctl = fake_bin / "systemctl"
            fake_systemctl.write_text(
                """#!/usr/bin/env bash
printf '%s\n' "$*" >> "$SYSTEMCTL_LOG"
if [[ "$*" == "--user is-enabled kimi-webbridge.service" ]]; then
  if [[ -f "$ENABLE_STATE" ]]; then state="$(cat "$ENABLE_STATE")"; printf '%s\n' "$state"; [[ "$state" == disabled ]] && exit 1; exit 0; fi
  printf '%s\n' enabled-runtime
  exit 0
fi
if [[ "$*" == "--user is-active kimi-webbridge.service" ]]; then
  count=0
  if [[ -f "$ACTIVE_COUNT" ]]; then read -r count < "$ACTIVE_COUNT"; fi
  printf '%s\n' "$((count + 1))" > "$ACTIVE_COUNT"
  if [[ "$count" == 1 || "$count" == 2 ]]; then printf '%s\n' inactive; exit 3; fi
  printf '%s\n' active
  exit 0
fi
if [[ "$*" == "--user show kimi-webbridge.service --property=FragmentPath --value" ]]; then printf '%s\n' "$UNIT_FILE"; exit 0; fi
if [[ "$*" == "--user show kimi-webbridge.service --property=DropInPaths --value" ]]; then exit 0; fi
if [[ "$*" == "--user daemon-reload" ]]; then
  count=0
  if [[ -f "$RELOAD_COUNT" ]]; then read -r count < "$RELOAD_COUNT"; fi
  printf '%s\n' "$((count + 1))" > "$RELOAD_COUNT"
  if [[ "$count" == 1 ]]; then kill -TERM "$PPID"; fi
  exit 0
fi
if [[ "$*" == "--user disable --runtime --now kimi-webbridge.service" ]]; then printf '%s\n' disabled > "$ENABLE_STATE"; exit 0; fi
if [[ "$*" == "--user enable --runtime kimi-webbridge.service" ]]; then printf '%s\n' enabled-runtime > "$ENABLE_STATE"; exit 0; fi
if [[ "$*" == "--user start kimi-webbridge.service" ]]; then exit 0; fi
exit 99
""",
                encoding="utf-8",
            )
            fake_systemctl.chmod(0o755)

            result = self.run_bash_cli(
                SCRIPTS / "install_linux_autostart.sh",
                "--uninstall",
                expected=1,
                env_extra={
                    "ACTIVE_COUNT": str(active_count),
                    "ENABLE_STATE": str(enable_state),
                    "RELOAD_COUNT": str(reload_count),
                    "SYSTEMCTL_LOG": str(systemctl_log),
                    "UNIT_FILE": str(unit),
                    "XDG_CONFIG_HOME": str(config),
                    "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
                },
            )

            restored_unit = unit.read_text(encoding="utf-8")
            backups = list(unit.parent.glob("kimi-webbridge.service.uninstall.*"))
            systemctl_calls = systemctl_log.read_text(encoding="utf-8").splitlines()

        self.assertEqual(restored_unit, previous_unit)
        self.assertEqual(backups, [])
        self.assertIn("--user disable --runtime --now kimi-webbridge.service", systemctl_calls)
        self.assertIn("--user enable --runtime kimi-webbridge.service", systemctl_calls)
        self.assertIn("--user start kimi-webbridge.service", systemctl_calls)
        self.assertIn("uninstall was interrupted", result.stderr)

    def test_invoke_sh_reads_utf8_json_from_stdin(self):
        args_json = json.dumps(
            {
                "selector": "@e1",
                "value": "🌔🥚🏋️‍♂️",
                "nested": {"enabled": True},
            },
            ensure_ascii=False,
        )
        result = self.run_bash_cli(
            SCRIPTS / "invoke.sh",
            "--daemon-url",
            self.daemon_url,
            "--action",
            "fill",
            "--session",
            "mock",
            "--args-stdin",
            input_text=args_json,
        )

        response = json.loads(result.stdout)
        echo = response["data"]["echo"]
        self.assertEqual(echo["args"]["value"], "🌔🥚🏋️‍♂️")
        self.assertEqual(echo["args"]["nested"], {"enabled": True})

    def test_invoke_sh_preserves_utf8_under_ascii_python_locale(self):
        result = self.run_bash_cli(
            SCRIPTS / "invoke.sh",
            "--action",
            "fill",
            "--args-json",
            '{"selector":"@e1","value":"显卡日报 🌔"}',
            "--dry-run",
            env_extra={
                "LC_ALL": "C",
                "PYTHONCOERCECLOCALE": "0",
                "PYTHONIOENCODING": "ascii",
                "PYTHONUTF8": "0",
            },
        )

        self.assertEqual(json.loads(result.stdout)["args"]["value"], "显卡日报 🌔")

    def test_invoke_sh_accepts_dash_as_stdin_args_file(self):
        result = self.run_bash_cli(
            SCRIPTS / "invoke.sh",
            "--action",
            "fill",
            "--args-file",
            "-",
            "--dry-run",
            input_text='{"selector":"@e1","value":"🌔"}',
        )

        payload = json.loads(result.stdout)
        self.assertEqual(payload["args"]["value"], "🌔")

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

    def test_invoke_ps1_rejects_scalar_and_array_action_args(self):
        for action_args in ("42", "@(1,2)"):
            with self.subTest(action_args=action_args):
                command = (
                    f"& '{SCRIPTS / 'invoke.ps1'}' "
                    f"-Action snapshot -ActionArgs {action_args} -DryRun"
                )
                result = self.run_pwsh_cli("-Command", command, expected=1)
                self.assertIn("JSON-like object", result.stderr)

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

    def test_snapshot_file_mode_keeps_path_only_stdout_and_quiet_stderr(self):
        output = Path(self.tempdir.name) / "snapshot.json"
        result = self.run_python_cli(
            SCRIPTS / "snapshot.py",
            "--daemon-url",
            self.daemon_url,
            "--session",
            "mock",
            "--mode",
            "file",
            "--output",
            str(output),
        )

        self.assertEqual(result.stdout.strip(), str(output.resolve()))
        self.assertEqual(result.stderr, "")
        self.assertTrue(output.read_bytes().endswith(b"\n"))

    def test_snapshot_file_metadata_is_opt_in(self):
        output = Path(self.tempdir.name) / "snapshot-metadata.json"
        result = self.run_python_cli(
            SCRIPTS / "snapshot.py",
            "--daemon-url",
            self.daemon_url,
            "--session",
            "mock",
            "--mode",
            "file",
            "--output",
            str(output),
            "--metadata",
        )

        metadata = json.loads(result.stderr)
        self.assertEqual(metadata["path"], str(output.resolve()))
        self.assertEqual(metadata["file_bytes"], output.stat().st_size)

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

        self.assertTrue(os.path.samefile(Path(result.stdout.strip()), self.screenshot_path))

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

        self.assertTrue(os.path.samefile(Path(result.stdout.strip()), output_path))
        self.assertEqual(output_path.read_bytes(), b"fake-image-bytes")

    def test_screenshot_ps1_default_base64_outputs_use_unique_temp_directories(self):
        outputs = []
        try:
            for _ in range(2):
                result = self.run_pwsh_cli(
                    "-File",
                    str(SCRIPTS / "screenshot.ps1"),
                    "-DaemonUrl",
                    self.daemon_url,
                    "-Session",
                    "base64-shot",
                )
                output = Path(result.stdout.strip())
                outputs.append(output)
                self.assertEqual(output.read_bytes(), b"fake-image-bytes")
                self.assertTrue(output.parent.name.startswith("kimi-webbridge-screenshots-"))

            self.assertNotEqual(outputs[0].parent, outputs[1].parent)
        finally:
            for output in outputs:
                shutil.rmtree(output.parent, ignore_errors=True)

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
