import sys
import unittest
from pathlib import Path
from unittest.mock import patch


SCRIPTS_DIR = Path(__file__).parents[1] / "skill" / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import wait_for  # noqa: E402


class WaitForArgumentTests(unittest.TestCase):
    def test_visible_text_alias_maps_to_text_contains(self):
        with patch.object(
            sys,
            "argv",
            ["wait_for.py", "--session", "demo", "--visible-text", "Ready"],
        ):
            args = wait_for.parse_args()

        self.assertEqual(args.text_contains, "Ready")


if __name__ == "__main__":
    unittest.main()
