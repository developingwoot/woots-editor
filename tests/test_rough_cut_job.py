import json
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools" / "review_app"))
import make_project  # noqa: E402
import reviewnotes  # noqa: E402

pytestmark = pytest.mark.skipif(not make_project.have_ffmpeg(), reason="ffmpeg missing")


@pytest.fixture
def server(monkeypatch, tmp_path):
    monkeypatch.setenv("WOOTS_FAKE_VISION", "1")
    monkeypatch.setenv("WOOTS_FAKE_CLAUDE", str(tmp_path))          # nothing in it: any Claude call would fail the job
    monkeypatch.setenv("WOOTS_MIN_WORDS", "5")                      # the test recordings are three seconds long (the numbers come from the skill otherwise)
    monkeypatch.setenv("WOOTS_MIN_PIECE", "1")
    monkeypatch.setenv("WOOTS_COLD_AFTER", "0")
    import server as s
    return s


def wait(job, seconds=120):
    end = time.time() + seconds
    while not job["done"] and time.time() < end:
        time.sleep(0.2)
    assert job["done"], job["log"]
    return job


def test_make_the_rough_cut_end_to_end(server):
    r = make_project.build_footage("rc job")
    w, n, d = r["work"], r["name"], r["dir"]
    job = wait(server.start_rough_cut(w, n))
    assert job["ok"] is True and "Kept as Cut 1." in job["log"], job["log"]
    vs = reviewnotes.versions(w, n, "cut")
    assert [v["n"] for v in vs] == [1] and [c for c in vs[0]["changes"] if not c.startswith("Not done")][:3] == ["Cut 3 recordings together in outline order", "1 of 2 shots have footage", "1 shot still has nothing"] and vs[0]["changes"][-1].startswith("Rule check")
    skipped = [c for c in vs[0]["changes"] if c.startswith("Not done")]          # the fake Claude has no answers: each Claude step is named as skipped, first in the list
    assert vs[0]["changes"][:len(skipped)] == skipped and any("reading the cut" in c for c in skipped) and all("fake claude has no" in c for c in skipped)
    assert len(vs[0]["clips"]) == 3 and (d / vs[0]["file"]).exists()
    beats = json.loads((d / f"{n}.beatmap.json").read_text(encoding="utf-8"))["beats"]
    assert beats[1]["on_screen"]["broll"][0]["file"] == "B Roll/gears close up.mp4"
    assert (d / f"{n}.clips.json").exists() and (d / f"{n}.shots.json").exists() and (d / f"{n}.brolllib.json").exists()


def test_making_it_again_keeps_a_cut_before_it_and_sams_choice(server):
    import shotmatch
    r = make_project.build_footage("rc again")
    w, n = r["work"], r["name"]
    wait(server.start_rough_cut(w, n))
    key = shotmatch.plan(w, n)[1]["key"]
    shotmatch.choose(w, n, key, 1)
    job = wait(server.start_rough_cut(w, n))
    assert job["ok"] is True and [v["n"] for v in reviewnotes.versions(w, n, "cut")] == [1, 2]
    assert shotmatch.load(w, n)[key]["by"] == "user"


def test_it_refuses_without_a_folder_or_an_outline(server):
    r = make_project.build(clips=False, title="rc refuse")
    import scriptedit
    with pytest.raises(ValueError, match="choose the folder"):
        server.start_rough_cut(r["work"], r["name"])
    r2 = make_project.build_footage("rc no outline")
    scriptedit.script_path(r2["work"], r2["name"]).write_text("x", encoding="utf-8")
    with pytest.raises(ValueError, match="write the outline first"):
        server.start_rough_cut(r2["work"], r2["name"])


