"""Start the real server on a spare port against a throwaway data root and make sure it answers."""
import json
import os
import re
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SERVER = REPO / "tools" / "review_app" / "server.py"


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def base():
    import workflow
    workflow.create("Smoke Video")
    port = free_port()
    p = subprocess.Popen([sys.executable, str(SERVER), "--port", str(port), "--host", "127.0.0.1"],
                         env=os.environ.copy(), stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    url = f"http://127.0.0.1:{port}"
    try:
        for _ in range(60):
            if p.poll() is not None:
                pytest.fail("server exited: " + p.stderr.read().decode(errors="replace")[-800:])
            try:
                urllib.request.urlopen(url + "/", timeout=1).read()
                break
            except OSError:
                time.sleep(0.25)
        else:
            pytest.fail("server did not start")
        yield url
    finally:
        p.terminate()
        try:
            p.wait(5)
        except subprocess.TimeoutExpired:
            p.kill()


def get(url):
    with urllib.request.urlopen(url, timeout=10) as r:
        return r.status, r.read()


def test_index_and_every_script_it_loads(base):
    status, body = get(base + "/")
    assert status == 200
    scripts = re.findall(r'<script src="(/static/[^"]+)"', body.decode("utf-8"))
    assert len(scripts) >= 10
    for s in scripts:
        assert get(base + s)[0] == 200, s


def test_works_api_serves_json(base):
    status, body = get(base + "/api/works")
    assert status == 200
    assert isinstance(json.loads(body), list)


def test_history_endpoints_list_diff_and_restore(base):
    import json as _json
    import workflow
    r = workflow.create("History Endpoints")
    p = workflow.WORK / r["work"] / f"{r['name']}.script.md"
    p.write_text("S01 first", encoding="utf-8")
    q = f"work={r['work']}&name={r['name']}&file={p.name}"
    first = _json.loads(get(f"{base}/api/history?{q}")[1])["entries"]
    assert first[0]["file"].endswith(".script.md")
    p.write_text("S01 second", encoding="utf-8")
    entries = _json.loads(get(f"{base}/api/history?{q}")[1])["entries"]
    assert len(entries) == 2
    d = _json.loads(get(f"{base}/api/history/diff?{q}&id={entries[1]['id']}&other={entries[0]['id']}")[1])
    assert "+S01 second" in d["text"]
    req = urllib.request.Request(f"{base}/api/history/restore", data=_json.dumps({"work": r["work"], "id": entries[1]["id"]}).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    urllib.request.urlopen(req, timeout=10).read()
    assert p.read_text(encoding="utf-8") == "S01 first"


def test_shorts_recommendation_and_make_need_a_final(base):
    import json as _json
    import beatmap
    import workflow
    r = workflow.create("Shorts Endpoint")
    wd = workflow.WORK / r["work"]
    beatmap.write_json(wd / f"{r['name']}.beatmap.json", {"version": 1, "beats": [
        {"id": "B01", "section": "A", "dur": 400.0, "start": 0.0, "end": 400.0, "graphic": None, "on_screen": {"broll": []}},
        {"id": "B02", "section": "A", "dur": 10.0, "start": 400.0, "end": 410.0, "graphic": {"kind": "gears", "strength": 4}, "on_screen": {"broll": []}}]})
    rec = _json.loads(get(f"{base}/api/shorts/recommend?work={r['work']}&name={r['name']}")[1])
    assert rec["recommended"] == 1 and rec["strong"] == 1 and rec["final"] is None and rec["has_project"] is False
    req = urllib.request.Request(f"{base}/api/shorts/make", data=_json.dumps({"work": r["work"], "name": r["name"], "count": 2}).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(req, timeout=10)
    assert e.value.code == 400 and "render the final first" in e.value.read().decode()


def test_path_traversal_is_refused(base):
    with pytest.raises(urllib.error.HTTPError) as e:
        get(base + "/static/..%2F..%2Fserver.py")
    assert e.value.code in (400, 403, 404)


def test_shorts_make_refuses_a_silly_count(base):
    import json as _json
    import workflow
    r = workflow.create("Shorts Count")
    req = urllib.request.Request(f"{base}/api/shorts/make", data=_json.dumps({"work": r["work"], "name": r["name"], "count": 99}).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(req, timeout=10)
    assert e.value.code == 400 and "between 1 and" in e.value.read().decode()


def test_v2_page_and_its_module_are_served(base):
    status, body = get(base + "/v2/")
    assert status == 200 and b"/static/v2/app.js" in body
    assert get(base + "/static/v2/app.js")[0] == 200


def test_v2_home_and_video_endpoints(base):
    import json as _json
    import workflow
    workflow.create("V2 Endpoint")
    home = _json.loads(get(base + "/api/v2/home")[1])
    card = next(c for c in home["videos"] if c["title"] == "V2 Endpoint")
    assert {"key", "title", "sentence", "step", "button"} <= set(card)
    v = _json.loads(get(base + "/api/v2/video?key=" + card["key"])[1])
    assert v["step"] == "outline" and len(v["steps"]) == 6
    assert _json.loads(get(base + "/api/v2/job")[1])["job"] is None


def test_v2_notes_make_and_stop_refuse_bad_requests(base):
    import json as _json
    import workflow
    import views
    r = workflow.create("V2 Notes Refusal")
    key = views.key_of(r["work"], r["name"])

    def post(path, body):
        req = urllib.request.Request(base + path, data=_json.dumps(body).encode(), headers={"Content-Type": "application/json"}, method="POST")
        return urllib.request.urlopen(req, timeout=10)
    with pytest.raises(urllib.error.HTTPError) as e:
        post("/api/v2/make", {"key": key, "stage": "preview"})
    assert e.value.code == 400 and "add a note first" in e.value.read().decode()
    with pytest.raises(urllib.error.HTTPError) as e:
        post("/api/v2/notes", {"key": key, "stage": "preview", "op": "add", "text": " ", "t": 1})
    assert e.value.code == 400 and "write the note first" in e.value.read().decode()
    assert _json.loads(post("/api/v2/job/stop", {"id": "nope"}).read()) == {"ok": True}


def test_shorts_from_a_file_refuses_what_is_not_a_video(base, tmp_path):
    (tmp_path / "notes.txt").write_text("hi", encoding="utf-8")
    for path in (str(tmp_path / "notes.txt"), str(tmp_path / "missing.mp4")):
        req = urllib.request.Request(f"{base}/api/v2/shorts/fromfile", data=json.dumps({"path": path}).encode(),
                                     headers={"Content-Type": "application/json"}, method="POST")
        with pytest.raises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(req, timeout=10)
        assert e.value.code == 400 and "pick a video file" in e.value.read().decode()


def test_the_file_picker_lists_video_files_only_when_asked(base, tmp_path):
    (tmp_path / "a.mp4").write_bytes(b"x" * 2000)
    (tmp_path / "b.txt").write_text("no", encoding="utf-8")
    (tmp_path / "sub").mkdir()
    plain = json.loads(urllib.request.urlopen(f"{base}/api/fs?path={urllib.parse.quote(str(tmp_path))}", timeout=10).read())
    withfiles = json.loads(urllib.request.urlopen(f"{base}/api/fs?path={urllib.parse.quote(str(tmp_path))}&files=1", timeout=10).read())
    assert "files" not in plain and plain["videos"] == 1
    assert [f["name"] for f in withfiles["files"]] == ["a.mp4"] and [d["name"] for d in withfiles["dirs"]] == ["sub"]


def test_shorts_from_a_folder_refuses_an_empty_or_missing_folder(base, tmp_path):
    for path in (str(tmp_path), str(tmp_path / "missing")):
        req = urllib.request.Request(f"{base}/api/v2/shorts/fromfolder", data=json.dumps({"path": path}).encode(),
                                     headers={"Content-Type": "application/json"}, method="POST")
        with pytest.raises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(req, timeout=10)
        assert e.value.code == 400 and ("no video files" in e.value.read().decode() or e.value.code == 400)
