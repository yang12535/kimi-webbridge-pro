#!/usr/bin/env python3

import argparse
import base64
import shutil
import tempfile
from pathlib import Path

from webbridge_client import configure_utf8_output, post_command


def parse_args():
    parser = argparse.ArgumentParser(
        description="Capture a WebBridge screenshot and return a local path."
    )
    parser.add_argument("--session", help="Stable task session name")
    parser.add_argument("--output", type=Path, help="Optional destination path")
    parser.add_argument("--format", choices=("png", "jpeg"), default="png")
    parser.add_argument("--quality", type=int, default=80)
    parser.add_argument("--selector", help="Optional @e ref or CSS selector")
    parser.add_argument(
        "--daemon-url",
        default="http://127.0.0.1:10086",
        help="WebBridge daemon URL",
    )
    parser.add_argument("--timeout", type=int, default=30)
    return parser.parse_args()


def default_output_path(image_format):
    directory = Path(tempfile.gettempdir()) / "kimi-webbridge-screenshots"
    directory.mkdir(parents=True, exist_ok=True)
    suffix = ".jpg" if image_format == "jpeg" else ".png"
    handle = tempfile.NamedTemporaryFile(
        suffix=suffix,
        prefix="screenshot_",
        dir=directory,
        delete=False,
    )
    handle.close()
    return Path(handle.name)


def main():
    configure_utf8_output()
    args = parse_args()
    if not 0 <= args.quality <= 100:
        raise SystemExit("--quality must be between 0 and 100.")

    action_args = {"format": args.format}
    if args.format == "jpeg":
        action_args["quality"] = args.quality
    if args.selector:
        action_args["selector"] = args.selector

    try:
        response = post_command(
            action="screenshot",
            args=action_args,
            session=args.session,
            daemon_url=args.daemon_url,
            timeout=args.timeout,
        )
    except RuntimeError as error:
        raise SystemExit(str(error)) from error

    data = response.get("data") or {}
    source = Path(data["path"]).expanduser() if data.get("path") else None
    if source and not source.exists():
        raise SystemExit(f"Screenshot path does not exist: {source}")

    if source and args.output is None:
        print(source.resolve())
        return

    output = args.output or default_output_path(args.format)
    output = output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)

    if source:
        shutil.copyfile(source, output)
    elif data.get("data"):
        output.write_bytes(base64.b64decode(data["data"], validate=True))
    else:
        raise SystemExit("WebBridge returned neither a screenshot path nor image data.")
    print(output)


if __name__ == "__main__":
    main()
