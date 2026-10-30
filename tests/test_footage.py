import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures"))
import brolllib  # noqa: E402
import clipmap  # noqa: E402
import footageview  # noqa: E402
import make_project  # noqa: E402
import outline  # noqa: E402
import shotmatch  # noqa: E402
import views  # noqa: E402

needs_ffmpeg = pytest.mark.skipif(not make_project.have_ffmpeg(), reason="ffmpeg missing")


@pytest.fixture(autouse=True)
def fake_vision(monkeypatch):
    monkeypatch.setenv("WOOTS_FAKE_VISION", "1")


def project(title):
    r = make_project.build_footage(title)
    return r["work"], r["name"], r["dir"]


SAMPLE = (Path(__file__).resolve().parent / "fixtures" / "outline_sample.md").read_text(encoding="utf-8")


# ----------------------------------------------------------------------------- the outline feeds the old stages
def test_spoken_lines_of_the_sample_get_ids_by_order_and_their_shot_ideas():
    m = outline.parse(SAMPLE)
    lines = outline.speech_lines(m)
    assert len(lines) == 33 and [ln["id"] for ln in lines[:3]] == ["S01", "S02", "S03"] and lines[0]["heading"] == "Intro: The Soldering Test"
    assert [ln["kind"] for ln in lines[:6]] == ["aroll", "aroll", "aroll", "vo", "aroll", "vo"]
    assert lines[0]["visuals"][0].startswith("Fast-paced montage") and lines[3]["visuals"][0].startswith("B-Roll of a cheap iron")
    assert "*" not in lines[3]["said"] and not lines[1]["said"].startswith('"')
    parsed = clipmap.parse_script(SAMPLE)
    assert len(parsed) == 33 and parsed[0]["tokens"][:3] == ["if", "you", "ask"]


def test_old_scripts_keep_their_own_ids():
    old = "## OPEN (0:00 - 0:10)\n\n[VISUAL: a desk]\nS07 Hello there friends.\nS09 Second line here.\n"
    assert [ln["id"] for ln in clipmap.parse_script(old)] == ["S07", "S09"]
    assert [ln["id"] for ln in outline.speech_lines(outline.parse(old))] == ["S07", "S09"]


def test_camera_shots_are_told_from_things_to_show():
    assert all(outline.is_camera(t) for t in ("Cut to A-Roll", "Cut to close-up on camera", "Cut to A-Roll, throwing hands up in disbelief"))
    assert not any(outline.is_camera(t) for t in ("B-Roll of dragging blocks", "Screen recording showing Preferences", "Ultra-fast timelapse of sketching"))


# ----------------------------------------------------------------------------- matching shots
@needs_ffmpeg
def test_shots_are_matched_by_what_the_footage_shows_and_gaps_are_flagged():
    w, n, d = project("ft match")
    brolllib.build(w, None, n)
    p = shotmatch.plan(w, n)
    assert [(s["camera"], s["kind"]) for s in p] == [(True, "aroll"), (False, "vo"), (False, "aroll")]
    r = shotmatch.match(w, n)
    assert r == {"ready": 1, "nothing": 1, "total": 2}
    shots = shotmatch.load(w, n)
    gears = shots[p[1]["key"]]
    assert gears["chosen"]["rel"] == "B Roll/gears close up.mp4" and gears["by"] == "auto" and len(gears["candidates"]) <= shotmatch.TOP
    assert shots[p[2]["key"]]["chosen"] is None
    assert "Part 2: The fix: film or find: a rainbow unicorn dancing" in shotmatch.missing(w, n)


@needs_ffmpeg
def test_sams_choice_is_kept_when_the_outline_is_matched_again():
    w, n, d = project("ft keep")
    brolllib.build(w, None, n)
    shotmatch.match(w, n)
    key = shotmatch.plan(w, n)[1]["key"]
    cands = shotmatch.load(w, n)[key]["candidates"]
    assert len(cands) >= 2
    shotmatch.choose(w, n, key, 1)
    shotmatch.match(w, n)
    e = shotmatch.load(w, n)[key]
    assert e["by"] == "user" and e["chosen"] == cands[1]
    with pytest.raises(ValueError):
        shotmatch.choose(w, n, key, 99)
    with pytest.raises(ValueError):
        shotmatch.choose(w, n, "nope", 0)
    assert shotmatch.choose(w, n, key, None)["chosen"] is None


