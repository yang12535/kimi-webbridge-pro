import http.client
import json
import sys
import urllib.error
import urllib.request


def configure_utf8_output():
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure:
            reconfigure(encoding="utf-8", newline="\n")


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
            try:
                result = json.load(response)
            except (ValueError, UnicodeError, http.client.IncompleteRead) as error:
                raise RuntimeError(f"WebBridge returned a malformed response: {error}") from error
    except urllib.error.HTTPError as error:
        try:
            try:
                payload = error.read()
                detail = ""
            except http.client.IncompleteRead as read_error:
                payload = read_error.partial or b""
                detail = " (response body was truncated)"
            except (TimeoutError, OSError) as read_error:
                payload = b""
                detail = f" (unable to read response body: {read_error})"
        finally:
            error.close()
        message = payload.decode("utf-8", errors="replace")
        raise RuntimeError(f"WebBridge HTTP {error.code}: {message}{detail}") from error
    except TimeoutError as error:
        raise RuntimeError(f"WebBridge request timed out: {error}") from error
    except urllib.error.URLError as error:
        if isinstance(error.reason, TimeoutError):
            raise RuntimeError(f"WebBridge request timed out: {error.reason}") from error
        raise RuntimeError(f"WebBridge request failed: {error.reason}") from error
    except OSError as error:
        raise RuntimeError(f"WebBridge request failed: {error}") from error

    if not isinstance(result, dict):
        raise RuntimeError("WebBridge returned a malformed response: expected a JSON object.")
    if result.get("ok") is False:
        raise RuntimeError(result.get("error") or "Kimi WebBridge command failed.")
    return result