def test_a_cold_open_chosen_by_claude_is_put_before_the_intro_and_kept_when_made_again(server, tmp_path, monkeypatch):
    import coldopen
    (tmp_path / "hooks.json").write_text(json.dumps({"options": [
        {"title": "Gears", "hook_type": "H1 result first", "question": "Did they last?", "why": "a result", "sentences": ["B02.1", "B03.1"]},
        {"title": "Shirt", "hook_type": "H2", "question": "Why?", "why": "x", "sentences": ["B01.1", "B03.1"]},
        {"title": "Bad", "sentences": ["B99.1"]}]}), encoding="utf-8")
    r = make_project.build_footage("rc cold")
    w, n, d = r["work"], r["name"], r["dir"]
    job = wait(server.start_rough_cut(w, n))
    assert job["ok"] is True, job["log"]
    saved = coldopen.load(w, n)
    assert len(saved["options"]) == 2 and saved["chosen"] == 0 and saved["by"] == "auto"
    beats = json.loads((d / f"{n}.beatmap.json").read_text(encoding="utf-8"))["beats"]
    assert [b["id"] for b in beats[:2]] == ["H01", "H02"] and beats[0]["section"] == "Cold open" and beats[0]["said"] == make_project.SAID[1]
    assert len(reviewnotes.versions(w, n, "cut")[0]["clips"]) == 5
    coldopen.choose(w, n, 1)
    wait(server.start_rough_cut(w, n))
    beats = json.loads((d / f"{n}.beatmap.json").read_text(encoding="utf-8"))["beats"]
    assert beats[0]["said"] == make_project.SAID[0] and [b["id"] for b in beats[:2]] == ["H01", "H02"] and len([b for b in beats if b["id"].startswith("H")]) == 2


def test_a_sentence_claude_finds_contradicting_is_taken_out_of_the_cut_and_stays_out_when_made_again(server, tmp_path):
    import cutreview
    (tmp_path / "review.json").write_text(json.dumps({"drops": [{"id": "B02.1", "kind": "repeat", "why": "said twice"}, {"id": "B99.1", "kind": "repeat"}],
                                                      "suggestions": [{"ids": ["B03.1"], "before": "B01.1", "why": "explains the test"}]}), encoding="utf-8")
    r = make_project.build_footage("rc review")
    w, n, d = r["work"], r["name"], r["dir"]
    job = wait(server.start_rough_cut(w, n))
    assert job["ok"] is True, job["log"]
    saved = cutreview.load(w, n)
    assert len(saved["drops"]) == 1 and saved["drops"][0]["text"].startswith("then the gears") and len(saved["suggestions"]) == 1
    beats = json.loads((d / f"{n}.beatmap.json").read_text(encoding="utf-8"))["beats"]
    assert not any("gears kept breaking" in b["said"] for b in beats) and len(beats) == 2
    ch = reviewnotes.versions(w, n, "cut")[0]["changes"]
    assert any(c.startswith("Took out (repeat)") for c in ch) and any(c.startswith("Suggestion, not done") for c in ch)
    wait(server.start_rough_cut(w, n))
    beats = json.loads((d / f"{n}.beatmap.json").read_text(encoding="utf-8"))["beats"]
    assert not any("gears kept breaking" in b["said"] for b in beats)


def test_the_other_take_of_a_passage_is_left_out_and_reported(server, tmp_path):
    import takes
    (tmp_path / "takes.json").write_text(json.dumps({"groups": [{"topic": "the gears", "takes": [["B01.1"], ["B02.1"]], "best": 0, "why": "first is complete"}]}), encoding="utf-8")
    r = make_project.build_footage("rc takes")
    w, n, d = r["work"], r["name"], r["dir"]
    job = wait(server.start_rough_cut(w, n))
    assert job["ok"] is True, job["log"]
    assert len(takes.load(w, n)["groups"]) == 1
    beats = json.loads((d / f"{n}.beatmap.json").read_text(encoding="utf-8"))["beats"]
    assert not any("gears kept breaking" in b["said"] for b in beats)
    ch = reviewnotes.versions(w, n, "cut")[0]["changes"]
    assert any(c.startswith("Said more than once: \"the gears\"") for c in ch)


def test_the_story_step_runs_once_and_is_named_when_it_fails(server, tmp_path):
    import os
    import story
    r = make_project.build_footage("rc story")
    w, n = r["work"], r["name"]
    job = wait(server.start_rough_cut(w, n))
    changes = reviewnotes.versions(w, n, "cut")[0]["changes"]
    assert any(c.startswith("Not done: finding the story") for c in changes) and story.load(w, n) == {}
    (tmp_path / "story.json").write_text(json.dumps({"logline": "A test", "question": "Does it work?"}), encoding="utf-8")
    job = wait(server.start_rough_cut(w, n))
    assert story.load(w, n)["question"] == "Does it work?"
    changes = reviewnotes.versions(w, n, "cut")[-1]["changes"]
    assert not any(c.startswith("Not done: finding the story") for c in changes)