@needs_ffmpeg
def test_claude_is_only_asked_about_shots_with_two_likely_clips(tmp_path):
    w, n, d = project("ft pick")
    brolllib.build(w, None, n)
    shotmatch.match(w, n)
    key = shotmatch.plan(w, n)[1]["key"]
    e = shotmatch.load(w, n)
    e[key]["candidates"] = [{"rel": "a.mp4", "t": 1.0, "score": 3.0, "what": "gears", "dur": 3}, {"rel": "b.mp4", "t": 2.0, "score": 2.0, "what": "gear box", "dur": 3}]
    shotmatch.save(w, n, e)
    assert [k for k, _ in shotmatch.ambiguous(w, n)] == [key]
    prompt = shotmatch.pick_brief(w, n, tmp_path / "fd")
    rows = json.loads((tmp_path / "fd" / "shots.json").read_text(encoding="utf-8"))
    assert "picks.json" in prompt and rows[0]["clips"][0]["what_it_shows"] == "gears"
    p = tmp_path / "picks.json"
    p.write_text(json.dumps({"picks": [{"key": key, "clip": 1, "why": "x"}, {"key": "zzz", "clip": 0}]}), encoding="utf-8")
    ok, msg = shotmatch.apply_picks(w, n, p)
    assert ok and msg == "Claude chose between clips for 1 shot." and shotmatch.load(w, n)[key]["chosen"]["rel"] == "b.mp4" and shotmatch.load(w, n)[key]["by"] == "claude"
    assert shotmatch.ambiguous(w, n) == []                                              # asked once


@needs_ffmpeg
def test_the_chosen_clip_goes_under_the_spoken_line_without_touching_a_hand_placed_cutaway():
    w, n, d = project("ft beats")
    clipmap.build(w, n)
    import beatmap
    beatmap.build(w, n)
    brolllib.build(w, None, n)
    shotmatch.match(w, n)
    assert shotmatch.apply_to_beats(w, n) == 1
    beats = json.loads((d / f"{n}.beatmap.json").read_text(encoding="utf-8"))["beats"]
    assert [b["script_lines"] for b in beats] == [["S01"], ["S02"], ["S03"]]
    cut = beats[1]["on_screen"]["broll"][0]
    assert cut["file"] == "B Roll/gears close up.mp4" and cut["at"] == 0.0 and cut["auto"] is True and 0 < cut["dur"] <= beats[1]["dur"]
    assert beats[0]["on_screen"]["broll"] == [] and beats[2]["on_screen"]["broll"] == []
    data = json.loads((d / f"{n}.beatmap.json").read_text(encoding="utf-8"))
    data["beats"][2]["on_screen"]["broll"] = [{"file": "mine.mp4", "in": 0, "dur": 1, "at": 0.5}]
    (d / f"{n}.beatmap.json").write_text(json.dumps(data), encoding="utf-8")
    shotmatch.apply_to_beats(w, n)
    assert json.loads((d / f"{n}.beatmap.json").read_text(encoding="utf-8"))["beats"][2]["on_screen"]["broll"][0]["file"] == "mine.mp4"


# ----------------------------------------------------------------------------- the screen's data
@needs_ffmpeg
def test_recordings_are_listed_with_lengths_status_and_a_cache():
    w, n, d = project("ft rows")
    rec = footageview.recordings(w, n)
    assert (rec["total"], rec["read"], rec["unread"], rec["looked"]) == (5, 3, 0, 0)
    by = {r["ref"]: r for r in rec["rows"]}
    assert by["take1.mp4"]["speech"] == "read" and by["B Roll/gears close up.mp4"]["speech"] == "silent footage" and by["take1.mp4"]["len"] == "0:03"
    assert (d / "v2-durations.json").exists()
    cfg = json.loads((d / f"{n}.footage.json").read_text(encoding="utf-8"))
    del cfg["analysis"]["take2.mp4"]
    (d / f"{n}.footage.json").write_text(json.dumps(cfg), encoding="utf-8")
    rec = footageview.recordings(w, n)
    assert rec["unread"] == 1 and rec["unread_refs"] == ["take2.mp4"] and {r["ref"]: r for r in rec["rows"]}["take2.mp4"]["speech"] == "not read yet"
    assert {r["ref"]: r for r in footageview.recordings(w, n, reading=True)["rows"]}["take2.mp4"]["speech"] == "reading now"
    brolllib.build(w, None, n)
    assert footageview.recordings(w, n)["looked"] == 5


@needs_ffmpeg
def test_footage_view_has_the_button_the_shots_and_plain_text_only():
    w, n, d = project("ft view")
    v = views.footage_view(w, n)
    assert v["folder"]["set"] and v["button"]["label"] == "Make the rough cut" and v["button"]["enabled"] is True
    assert v["button"]["detail"] == "First it looks at what is in the footage, matches your clips to the outline and cuts them together."
    brolllib.build(w, None, n)
    shotmatch.match(w, n)
    v = views.footage_view(w, n)
    items = [it for sec in v["sections"] for it in sec["items"]]
    assert [(it["type"], it["status"]) for it in items] == [("take", "nothing"), ("shot", "ready"), ("take", "nothing"), ("shot", "nothing"), ("take", "nothing")]
    assert v["sections"][0]["section"] == "Intro: The hook" and v["missing"] and v["summary"] == "5 recordings"
    shot = items[1]
    assert shot["chosen"]["frame"].startswith("/api/v2/clipframe?") and shot["candidates"][0]["at"] == "0:01"
    assert views.footage_view(w, n, running=True)["button"]["enabled"] is False


