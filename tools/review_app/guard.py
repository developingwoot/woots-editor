"""Who may talk to the app. It listens on this computer only (server.HOST); this adds the checks a web page open in the user's own browser could otherwise get around:
- the connection comes from this computer;
- the Host header names this computer and the server's port (a hostile site that points its own name at 127.0.0.1 is refused: DNS rebinding);
- a POST is JSON and, when the browser says where it came from (Origin), it came from the app's own page (a form on another site cannot send JSON, and its Origin differs).
Pure functions: server.py calls `allowed` first thing in every request.
"""
from urllib.parse import urlsplit

LOOPBACK = ("127.0.0.1", "::1", "::ffff:127.0.0.1")
HOSTS = ("localhost", "127.0.0.1", "[::1]")
MAX_BODY = 2 * 1024 * 1024


def _hostport(value: str):
    """(host, port) of a Host header value like 'localhost:8765' or '[::1]:8765'; port None when absent."""
    try:
        u = urlsplit("//" + value.strip())
        host = u.hostname or ""
        port = u.port
    except ValueError:
        return None, None
    return ("[::1]" if host == "::1" else host.lower()), port


def allowed(method: str, headers, client_ip: str, port: int) -> tuple[bool, int, str]:
    """(ok, http status, plain reason). `headers` is anything with .get (the request's headers)."""
    if client_ip not in LOOPBACK:
        return False, 403, "This app only answers on the computer it runs on."
    host, hport = _hostport(headers.get("Host") or "")
    if host not in HOSTS or (hport or 80) != port:
        return False, 403, "Open the app at http://localhost:%d/" % port
    if method == "POST":
        if not (headers.get("Content-Type") or "").lower().startswith("application/json"):
            return False, 415, "Requests to the app must be JSON."
        origin = headers.get("Origin")
        if origin is not None:
            ohost, oport = _hostport(origin.split("://", 1)[-1])
            if ohost != host or (oport or 80) != (hport or 80) or not origin.lower().startswith("http://"):
                return False, 403, "This request came from another web page."
    return True, 200, ""
