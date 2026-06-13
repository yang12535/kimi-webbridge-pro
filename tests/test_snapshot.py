import sys
import unittest
from pathlib import Path


SCRIPTS_DIR = Path(__file__).parents[1] / "skill" / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from snapshot import compact_snapshot  # noqa: E402


class CompactSnapshotTests(unittest.TestCase):
    def test_nested_lists_are_flattened(self):
        response = {
            "ok": True,
            "data": {
                "url": "https://example.com",
                "title": "Example",
                "tree": [
                    [
                        {"role": "link", "name": "First", "ref": "@e1"},
                        {"role": "button", "name": "Second", "ref": "@e2"},
                    ],
                    [{"role": "heading", "name": "Nested heading"}],
                ],
            },
        }

        result = compact_snapshot(response, max_elements=10, max_name_length=240)

        self.assertEqual(
            [item["role"] for item in result["elements"]],
            ["link", "button", "heading"],
        )
        self.assertEqual(result["elements"][0]["ref"], "@e1")
        self.assertEqual(result["elements"][0]["usage"], "click selector @e1")
        self.assertFalse(result["truncated"])

    def test_non_mapping_children_are_ignored(self):
        response = {
            "ok": True,
            "data": {
                "tree": [
                    None,
                    "unexpected",
                    {"role": "heading", "name": "Still works", "children": [42]},
                ]
            },
        }

        result = compact_snapshot(response, max_elements=10, max_name_length=240)

        self.assertEqual(result["elements"], [{"role": "heading", "name": "Still works"}])

    def test_max_elements_sets_truncated(self):
        response = {
            "ok": True,
            "data": {
                "tree": [
                    {"role": "link", "name": "One", "ref": "@e1"},
                    {"role": "link", "name": "Two", "ref": "@e2"},
                ]
            },
        }

        result = compact_snapshot(response, max_elements=1, max_name_length=240)

        self.assertEqual(len(result["elements"]), 1)
        self.assertTrue(result["truncated"])


if __name__ == "__main__":
    unittest.main()
