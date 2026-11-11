import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools" / "review_app"))
import make_project  # noqa: E402
import makeversion  # noqa: E402
import reviewnotes  # noqa: E402
import views  # noqa: E402

needs_ffmpeg = pytest.mark.skipif(not make_project.have_ffmpeg(), reason="ffmpeg missing")


@needs_ffmpeg
def test_a_note_for_the_whole_video_has_no_time_and_claude_is_told_so(tmp_path):
    r = make_project.build(cut=True, title="whole note")
    w, n = r["work"], r["name"]
    reviewnotes.add(w, n, "cut", "Be more judicious about killing darlings", 12.0)
    reviewnotes.add(w, n, "cut", "The video is too long", 99.0, whole=True)
    view = views.review(w, n, "cut")
    assert [x["when"] for x in view["notes"]][0] == "Whole video" and view["notes"][0]["whole"] and view["notes"][0]["t"] == 0.0
    assert not view["notes"][1]["whole"]
    prompt = makeversion.brief(w, n, "cut", tmp_path)
    sent = json.loads((tmp_path / "notes.json").read_text(encoding="utf-8"))
    assert {x["note"]: x["time"] for x in sent}["The video is too long"] == "whole video"
    assert "whole video" in prompt and "skip" in prompt


def test_reads_made_for_the_old_recordings_are_marked_to_be_made_again(tmp_path, monkeypatch):
    import server
    import story
    monkeypatch.setattr(server, "takes", type("T", (), {"path": staticmethod(lambda w, n: tmp_path / "t.json")}))
    monkeypatch.setattr(story, "path", lambda w, n: tmp_path / "s.json")
    (tmp_path / "t.json").write_text(json.dumps({"v": 2, "x": 1}), encoding="utf-8")
    (tmp_path / "s.json").write_text(json.dumps({"v": 1, "logline": "kept"}), encoding="utf-8")
    server.mark_reads_stale("w", "n")
    assert json.loads((tmp_path / "t.json").read_text(encoding="utf-8")) == {"v": 0, "x": 1}
    assert json.loads((tmp_path / "s.json").read_text(encoding="utf-8"))["logline"] == "kept"
    assert json.loads((tmp_path / "s.json").read_text(encoding="utf-8"))["v"] == 0


@needs_ffmpeg
def test_claude_can_answer_a_whole_video_note_by_listing_beats_to_take_out(tmp_path):
    r = make_project.build(cut=True, title="whole skip")
    w, n, d = r["work"], r["name"], r["dir"]
    note = reviewnotes.add(w, n, "cut", "Too long, be pickier", 0, whole=True)
    prompt = makeversion.brief(w, n, "cut", tmp_path)
    rows = json.loads((tmp_path / "beats.json").read_text(encoding="utf-8"))
    assert {"id", "seconds", "said", "good", "skipped"} <= set(rows[0]) and "skip_beats" in prompt
    ans = tmp_path / "answer.json"
    ans.write_text(json.dumps({"applied": [{"id": note["id"], "summary": "Took out two weaker clips"}], "skip_beats": ["B02", "nope"]}), encoding="utf-8")
    ok, msg, res = makeversion.apply_answer(w, n, "cut", ans)
    bm = {b["id"]: b for b in json.loads((d / f"{n}.beatmap.json").read_text(encoding="utf-8"))["beats"]}
    assert ok and bm["B02"]["skip"] is True and not bm["B01"].get("skip") and res["changes"] == ["Took out two weaker clips"]


def test_good_parts_times_follow_beats_that_were_taken_out():
    import locks
    from test_locks import beat
    data = {"beats": [beat(1, 0.0, ["First thing we say here."]), beat(2, 3.0, ["Second thing we say here."]), beat(3, 6.0, ["Third thing we say here."])]}
    import beatmap
    beatmap.retime(data["beats"])
    before = {s["beat"]: s["start"] for s in locks.transcript(data)}
    data["beats"][1]["skip"] = True                     # taken out, the old start values left in the file (the plan was not retimed)
    data["beats"][1]["end"] = data["beats"][1]["start"] + data["beats"][1]["dur"]
    after = {s["beat"]: s["start"] for s in locks.transcript(data)}
    assert "B02" not in after and after["B03"] == before["B03"] - data["beats"][1]["dur"]
    beatmap.retime(data["beats"])                       # once retimed the same answer: nothing is counted twice
    assert {s["beat"]: s["start"] for s in locks.transcript(data)} == after
