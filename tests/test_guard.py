"""The request guard: this computer only, the app's own address, JSON from the app's own page."""
import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools" / "review_app"))
import guard  # noqa: E402

PORT = 8765
JSON = "application/json"


def ok(method="GET", host="localhost:8765", ip="127.0.0.1", **h):
    return guard.allowed(method, {"Host": host, **h}, ip, PORT)[0]


def test_get_from_this_computer_on_the_app_address():
    for host in ("localhost:8765", "127.0.0.1:8765", "[::1]:8765", "LOCALHOST:8765"):
        assert ok(host=host)
    assert ok(ip="::1") and ok(ip="::ffff:127.0.0.1")


def test_another_computer_is_refused():
    assert guard.allowed("GET", {"Host": "localhost:8765"}, "192.168.1.20", PORT)[1] == 403


def test_a_foreign_host_name_or_port_is_refused():
    for host in ("evil.example:8765", "localhost:9999", "localhost", "192.168.1.5:8765", "", "localhost.evil.example:8765"):
        assert not ok(host=host), host


def test_post_needs_json_from_the_apps_own_page():
    assert ok("POST", **{"Content-Type": JSON})
    assert ok("POST", **{"Content-Type": "application/json; charset=utf-8", "Origin": "http://localhost:8765"})
    assert ok("POST", host="127.0.0.1:8765", **{"Content-Type": JSON, "Origin": "http://127.0.0.1:8765"})
    assert guard.allowed("POST", {"Host": "localhost:8765", "Content-Type": "text/plain"}, "127.0.0.1", PORT)[1] == 415
    assert guard.allowed("POST", {"Host": "localhost:8765"}, "127.0.0.1", PORT)[1] == 415
    for origin in ("https://evil.example", "http://evil.example:8765", "http://localhost:9999", "null", "http://127.0.0.1:8765"):
        assert not ok("POST", **{"Content-Type": JSON, "Origin": origin}), origin       # the last one: the page was opened as localhost, the post says 127.0.0.1


# ---- the real server
def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def base():
    port = _free_port()
    p = subprocess.Popen([sys.executable, str(REPO / "tools" / "review_app" / "server.py"), "--port", str(port)], env=os.environ.copy(),
                         stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    try:
        for _ in range(60):
            if p.poll() is not None:
                pytest.fail("server exited: " + p.stderr.read().decode(errors="replace")[-800:])
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{port}/api/code", timeout=1).read()
                break
            except OSError:
                time.sleep(0.25)
        else:
            pytest.fail("server did not start")
        yield port
    finally:
        p.terminate()
        try:
            p.wait(5)
        except subprocess.TimeoutExpired:
            p.kill()


def _send(port, method, path, headers=None, body=None):
    import http.client
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    c.request(method, path, body=body, headers=headers or {})
    r = c.getresponse()
    data = r.read()
    c.close()
    return r.status, r.getheaders(), data


def test_server_refuses_a_cross_site_post_and_a_foreign_host(base):
    body = json.dumps({"title": "zz csrf probe"})
    assert _send(base, "POST", "/api/v2/video/new", {"Content-Type": "text/plain"}, body)[0] == 415
    assert _send(base, "POST", "/api/v2/video/new", {"Content-Type": JSON, "Origin": "https://evil.example"}, body)[0] == 403
    assert _send(base, "GET", "/api/v2/home", {"Host": "evil.example"})[0] == 403
    assert not any("csrf" in v["title"] for v in json.loads(_send(base, "GET", "/api/v2/home")[2])["videos"])
    assert _send(base, "POST", "/api/v2/video/new", {"Content-Type": JSON, "Origin": f"http://127.0.0.1:{base}"}, body)[0] == 200


def test_server_answers_no_other_computer(base):
    ips = {i[4][0] for i in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)} - {"127.0.0.1"}
    for ip in ips:
        with pytest.raises(OSError):
            socket.create_connection((ip, base), timeout=2).close()


def test_server_sets_safety_headers_and_limits_the_body(base):
    status, headers, _ = _send(base, "GET", "/v2/")
    h = {k.lower(): v for k, v in headers}
    assert status == 200 and h["x-content-type-options"] == "nosniff" and h["x-frame-options"] == "DENY" and "default-src 'self'" in h["content-security-policy"]
    with socket.create_connection(("127.0.0.1", base), timeout=10) as s:             # says the body is too big and sends none: the server must answer without waiting for it
        s.sendall(f"POST /api/v2/video/new HTTP/1.1\r\nHost: localhost:{base}\r\nContent-Type: {JSON}\r\nContent-Length: {guard.MAX_BODY + 10}\r\n\r\n".encode())
        first = s.recv(200).split(b"\r\n")[0]
    assert b" 413 " in first
