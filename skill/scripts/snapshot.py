#!/usr/bin/env python3

import argparse
import json
import sys
import tempfile
from pathlib import Path

from webbridge_client import configure_utf8_output, post_command


def positive_int(value):
    try:
        number = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("must be an integer") from error
    if number <= 0:
        raise argparse.ArgumentTypeError("must be positive")
    return number


def nonnegative_int(value):
    try:
        number = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("must be an integer") from error
    if number < 0:
        raise argparse.ArgumentTypeError("must be non-negative")
    return number


def parse_args():
    parser = argparse.ArgumentParser(
        description="Capture a WebBridge snapshot without flooding agent context."
    )
    parser.add_argument("--session", help="Stable task session name")
    strategy = parser.add_mutually_exclusive_group()
    strategy.add_argument(
        "--mode",
        choices=("auto", "compact", "file", "full"),
        default="compact",
        help="auto strategy, compact summary, file path, or full JSON output",
    )
    strategy.add_argument(
        "--auto",
        action="store_const",
        dest="mode",
        const="auto",
        help="Shortcut for --mode auto.",
    )
    parser.add_argument(
        "--output",
        "--path",
        "--file",
        dest="output",
        type=Path,
        help="Destination used by file/auto mode; --path and --file are aliases.",
    )
    parser.add_argument(
        "--metadata",
        action="store_true",
        help="In explicit file mode, also print byte-count JSON to stderr.",
    )
    parser.add_argument(
        "--daemon-url",
        default="http://127.0.0.1:10086",
        help="WebBridge daemon URL",
    )
    parser.add_argument("--timeout", type=positive_int, default=30)
    parser.add_argument("--max-elements", type=positive_int, default=250)
    parser.add_argument("--max-name-length", type=positive_int, default=240)
    parser.add_argument(
        "--max-inline-bytes",
        dest="max_inline_bytes",
        type=positive_int,
        default=12000,
        help="Auto mode inline compact-output budget (default: 12000 bytes).",
    )
    parser.add_argument(
        "--auto-file-bytes",
        dest="raw_file_bytes",
        type=nonnegative_int,
        help="Legacy raw-snapshot threshold; also force file mode at this byte count.",
    )
    args = parser.parse_args()
    if args.output and args.mode not in {"auto", "file"}:
        parser.error("--output/--path/--file requires --mode file or --auto")
    if args.metadata and args.mode != "file":
        parser.error("--metadata requires --mode file")
    return args


def request_snapshot(args):
    try:
        return post_command(
            action="snapshot",
            args={},
            session=args.session,
            daemon_url=args.daemon_url,
            timeout=args.timeout,
        )
    except RuntimeError as error:
        raise SystemExit(str(error)) from error


def compact_snapshot(response, max_elements, max_name_length):
    data = response.get("data") or {}
    elements = []
    collection_limit = max_elements + 1

    # Keep semantic landmarks and actionable refs; omit most static text.
    stack = [iter([data.get("tree")])]
    while stack and len(elements) < collection_limit:
        try:
            nodes = next(stack[-1])
        except StopIteration:
            stack.pop()
            continue
        if isinstance(nodes, list):
            stack.append(iter(nodes))
            continue
        if not isinstance(nodes, dict):
            continue

        role = nodes.get("role")
        ref = nodes.get("ref")
        name = nodes.get("name")
        if ref or role in {"heading", "button", "link", "textbox", "combobox"}:
            item = {"role": role}
            if name:
                item["name"] = str(name)[:max_name_length]
            if ref:
                item["ref"] = ref
                if role in {"textbox", "combobox"}:
                    item["usage"] = f"fill selector {ref}"
                elif role in {"button", "link"}:
                    item["usage"] = f"click selector {ref}"
                else:
                    item["usage"] = f"use selector {ref} with click or fill"
            elements.append(item)
        children = nodes.get("children")
        if children is not None:
            stack.append(iter(children if isinstance(children, list) else [children]))
    truncated = len(elements) > max_elements
    return {
        "ok": response.get("ok"),
        "url": data.get("url"),
        "title": data.get("title"),
        "elements": elements[:max_elements],
        "truncated": truncated,
    }


def write_snapshot(response, output):
    if output is None:
        directory = Path(tempfile.mkdtemp(prefix="kimi-webbridge-snapshots-"))
        handle = tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            suffix=".json",
            prefix="snapshot_",
            dir=directory,
            delete=False,
        )
        output = Path(handle.name)
    else:
        output.parent.mkdir(parents=True, exist_ok=True)
        handle = output.open("w", encoding="utf-8")

    with handle:
        json.dump(response, handle, ensure_ascii=False, separators=(",", ":"))
        handle.write("\n")
    return output.resolve()


def snapshot_size_bytes(response):
    return len(json.dumps(response, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


def bounded_preview(value, max_characters=512):
    if value is None:
        return None
    text = str(value)
    if len(text) <= max_characters:
        return text
    if max_characters <= 0:
        return ""
    return text[: max_characters - 1] + "…"


def auto_snapshot(response, args):
    raw_bytes = snapshot_size_bytes(response)
    compact = compact_snapshot(
        response,
        max_elements=args.max_elements,
        max_name_length=args.max_name_length,
    )
    compact["mode"] = "compact"
    compact["snapshot_bytes"] = raw_bytes
    compact_bytes = len(json.dumps(compact, ensure_ascii=False, indent=2).encode("utf-8")) + 1
    raw_file_bytes = getattr(args, "raw_file_bytes", None)
    legacy_raw_limit_reached = raw_file_bytes is not None and raw_bytes >= raw_file_bytes
    should_write_file = (
        compact_bytes > args.max_inline_bytes
        or compact["truncated"]
        or legacy_raw_limit_reached
    )
    if not should_write_file:
        return compact

    path = write_snapshot(response, args.output)
    return {
        "ok": response.get("ok"),
        "mode": "file",
        "path": str(path),
        "url_preview": bounded_preview((response.get("data") or {}).get("url")),
        "title_preview": bounded_preview((response.get("data") or {}).get("title")),
        "snapshot_bytes": raw_bytes,
        "file_bytes": path.stat().st_size,
        "compact_bytes": compact_bytes,
        "compact_elements": len(compact["elements"]),
        "reason": (
            "compact summary reached max-elements"
            if compact["truncated"]
            else (
                "compact output exceeds max-inline-bytes"
                if compact_bytes > args.max_inline_bytes
                else "raw snapshot reached legacy auto-file-bytes"
            )
        ),
    }


def main():
    configure_utf8_output()
    args = parse_args()
    response = request_snapshot(args)

    if args.mode == "auto":
        result = auto_snapshot(response, args)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.mode == "file":
        path = write_snapshot(response, args.output)
        print(path)
        if args.metadata:
            print(
                json.dumps(
                    {
                        "mode": "file",
                        "path": str(path),
                        "snapshot_bytes": snapshot_size_bytes(response),
                        "file_bytes": path.stat().st_size,
                    },
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
                file=sys.stderr,
            )
    elif args.mode == "full":
        print(json.dumps(response, ensure_ascii=False, indent=2))
    else:
        result = compact_snapshot(
            response,
            max_elements=args.max_elements,
            max_name_length=args.max_name_length,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
