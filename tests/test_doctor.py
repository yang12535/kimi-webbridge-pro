import sys
import io
import time
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch


SCRIPTS_DIR = Path(__file__).parents[1] / "skill" / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import doctor  # noqa: E402
import webbridge_client  # noqa: E402


class DoctorTests(unittest.TestCase):
    def test_utf8_output_disables_windows_newline_expansion(self):
        stdout = MagicMock()
        stderr = MagicMock()
        with patch.object(webbridge_client.sys, "stdout", stdout):
            with patch.object(webbridge_client.sys, "stderr", stderr):
                webbridge_client.configure_utf8_output()

        stdout.reconfigure.assert_called_once_with(encoding="utf-8", newline="\n")
        stderr.reconfigure.assert_called_once_with(encoding="utf-8", newline="\n")

    def test_parse_status_output_accepts_json(self):
        status, error = doctor.parse_status_output(
            '{"running":true,"extension_connected":false}'
        )

        self.assertIsNone(error)
        self.assertEqual(
            status, {"running": True, "extension_connected": False}
        )

    def test_parse_status_output_reports_invalid_json(self):
        status, error = doctor.parse_status_output("not json")

        self.assertIsNone(status)
        self.assertIn("invalid status JSON", error)

    def test_parse_status_output_rejects_non_object_json(self):
        for payload in ("true", '"text"', "123", "[]"):
            with self.subTest(payload=payload):
                status, error = doctor.parse_status_output(payload)

                self.assertIsNone(status)
                self.assertIn("invalid status shape", error)

    def test_run_binary_reports_os_errors(self):
        with patch.object(doctor.subprocess, "run", side_effect=PermissionError("denied")):
            result = doctor.run_binary(Path("fake-binary"), "status")

        self.assertIsNone(result["returncode"])
        self.assertEqual(result["stdout"], "")
        self.assertIn("denied", result["stderr"])

    def test_recommends_waiting_for_disconnected_extension(self):
        report = {
            "binary": {"exists": True},
            "status": {"running": True, "extension_connected": False},
            "pid_file": {"exists": False},
            "port_open": True,
        }

        recommendations = doctor.build_recommendations(report)

        self.assertTrue(
            any("--wait-connected" in item for item in recommendations)
        )

    def test_ready_requires_reachable_daemon_port(self):
        report = {
            "binary": {"exists": True},
            "status": {"running": True, "extension_connected": True},
            "pid_file": {"exists": False},
            "port_open": False,
        }

        self.assertFalse(doctor.report_ready(report))

        recommendations = doctor.build_recommendations(report)
        self.assertFalse(any(item.startswith("Ready:") for item in recommendations))
        self.assertTrue(any("port 10086 is not reachable" in item for item in recommendations))
        self.assertEqual(doctor.readiness_reason(report), "daemon port not reachable")

    def test_port_failure_takes_priority_over_extension_failure(self):
        report = {
            "binary": {"exists": True},
            "status": {"running": True, "extension_connected": False},
            "pid_file": {"exists": False},
            "port_open": False,
        }

        recommendations = doctor.build_recommendations(report)

        self.assertEqual(doctor.readiness_reason(report), "daemon port not reachable")
        self.assertIn("port 10086 is not reachable", recommendations[0])
        self.assertFalse(
            any("enable the Kimi WebBridge extension" in item for item in recommendations),
            recommendations,
        )

    def test_readiness_reason_reports_extension_disconnect(self):
        report = {
            "binary": {"exists": True},
            "status": {"running": True, "extension_connected": False},
            "pid_file": {"exists": False},
            "port_open": True,
        }

        self.assertEqual(doctor.readiness_reason(report), "extension not connected")

    def test_json_flag_is_accepted(self):
        with patch.object(sys, "argv", ["doctor.py", "--json"]):
            args = doctor.parse_args()

        self.assertTrue(args.json)

    def test_extension_id_mismatch_is_not_hard_failure(self):
        report = {
            "binary": {"exists": True},
            "status": {
                "running": True,
                "extension_connected": True,
                "extension_id": "runtime-specific-id",
            },
            "pid_file": {"exists": False},
            "port_open": True,
        }

        recommendations = doctor.build_recommendations(report)

        self.assertTrue(any("not treat extension_id mismatch" in item for item in recommendations))

    def test_stale_pid_gets_explicit_recommendation(self):
        report = {
            "binary": {"exists": True},
            "status": {"running": False, "extension_connected": False},
            "pid_file": {"exists": True, "stale": True},
            "port_open": False,
        }

        recommendations = doctor.build_recommendations(report)

        self.assertTrue(any("daemon.pid" in item for item in recommendations))
        self.assertTrue(any("--start --wait-connected 20" in item for item in recommendations))
        self.assertTrue(any("Try doctor.py --start first" in item for item in recommendations))

    def test_skill_conflict_requires_both_skills_in_same_root(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("kimi-webbridge", "kimi-webbridge-pro"):
                skill = root / name
                skill.mkdir()
                (skill / "SKILL.md").write_text("---\n", encoding="utf-8")

            conflicts = doctor.inspect_skill_conflicts([root])

        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0]["skills_dir"], str(root))

    def test_skills_in_different_roots_get_conditional_conflict_warning(self):
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            first = parent / "first"
            second = parent / "second"
            (first / "kimi-webbridge").mkdir(parents=True)
            (second / "kimi-webbridge-pro").mkdir(parents=True)
            (first / "kimi-webbridge" / "SKILL.md").write_text("x", encoding="utf-8")
            (second / "kimi-webbridge-pro" / "SKILL.md").write_text("x", encoding="utf-8")

            conflicts = doctor.inspect_skill_conflicts([first, second])

        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0]["scope"], "multiple_roots")

    def test_version_mismatch_gets_non_blocking_alignment_recommendation(self):
        report = {
            "binary": {"exists": True},
            "status": {
                "running": True,
                "extension_connected": True,
                "version": "v1.11.3",
                "extension_version": "1.9.10",
            },
            "pid_file": {"exists": False},
            "port_open": True,
        }

        recommendations = doctor.build_recommendations(report)

        self.assertTrue(any("versions differ" in item for item in recommendations))
        self.assertTrue(any("kimi-webbridge upgrade" in item for item in recommendations))
        self.assertTrue(doctor.report_ready(report))

    def test_unparseable_version_is_not_labeled_outdated(self):
        report = {
            "binary": {"exists": True},
            "status": {
                "running": True,
                "extension_connected": True,
                "version": "unknown",
                "extension_version": "unknown",
            },
            "pid_file": {"exists": False},
            "port_open": True,
        }

        recommendations = doctor.build_recommendations(report)

        self.assertFalse(any("versions differ" in item for item in recommendations))

    def test_sleep_until_deadline_clamps_to_remaining_time(self):
        with patch.object(doctor.time, "monotonic", return_value=3.0):
            with patch.object(doctor.time, "sleep") as sleep:
                self.assertTrue(doctor.sleep_until_deadline(5.0, 10.0))

        sleep.assert_called_once_with(2.0)

    def test_sleep_until_deadline_skips_elapsed_deadline(self):
        with patch.object(doctor.time, "monotonic", return_value=5.0):
            with patch.object(doctor.time, "sleep") as sleep:
                self.assertFalse(doctor.sleep_until_deadline(5.0, 10.0))

        sleep.assert_not_called()

    def test_probe_command_reports_success(self):
        response = {"ok": True, "data": {"success": True, "tabs": []}}
        with patch.object(doctor, "post_command", return_value=response) as post:
            probe = doctor.probe_command("127.0.0.1", 10086, 5)

        self.assertEqual(probe, {"ok": True, "tab_count": 0})
        post.assert_called_once_with(
            "list_tabs", {}, "doctor-probe", "http://127.0.0.1:10086", 5
        )

    def test_probe_command_formats_ipv6_daemon_url(self):
        response = {"ok": True, "data": {"success": True, "tabs": []}}
        with patch.object(doctor, "post_command", return_value=response) as post:
            probe = doctor.probe_command("::1", 10086, 5)

        self.assertTrue(probe["ok"])
        post.assert_called_once_with(
            "list_tabs", {}, "doctor-probe", "http://[::1]:10086", 5
        )

    def test_port_recommendation_uses_configured_port(self):
        report = {
            "daemon": {"host": "127.0.0.1", "port": 12345},
            "binary": {"exists": True},
            "status": {"running": True, "extension_connected": True},
            "pid_file": {"exists": False},
            "port_open": False,
        }

        recommendations = doctor.build_recommendations(report)

        self.assertTrue(any("port 12345" in item for item in recommendations))

    def test_probe_command_reports_failure(self):
        with patch.object(doctor, "post_command", side_effect=RuntimeError("boom")):
            probe = doctor.probe_command("127.0.0.1", 10086, 5)

        self.assertFalse(probe["ok"])
        self.assertIn("boom", probe["error"])

    def test_probe_command_rejects_incomplete_success_responses(self):
        responses = [
            {},
            {"ok": True},
            {"ok": True, "data": None},
            {"ok": True, "data": {}},
            {"ok": True, "data": {"success": True}},
        ]
        for response in responses:
            with self.subTest(response=response):
                with patch.object(doctor, "post_command", return_value=response):
                    probe = doctor.probe_command("127.0.0.1", 10086, 5)
                self.assertFalse(probe["ok"])

    def test_probe_command_enforces_wall_clock_timeout(self):
        def slow_command(*_args, **_kwargs):
            time.sleep(0.1)
            return {"ok": True, "data": {"success": True, "tabs": []}}

        started = time.monotonic()
        with patch.object(doctor, "post_command", side_effect=slow_command):
            probe = doctor.probe_command("127.0.0.1", 10086, 0.01)
        elapsed = time.monotonic() - started

        self.assertFalse(probe["ok"])
        self.assertIn("wall-clock timeout", probe["error"])
        self.assertLess(elapsed, 0.08)

    def test_probe_timeout_rejects_non_finite_values(self):
        for value in ("nan", "inf", "-inf", "0", "301"):
            with self.subTest(value=value):
                with patch.object(sys, "argv", ["doctor.py", "--probe-timeout", value]):
                    with self.assertRaises(SystemExit):
                        doctor.parse_args()

    def test_wait_timeout_values_must_be_finite(self):
        for option, value in (
            ("--wait-connected", "nan"),
            ("--wait-connected", "inf"),
            ("--wait-connected", "-1"),
            ("--interval", "nan"),
            ("--interval", "0"),
        ):
            with self.subTest(option=option, value=value):
                with patch.object(sys, "argv", ["doctor.py", option, value]):
                    with self.assertRaises(SystemExit):
                        doctor.parse_args()

    def test_failed_probe_marks_report_not_ready(self):
        report = {
            "binary": {"exists": True},
            "status": {"running": True, "extension_connected": True},
            "pid_file": {"exists": False},
            "port_open": True,
            "probe": {"ok": False, "error": "timed out"},
        }

        self.assertFalse(doctor.report_ready(report))
        self.assertEqual(
            doctor.readiness_reason(report),
            "extension connected but command probe failed",
        )

        recommendations = doctor.build_recommendations(report)
        self.assertTrue(any("restart" in item.lower() for item in recommendations))
        self.assertFalse(any(item.startswith("Ready:") for item in recommendations))

    def test_successful_probe_keeps_ready(self):
        report = {
            "binary": {"exists": True},
            "status": {"running": True, "extension_connected": True},
            "pid_file": {"exists": False},
            "port_open": True,
            "probe": {"ok": True},
        }

        self.assertTrue(doctor.report_ready(report))
        self.assertEqual(doctor.readiness_reason(report), "ready")

        recommendations = doctor.build_recommendations(report)
        self.assertTrue(any(item.startswith("Ready:") for item in recommendations))

    def test_probe_command_reports_command_level_failure(self):
        response = {"ok": True, "data": {"success": False, "error": "no tab selected"}}
        with patch.object(doctor, "post_command", return_value=response):
            probe = doctor.probe_command("127.0.0.1", 10086, 5)

        self.assertFalse(probe["ok"])
        self.assertIn("no tab selected", probe["error"])

    def test_skipped_probe_does_not_affect_readiness(self):
        report = {
            "binary": {"exists": True},
            "status": {"running": True, "extension_connected": True},
            "pid_file": {"exists": False},
            "port_open": True,
            "probe": {"skipped": True, "reason": "passive checks not ready"},
        }

        self.assertFalse(doctor.probe_failed(report))
        self.assertTrue(doctor.report_ready(report))
        self.assertEqual(doctor.readiness_reason(report), "ready")

    def test_post_command_normalizes_timeout_to_runtime_error(self):
        with patch.object(
            webbridge_client.urllib.request, "urlopen", side_effect=TimeoutError("timed out")
        ):
            with self.assertRaises(RuntimeError) as context:
                webbridge_client.post_command(
                    "list_tabs", {}, "doctor-probe", "http://127.0.0.1:10086", 5
                )

        self.assertIn("timed out", str(context.exception))

    def test_post_command_normalizes_malformed_json_to_runtime_error(self):
        response = MagicMock()
        response.__enter__.return_value = io.BytesIO(b"<html>not json</html>")
        with patch.object(webbridge_client.urllib.request, "urlopen", return_value=response):
            with self.assertRaises(RuntimeError) as context:
                webbridge_client.post_command(
                    "list_tabs", {}, "doctor-probe", "http://127.0.0.1:10086", 5
                )

        self.assertIn("malformed response", str(context.exception))

    def test_post_command_rejects_non_object_json(self):
        for payload in (b"null", b"[]", b'"ok"'):
            with self.subTest(payload=payload):
                response = MagicMock()
                response.__enter__.return_value = io.BytesIO(payload)
                with patch.object(
                    webbridge_client.urllib.request, "urlopen", return_value=response
                ):
                    with self.assertRaises(RuntimeError) as context:
                        webbridge_client.post_command(
                            "list_tabs", {}, "doctor-probe", "http://127.0.0.1:10086", 5
                        )

                self.assertIn("expected a JSON object", str(context.exception))

    def test_post_command_normalizes_invalid_utf8(self):
        response = MagicMock()
        response.__enter__.return_value = io.BytesIO(b'{"ok": true, "bad": "\xff"}')
        with patch.object(webbridge_client.urllib.request, "urlopen", return_value=response):
            with self.assertRaises(RuntimeError) as context:
                webbridge_client.post_command(
                    "list_tabs", {}, "doctor-probe", "http://127.0.0.1:10086", 5
                )

        self.assertIn("malformed response", str(context.exception))

    def test_post_command_normalizes_http_error_body_timeout(self):
        error = webbridge_client.urllib.error.HTTPError(
            "http://127.0.0.1:10086/command", 500, "error", {}, None
        )
        error.read = MagicMock(side_effect=TimeoutError("body stalled"))
        error.close = MagicMock()
        with patch.object(webbridge_client.urllib.request, "urlopen", side_effect=error):
            with self.assertRaises(RuntimeError) as context:
                webbridge_client.post_command(
                    "list_tabs", {}, "doctor-probe", "http://127.0.0.1:10086", 5
                )

        self.assertIn("unable to read response body", str(context.exception))
        error.close.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
