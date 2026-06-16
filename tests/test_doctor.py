import sys
import unittest
from pathlib import Path


SCRIPTS_DIR = Path(__file__).parents[1] / "skill" / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import doctor  # noqa: E402


class DoctorTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
