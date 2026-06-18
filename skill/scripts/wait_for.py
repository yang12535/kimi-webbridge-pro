#!/usr/bin/env python3

import argparse
import json
import time

from webbridge_client import configure_utf8_output, post_command


def parse_args():
    parser = argparse.ArgumentParser(
        description="Poll the selected WebBridge tab until a page condition matches."
    )
    parser.add_argument("--session", help="Stable task session name")
    parser.add_argument("--url-contains")
    parser.add_argument("--title-contains")
    parser.add_argument(
        "--text-contains",
        "--visible-text",
        dest="text_contains",
        help="Wait until accessible text contains this value.",
    )
    parser.add_argument("--timeout", type=float, default=10)
    parser.add_argument("--interval", type=float, default=1)
    parser.add_argument(
        "--daemon-url",
        default="http://127.0.0.1:10086",
        help="WebBridge daemon URL",
    )
    return parser.parse_args()


def iter_names(nodes):
    if isinstance(nodes, list):
        for node in nodes:
            yield from iter_names(node)
    elif isinstance(nodes, dict):
        name = nodes.get("name")
        if name:
            yield str(name)
        yield from iter_names(nodes.get("children"))


def matches(args, data):
    url = data.get("url") or ""
    title = data.get("title") or ""
    if args.url_contains and args.url_contains not in url:
        return False
    if args.title_contains and args.title_contains not in title:
        return False
    if args.text_contains:
        text = "\n".join(iter_names(data.get("tree")))
        if args.text_contains not in text:
            return False
    return True


def main():
    configure_utf8_output()
    args = parse_args()
    if not any((args.url_contains, args.title_contains, args.text_contains)):
        raise SystemExit("Specify at least one URL, title, or text condition.")
    if args.timeout <= 0 or args.interval <= 0:
        raise SystemExit("--timeout and --interval must be positive.")

    deadline = time.monotonic() + args.timeout
    last_data = {}
    while True:
        try:
            response = post_command(
                action="snapshot",
                args={},
                session=args.session,
                daemon_url=args.daemon_url,
                timeout=max(1, int(args.interval + 5)),
            )
        except RuntimeError as error:
            raise SystemExit(str(error)) from error

        last_data = response.get("data") or {}
        if matches(args, last_data):
            print(
                json.dumps(
                    {
                        "matched": True,
                        "url": last_data.get("url"),
                        "title": last_data.get("title"),
                    },
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
            )
            return
        if time.monotonic() >= deadline:
            break
        time.sleep(args.interval)

    print(
        json.dumps(
            {
                "matched": False,
                "url": last_data.get("url"),
                "title": last_data.get("title"),
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
    )
    raise SystemExit(1)


if __name__ == "__main__":
    main()