def test_footage_view_explains_what_is_missing_before_the_button_works():
    r = make_project.build(clips=False, title="ft nothing")
    import scriptedit
    scriptedit.script_path(r["work"], r["name"]).unlink()
    v = views.footage_view(r["work"], r["name"])
    assert v["button"]["enabled"] is False and v["button"]["why"] in ("Choose the folder you recorded into first.", "Write the outline first.")
    if make_project.have_ffmpeg():
        w, n, d = project("ft empty folder")
        cfg = json.loads((d / f"{n}.footage.json").read_text(encoding="utf-8"))
        empty = d / "empty"
        empty.mkdir()
        cfg["folder"] = str(empty)
        (d / f"{n}.footage.json").write_text(json.dumps(cfg), encoding="utf-8")
        assert views.footage_view(w, n)["button"]["why"] == "There are no recordings in that folder yet."


# ----------------------------------------------------------------------------- recordings that are not material
def add_finished_video(d, n):
    """The finished video in its own footage folder (finalize puts it there): it says every line of the outline."""
    cfg = json.loads((d / f"{n}.footage.json").read_text(encoding="utf-8"))
    make_project.make_clip(d / "footage" / "Gears that last.mp4", 3, 770)
    words = [[w, round(0.2 + k * 0.1, 2), round(0.2 + k * 0.1 + 0.08, 2)] for k, w in enumerate(" ".join(make_project.SAID).split())]
    cfg["analysis"]["Gears that last.mp4"] = {"dur": 3.0, "words": len(words), "text": "", "first": 0.2, "last": 2.9, "restarts": 0, "restart_at": [], "pauses": 0,
                                              "wpm": 150, "trim": [0, 3], "list": words}
    (d / f"{n}.footage.json").write_text(json.dumps(cfg), encoding="utf-8")


@needs_ffmpeg
def test_the_finished_video_in_the_footage_folder_is_left_out_by_its_title():
    w, n, d = project("ft finished")
    add_finished_video(d, n)
    import footage_cfg
    assert "Gears that last.mp4" in brolllib.clips_of({"folder": str(d / "footage")})                # nothing says it is the finished video yet
    assert footage_cfg.titles_of(w, n)[:2] == ["ft finished", "Gears that last"]
    rec = footageview.recordings(w, n)
    by = {r["ref"]: r for r in rec["rows"]}
    assert by["Gears that last.mp4"]["ignored"] is True and by["Gears that last.mp4"]["auto"] is True and by["take1.mp4"]["ignored"] is False
    assert (rec["total"], rec["ignored"], rec["unread"]) == (5, 1, 0)
    clipmap.build(w, n)
    clips = json.loads((d / f"{n}.clips.json").read_text(encoding="utf-8"))
    assert "Gears that last.mp4" not in [c["rel"] for c in clips["clips"]]
    assert {c["rel"] for c in clips["clips"]} == {"take1.mp4", "take2.mp4", "take3.mp4"}
    brolllib.build(w, None, n)
    lib = json.loads((d / f"{n}.brolllib.json").read_text(encoding="utf-8"))
    assert "Gears that last.mp4" not in lib["clips"] and brolllib.state(w, n)["ready"] is True
    assert views.footage_view(w, n)["summary"] == "5 recordings, 1 left out"


@needs_ffmpeg
def test_user_can_leave_a_recording_out_or_put_the_finished_video_back():
    w, n, d = project("ft toggle")
    add_finished_video(d, n)
    import footage_cfg
    cfg = json.loads((d / f"{n}.footage.json").read_text(encoding="utf-8"))
    cfg["ignore"] = ["take3.mp4"]
    cfg["include"] = ["Gears that last.mp4"]
    full = footage_cfg.with_titles(cfg, w, n)
    assert footage_cfg.is_ignored(full, "take3.mp4") is True and footage_cfg.is_ignored(full, "Gears that last.mp4") is False
    (d / f"{n}.footage.json").write_text(json.dumps(cfg), encoding="utf-8")
    rec = footageview.recordings(w, n)
    assert {r["ref"]: r["ignored"] for r in rec["rows"]}["take3.mp4"] is True and rec["ignored"] == 1 and rec["total"] == 5
    clipmap.build(w, n)
    clips = json.loads((d / f"{n}.clips.json").read_text(encoding="utf-8"))
    assert "take3.mp4" not in [c["rel"] for c in clips["clips"]] and "Gears that last.mp4" in [c["rel"] for c in clips["clips"]]


@needs_ffmpeg
def test_a_tier_shot_gets_the_tier_list_recording_even_when_it_names_a_program():
    w, n, d = project("ft tier")
    make_project.make_clip(d / "footage" / "TierList_1.mp4", 3, 770)
    sp = d / f"{n}.script.md"
    sp.write_text(sp.read_text(encoding="utf-8") + '\n[VISUAL: Placing Gears in A-Tier]\n\nSAM (VO):\n"and gears land in the top tier"\n', encoding="utf-8")
    brolllib.build(w, None, n)
    shotmatch.match(w, n)
    shot = [s for s in shotmatch.plan(w, n) if "Tier" in s["visual"]][0]
    assert shotmatch.load(w, n)[shot["key"]]["chosen"]["rel"] == "TierList_1.mp4"
