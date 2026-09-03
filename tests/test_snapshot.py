import sys
import json
import shutil
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


SCRIPTS_DIR = Path(__file__).parents[1] / "skill" / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from snapshot import auto_snapshot, compact_snapshot, parse_args, write_snapshot  # noqa: E402
from screenshot import default_output_path  # noqa: E402


class CompactSnapshotTests(unittest.TestCase):
    def test_compact_snapshot_does_not_enqueue_large_flat_lists(self):
        class CountingList(list):
            def __init__(self, *args):
                super().__init__(*args)
                self.iterated = 0
                self.reversed = 0

            def __iter__(self):
                for item in super().__iter__():
                    self.iterated += 1
                    yield item

            def __reversed__(self):
                for item in super().__reversed__():
                    self.reversed += 1
                    yield item

        children = CountingList(
            {"role": "link", "name": f"Item {index}", "ref": f"@e{index}"}
            for index in range(1000)
        )
        response = {"ok": True, "data": {"tree": children}}

        result = compact_snapshot(response, max_elements=1, max_name_length=240)

        self.assertEqual(len(result["elements"]), 1)
        self.assertTrue(result["truncated"])
        self.assertEqual(children.iterated, 2)
        self.assertEqual(children.reversed, 0)

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

    def test_exact_max_elements_is_not_truncated(self):
        response = {
            "ok": True,
            "data": {"tree": [{"role": "link", "name": "One", "ref": "@e1"}]},
        }

        result = compact_snapshot(response, max_elements=1, max_name_length=240)

        self.assertEqual(len(result["elements"]), 1)
        self.assertFalse(result["truncated"])

    def test_compact_snapshot_handles_deep_trees_iteratively(self):
        tree = {"role": "heading", "name": "deep leaf"}
        for _ in range(3000):
            tree = {"role": "generic", "children": [tree]}

        result = compact_snapshot(
            {
                "ok": True,
                "data": {
                    "url": "https://example.com",
                    "title": "Deep",
                    "tree": tree,
                },
            },
            max_elements=10,
            max_name_length=240,
        )

        self.assertEqual(result["elements"], [{"role": "heading", "name": "deep leaf"}])

    def test_auto_mode_returns_compact_for_small_snapshots(self):
        response = {
            "ok": True,
            "data": {
                "url": "https://example.com",
                "title": "Example",
                "tree": [{"role": "link", "name": "Read", "ref": "@e1"}],
            },
        }
        args = type(
            "Args",
            (),
            {
                "max_elements": 10,
                "max_name_length": 240,
                "max_inline_bytes": 10000,
                "output": None,
            },
        )()

        result = auto_snapshot(response, args)

        self.assertEqual(result["mode"], "compact")
        self.assertEqual(result["elements"][0]["usage"], "click selector @e1")
        self.assertIn("snapshot_bytes", result)

    def test_auto_mode_writes_file_when_snapshot_is_large(self):
        response = {
            "ok": True,
            "data": {
                "url": "https://example.com",
                "title": "Example",
                "tree": [{"role": "heading", "name": "A" * 200}],
            },
        }
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "snapshot.json"
            args = type(
                "Args",
                (),
                {
                    "max_elements": 10,
                    "max_name_length": 240,
                    "max_inline_bytes": 1,
                    "output": output,
                },
            )()

            result = auto_snapshot(response, args)

            self.assertEqual(result["mode"], "file")
            self.assertEqual(Path(result["path"]), output.resolve())
            self.assertTrue(output.exists())
            self.assertEqual(result["reason"], "compact output exceeds max-inline-bytes")
            self.assertNotIn("compact_preview", result)
            self.assertEqual(result["file_bytes"], output.stat().st_size)

    def test_file_envelope_bounds_untrusted_url_and_title(self):
        response = {
            "ok": True,
            "data": {
                "url": "https://example.com/" + "路径" * 10000,
                "title": "标题" * 10000,
                "tree": [],
            },
        }
        with tempfile.TemporaryDirectory() as directory:
            args = type(
                "Args",
                (),
                {
                    "max_elements": 10,
                    "max_name_length": 240,
                    "max_inline_bytes": 12000,
                    "output": Path(directory) / "snapshot.json",
                },
            )()

            result = auto_snapshot(response, args)

        encoded = (json.dumps(result, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        self.assertEqual(result["mode"], "file")
        self.assertLess(len(encoded), 12000)
        self.assertLessEqual(len(result["url_preview"]), 512)
        self.assertLessEqual(len(result["title_preview"]), 512)
        self.assertTrue(result["url_preview"].endswith("…"))
        self.assertTrue(result["title_preview"].endswith("…"))

    def test_auto_mode_budgets_compact_output_not_large_static_raw_tree(self):
        response = {
            "ok": True,
            "data": {
                "url": "https://example.com",
                "title": "Example",
                "tree": {"role": "generic", "name": "A" * 50000},
            },
        }
        args = type(
            "Args",
            (),
            {
                "max_elements": 10,
                "max_name_length": 240,
                "max_inline_bytes": 1000,
                "output": None,
            },
        )()

        result = auto_snapshot(response, args)

        self.assertEqual(result["mode"], "compact")
        self.assertGreater(result["snapshot_bytes"], 50000)

    def test_legacy_auto_file_bytes_still_forces_on_raw_size(self):
        response = {
            "ok": True,
            "data": {"tree": {"role": "generic", "name": "A" * 100}},
        }
        with tempfile.TemporaryDirectory() as directory:
            args = type(
                "Args",
                (),
                {
                    "max_elements": 10,
                    "max_name_length": 240,
                    "max_inline_bytes": 10000,
                    "raw_file_bytes": 1,
                    "output": Path(directory) / "snapshot.json",
                },
            )()

            result = auto_snapshot(response, args)

        self.assertEqual(result["mode"], "file")
        self.assertEqual(result["reason"], "raw snapshot reached legacy auto-file-bytes")

    def test_default_file_output_is_private_and_newline_terminated(self):
        response = {"ok": True, "data": {"tree": []}}
        output = write_snapshot(response, None)
        try:
            if sys.platform != "win32":
                self.assertEqual(stat.S_IMODE(output.parent.stat().st_mode), 0o700)
            self.assertTrue(output.read_bytes().endswith(b"\n"))
        finally:
            shutil.rmtree(output.parent)

    def test_default_screenshot_output_uses_private_directory(self):
        output = default_output_path("png")
        try:
            if sys.platform != "win32":
                self.assertEqual(stat.S_IMODE(output.parent.stat().st_mode), 0o700)
            self.assertEqual(output.suffix, ".png")
        finally:
            shutil.rmtree(output.parent)

    def test_auto_flag_sets_mode(self):
        with patch.object(sys, "argv", ["snapshot.py", "--auto"]):
            args = parse_args()

        self.assertEqual(args.mode, "auto")

    def test_legacy_auto_file_bytes_accepts_zero(self):
        with patch.object(sys, "argv", ["snapshot.py", "--auto", "--auto-file-bytes", "0"]):
            args = parse_args()

        self.assertEqual(args.raw_file_bytes, 0)

    def test_output_alias_is_accepted_for_file_mode(self):
        with patch.object(
            sys, "argv", ["snapshot.py", "--mode", "file", "--path", "result.json"]
        ):
            args = parse_args()

        self.assertEqual(args.output, Path("result.json"))

    def test_auto_and_mode_are_mutually_exclusive(self):
        with patch.object(sys, "argv", ["snapshot.py", "--auto", "--mode", "file"]):
            with self.assertRaises(SystemExit):
                parse_args()

    def test_output_is_rejected_in_compact_mode(self):
        with patch.object(sys, "argv", ["snapshot.py", "--output", "result.json"]):
            with self.assertRaises(SystemExit):
                parse_args()

    def test_numeric_limits_must_be_positive(self):
        for option in ("--timeout", "--max-elements", "--max-name-length", "--max-inline-bytes"):
            with self.subTest(option=option):
                with patch.object(sys, "argv", ["snapshot.py", option, "0"]):
                    with self.assertRaises(SystemExit):
                        parse_args()


if __name__ == "__main__":
    unittest.main()
