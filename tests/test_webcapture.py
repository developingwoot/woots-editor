import json
import socket
import subprocess
import sys
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools" / "review_app"))
import make_project  # noqa: E402
import webcapture  # noqa: E402

needs_ffmpeg = pytest.mark.skipif(not make_project.have_ffmpeg(), reason="ffmpeg missing")


def resolves_to(monkeypatch, ip):
    webcapture._seen.clear()
    monkeypatch.setattr(socket, "getaddrinfo", lambda host, port: [(socket.AF_INET, 0, 0, "", (ip, 0))])


@pytest.mark.parametrize("url", ["file:///C:/Windows/win.ini", "ftp://example.com/x", "javascript:alert(1)", "https://user:pw@example.com/", "https:///nohost", ""])
def test_only_plain_web_addresses_are_opened(url):
    with pytest.raises(ValueError):
        webcapture.check_url(url)


@pytest.mark.parametrize("ip", ["127.0.0.1", "10.1.2.3", "192.168.0.5", "169.254.169.254", "::1", "172.16.0.9"])
def test_addresses_on_this_computer_or_the_local_network_are_refused(monkeypatch, ip):
    resolves_to(monkeypatch, ip)
    with pytest.raises(ValueError, match="private network"):
        webcapture.check_url("https://looks-public.example/")


def test_a_public_address_is_allowed(monkeypatch):
    resolves_to(monkeypatch, "93.184.215.14")
    assert webcapture.check_url(" https://example.com/about ") == "https://example.com/about"


def test_length_and_names_are_kept_in_range():
    assert webcapture.seconds_of(100) == webcapture.MAX_S and webcapture.seconds_of(0.1) == webcapture.MIN_S and webcapture.seconds_of("x") == 5.0
    assert webcapture.out_name("https://a/", "still", "") == webcapture.out_name("https://a/", "still", "")
    assert webcapture.out_name("https://a/", "still", "") != webcapture.out_name("https://a/", "scroll", "")


@pytest.fixture
def site(tmp_path):
    filler = "".join(f"<p>Paragraph {i}: filler text about printers and filament.</p>" for i in range(40))
    (tmp_path / "index.html").write_text(
        "<html><head><title>Test Co</title></head><body style='font:22px sans-serif'>"
        "<div id='cookie-banner' style='position:fixed;bottom:0;left:0;right:0;height:200px;background:#333;color:#fff'>We use cookies</div>"
        f"{filler}<p>The company was founded in 2019 and ships to 90 countries.</p>{filler}</body></html>", encoding="utf-8")
    srv = ThreadingHTTPServer(("127.0.0.1", 0), partial(SimpleHTTPRequestHandler, directory=str(tmp_path)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}/"
    srv.shutdown()


def duration(p) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(p)], capture_output=True, text=True)
    return float(out.stdout.strip())


@needs_ffmpeg
@pytest.mark.parametrize("style", ["scroll", "still"])
def test_a_page_becomes_a_clip_with_the_words_found(site, tmp_path, style):
    got = webcapture.capture(site, tmp_path / "out", style, "founded in 2019 and ships to 90 countries", 3, allow_local=True)
    assert got["found"] and got["title"] == "Test Co" and Path(got["still"]).is_file()
    assert abs(duration(got["file"]) - 3.0) < 0.2


@needs_ffmpeg
def test_words_that_are_not_on_the_page_still_give_a_clip(site, tmp_path):
    got = webcapture.capture(site, tmp_path / "out", "still", "words that are nowhere", 2, allow_local=True)
    assert not got["found"] and Path(got["file"]).is_file()


@needs_ffmpeg
def test_a_captured_page_goes_over_the_clip_and_into_the_credits(tmp_path):
    import cutview
    import publish
    import reviewnotes
    import server
    r = make_project.build(cut=True, title="web broll")
    w, n, d = r["work"], r["name"], r["dir"]
    clip = webcapture.out_name("https://example.com/", "still", "")
    f = d / "web-broll" / f"{clip}.mp4"
    f.parent.mkdir(exist_ok=True)
    f.write_bytes(b"x")
    server.attach_web_broll(w, n, "B02", {"file": str(f), "still": str(f.with_suffix(".png")), "url": "https://example.com/", "title": "Example Co", "seconds": 2.0, "found": True}, 0.5)
    assert [x["kind"] for x in reviewnotes.open_notes(w, n, "cut")] == ["web"]
    cutview.set_choice(w, n, "B02", "remove", "Take this clip out", 3.0)               # another choice on the clip keeps the web page
    assert sorted(x["kind"] for x in reviewnotes.open_notes(w, n, "cut")) == ["remove", "web"]
    cutview.set_choice(w, n, "B02", "keep", "", 3.0)
    res = cutview.apply_choices(w, n)
    b = {x["id"]: x for x in json.loads((d / f"{n}.beatmap.json").read_text(encoding="utf-8"))["beats"]}["B02"]
    ins = b["on_screen"]["broll"][-1]
    assert ins["file"] == str(f) and ins["at"] == 0.5 and ins["dur"] == 2.0 and ins["source"]["url"] == "https://example.com/"
    assert res["changes"] == ["Put the web page example.com over the clip at 0:04"]                 # 3.0 s into the cut + 0.5 s
    assert publish.web_credits(w, n) == ["Example Co - https://example.com/"]


@needs_ffmpeg
def test_a_local_address_is_refused_before_any_job_starts():
    import server
    r = make_project.build(cut=True, title="web refused")
    with pytest.raises(ValueError, match="private network"):
        server.start_web_broll(r["work"], r["name"], "B02", "http://127.0.0.1:8765/", "still", "", 3, 0)
    assert not [j for j in server._jobs.values() if j.get("pipeline") == "webcapture"]
