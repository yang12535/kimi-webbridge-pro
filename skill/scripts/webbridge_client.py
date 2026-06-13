import json
import sys
import urllib.error
import urllib.request


def configure_utf8_output():
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure:
            reconfigure(encoding="utf-8")


def post_command(action, args, session, daemon_url, timeout):
    body = {"action": action, "args": args}
    if session:
        body["session"] = session

    request = urllib.request.Request(
        f"{daemon_url}/command",
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            result = json.load(response)
    except urllib.error.HTTPError as error:
        message = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"WebBridge HTTP {error.code}: {message}") from error
    except urllib.error.URLError as error:
        raise RuntimeError(f"WebBridge request failed: {error.reason}") from error

    if result.get("ok") is False:
        raise RuntimeError(result.get("error") or "Kimi WebBridge command failed.")
    return result
