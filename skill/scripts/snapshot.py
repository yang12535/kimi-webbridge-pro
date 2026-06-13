#!/usr/bin/env python3

import argparse
import json
import tempfile
from pathlib import Path

from webbridge_client import configure_utf8_output, post_command


def parse_args():
    parser = argparse.ArgumentParser(
        description="Capture a WebBridge snapshot without flooding agent context."
    )
    parser.add_argument("--session", help="Stable task session name")
    parser.add_argument(
        "--mode",
        choices=("compact", "file", "full"),
        default="compact",
        help="compact summary, file path, or full JSON output",
    )
    parser.add_argument("--output", type=Path, help="Path used by file mode")
    parser.add_argument(
        "--daemon-url",
        default="http://127.0.0.1:10086",
        help="WebBridge daemon URL",
    )
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--max-elements", type=int, default=250)
    parser.add_argument("--max-name-length", type=int, default=240)
    return parser.parse_args()


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

    # Keep semantic landmarks and actionable refs; omit most static text.
    def walk(nodes):
        if len(elements) >= max_elements:
            return
        if isinstance(nodes, list):
            for node in nodes:
                walk(node)
                if len(elements) >= max_elements:
                    return
            return
        if not isinstance(nodes, dict):
            return

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
        walk(nodes.get("children"))

    walk(data.get("tree"))
    return {
        "ok": response.get("ok"),
        "url": data.get("url"),
        "title": data.get("title"),
        "elements": elements,
        "truncated": len(elements) >= max_elements,
    }


def write_snapshot(response, output):
    if output is None:
        directory = Path(tempfile.gettempdir()) / "kimi-webbridge-snapshots"
        directory.mkdir(parents=True, exist_ok=True)
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
    return output.resolve()


def main():
    configure_utf8_output()
    args = parse_args()
    response = request_snapshot(args)

    if args.mode == "file":
        print(write_snapshot(response, args.output))
    elif args.mode == "full":
        print(json.dumps(response, ensure_ascii=False, separators=(",", ":")))
    else:
        result = compact_snapshot(
            response,
            max_elements=args.max_elements,
            max_name_length=args.max_name_length,
        )
        print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))


if __name__ == "__main__":
    main()
