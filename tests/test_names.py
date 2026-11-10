"""A video's `work` and `name` are one plain folder name wherever they come from; paths are checked without resolve()."""
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import pytest

import config
import views

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_guard import _send, base, JSON  # noqa: E402,F401  (the real server on a spare port)

BAD = ["..", ".", "", "a/b", "a\\b", "C:x", "..\\x", " lead", "trail.", "a\x00b", "a*b", "x" * 300]


@pytest.mark.parametrize("s", BAD)
def test_safe_part_refuses(s):
    with pytest.raises(ValueError):
        config.safe_part(s)


def test_safe_part_keeps_real_names():
    for s in ("zz-demo", "my video 2", "Café-Test", "a.b"):
        assert config.safe_part(s) == s
    for v in (None, 5, ["a"]):
        with pytest.raises(ValueError):
            config.safe_part(v)


def test_split_key_checks_both_halves():
    assert views.split_key("a~b") == ("a", "b")
    for k in ("..\\..~x", "a~..", "~b", "a~", "nokey", "a/b~c", "a~b/c"):
        with pytest.raises(ValueError):
            views.split_key(k)


def test_inside_folds_dots_and_keeps_the_drive(tmp_path):
    (tmp_path / "a").mkdir()
    assert config.inside(tmp_path, tmp_path / "a" / "f.mp4")
    assert not config.inside(tmp_path, tmp_path)
    assert not config.inside(tmp_path / "a", tmp_path / "a" / ".." / "x.mp4")
    assert not config.inside(tmp_path / "a", Path(str(tmp_path / "a") + "x") / "f")         # a sibling with the same prefix
    assert not config.inside(tmp_path, tmp_path.parent / "elsewhere")


def _status(port, method, path, body=None):
    h = {"Content-Type": JSON} if method == "POST" else {}
    return _send(port, method, path, h, json.dumps(body) if body is not None else None)[0]


def test_server_refuses_bad_names_on_every_kind_of_route(base):
    q = urllib.parse.quote
    assert _status(base, "GET", "/api/v2/tags?key=" + q("..\\..~x")) == 400
    assert _status(base, "GET", "/api/clips?work=..&name=x") == 400
    assert _status(base, "GET", "/api/v2/outline?key=" + q("a~b/c")) == 400
    assert _status(base, "GET", "/media/..%5C..%5Cx/f.mp4") == 400
    assert _status(base, "GET", "/bmedia/ok/..%2Fx/S01") == 400
    assert _status(base, "POST", "/api/v2/notes", {"key": "..~x", "stage": "cut", "op": "add", "text": "t"}) == 400
    assert _status(base, "POST", "/api/wf/settings", {"work": "..", "name": "x", "settings": {}}) == 400
    assert _status(base, "POST", "/api/beatmap/build", {"work": "a", "name": "C:x"}) == 400


def test_a_clip_outside_the_footage_folder_is_refused(base, tmp_path):
    import workflow
    r = workflow.create("Names Outside")
    secret = tmp_path / "secret.mp4"
    secret.write_bytes(b"x")
    folder = tmp_path / "footage"
    folder.mkdir()
    (folder / "ok.mp4").write_bytes(b"x")
    key = views.key_of(r["work"], r["name"])
    assert _status(base, "POST", "/api/v2/footage/folder", {"key": key, "folder": str(folder)}) == 200
    assert _status(base, "GET", f"/fmedia/{r['work']}/{r['name']}/ok.mp4") == 200
    assert _status(base, "GET", f"/fmedia/{r['work']}/{r['name']}/..%2Fsecret.mp4") == 400
    assert _status(base, "GET", f"/fmedia/{r['work']}/{r['name']}/..%5Csecret.mp4") == 400
