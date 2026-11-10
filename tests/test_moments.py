import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures"))
import builder  # noqa: E402
import make_project  # noqa: E402
import moments  # noqa: E402
import teaching  # noqa: E402

needs_ffmpeg = pytest.mark.skipif(not make_project.have_ffmpeg(), reason="ffmpeg missing")


def project(title):
    r = make_project.build(cut=True, title=title)
    return r["work"], r["name"], r["dir"]


def answer(tmp_path, *rows):
    p = tmp_path / "moments.json"
    p.write_text(json.dumps({"moments": list(rows)}), encoding="utf-8")
    return p


def beat(d, n, bid):
    return {b["id"]: b for b in json.loads((d / f"{n}.beatmap.json").read_text(encoding="utf-8"))["beats"]}[bid]


@needs_ffmpeg
def test_a_short_video_may_have_one_fun_moment_and_only_valid_ones_are_kept(tmp_path):
    w, n, d = project("fun caps")
    assert moments.allowed(w, n) == 1
    ok, msg = moments.import_found(w, n, answer(
        tmp_path,
        {"beat": "ZZ", "kind": "stamp", "text": "NOPE", "why": "no such beat"},
        {"beat": "B02", "kind": "sparkle", "text": "NOPE", "why": "unknown kind"},
        {"beat": "B02", "kind": "stamp", "text": "IT BROKE", "why": "the joke"},
        {"beat": "B03", "kind": "burst", "text": "TOO MANY", "why": "over the limit"}))
    assert ok and msg == "Claude found 1 fun moment." and [m["text"] for m in moments.load(w, n)] == ["IT BROKE"]


@needs_ffmpeg
def test_the_gap_and_the_teaching_clash_are_enforced(tmp_path, monkeypatch):
    w, n, d = project("fun gap")
    monkeypatch.setattr(moments, "allowed", lambda *a, **k: 5)
    teaching.seed(w, n)
    teaching.set_status(w, n, "m1", "yes")                                     # TP01 explains a term: no pop-up there
    ok, _ = moments.import_found(w, n, answer(
        tmp_path,
        {"beat": "TP01", "kind": "stamp", "text": "CLASH", "why": "teaching beat"},
        {"beat": "B01", "kind": "stamp", "text": "FIRST", "why": "ok"},
        {"beat": "B02", "kind": "stamp", "text": "TOO CLOSE", "why": "3 s later, the gap is 8 s"}))
    assert ok and [m["text"] for m in moments.load(w, n)] == ["FIRST"]


@needs_ffmpeg
def test_a_yes_puts_a_short_pop_up_on_the_beat_and_a_no_takes_it_off(tmp_path):
    w, n, d = project("fun accept")
    moments.import_found(w, n, answer(tmp_path, {"beat": "B02", "kind": "stamp", "text": "IT BROKE", "why": "the joke"}))
    moments.set_status(w, n, "f1", "yes")
    g = beat(d, n, "B02")["graphic"]
    assert g["kind"] == "stamp" and g["text"] == "IT BROKE" and g["dur"] == 1.5 and not g["struck"]
    assert [m["id"] for m in moments.accepted(w, n)] == ["f1"]
    moments.set_status(w, n, "f1", "suggested")
    assert beat(d, n, "B02")["graphic"] is None
    with pytest.raises(ValueError):
        moments.set_status(w, n, "f1", "maybe")


@needs_ffmpeg
def test_the_builder_is_told_the_text_and_the_short_length(tmp_path):
    w, n, d = project("fun brief")
    moments.import_found(w, n, answer(tmp_path, {"beat": "B02", "kind": "stamp", "text": "IT BROKE", "why": "the joke"}))
    moments.set_status(w, n, "f1", "yes")
    b = beat(d, n, "B02")
    line = builder.brief(w, n, {"id": "S1", "title": "Part 1", "beats": ["B02"], "dur": 3.0, "asked": []},
                         [b], {"read_s_per_word": 0.3, "read_pad_s": 1.0, "min_visible_s": 1.0}, d, {})
    assert "(stamp)" in line and "on-screen text “IT BROKE”" in line and "about 1.5 s" in line
