import json

import beatmap
import shortsapp
import shortsplan
import workflow

EXPLAINER = {"kind": "gears", "strength": 3}


def video_with_ten_minutes(title):
    r = workflow.create(title)
    wd = workflow.WORK / r["work"]
    spec = []
    for sec in "ABCDE":                                       # five sections of 2 minutes, each with one strong moment
        spec += [(sec, 30, None), (sec, 10, EXPLAINER), (sec, 80, None)]
    beats, t = [], 0.0
    for i, (sec, dur, g) in enumerate(spec, 1):
        beats.append({"id": f"B{i:02d}", "section": sec, "dur": float(dur), "start": t, "end": t + dur, "graphic": g,
                      "on_screen": {"broll": []}, "skip": False, "why": f"why {i}"})
        t += dur
    beatmap.write_json(wd / f"{r['name']}.beatmap.json", {"version": 1, "beats": beats})
    return r["work"], r["name"], wd


def shorts_project(work, name, wd, duration=600):
    tr = wd / "main.transcript.json"
    tr.write_text(json.dumps({"duration": duration, "words": [], "segments": [{"start": 0, "end": 10, "text": "hello there"}]}), encoding="utf-8")
    shortsapp.new_project(work, name, "main.mp4", str(tr), None)


def test_the_page_report_for_a_ten_minute_video_is_three_shorts():
    work, name, wd = video_with_ten_minutes("Shorts Report")
    rec = shortsplan.for_video(work, name)
    assert rec["recommended"] == 3 and rec["strong"] == 5 and rec["has_beatmap"] is True


def test_the_find_prompt_carries_the_count_the_rules_and_the_moments():
    work, name, wd = video_with_ten_minutes("Shorts Prompt")
    shorts_project(work, name, wd)
    t = shortsapp.find_prompt(work, name)                               # default = the recommendation
    assert "exactly 3 shorts" in t and "VISUAL MOMENTS found in the beat map" in t and "[0.0-10.0]" in t
    assert "exactly 5 shorts" in shortsapp.find_prompt(work, name, 5)
    assert "only 5 strong visual moments" not in shortsapp.find_prompt(work, name, 5)
    assert "only 5 strong visual moment" in shortsapp.find_prompt(work, name, 7)


def cand(title, ranges, thought=True):
    c = {"title": title, "hook": title.upper(), "ranges": ranges, "visual": "a graphic", "why": "w"}
    if thought:
        c["thought"] = {"setup": "s", "point": "p", "payoff": "y"}
    return c


def test_claudes_picks_are_checked_against_sams_rules(tmp_path):
    work, name, wd = video_with_ten_minutes("Shorts Import")
    shorts_project(work, name, wd)
    p = tmp_path / "candidates.json"
    p.write_text(json.dumps([
        cand("Good A", [[10, 40]]),
        cand("No thought", [[60, 90]], thought=False),
        cand("Too short", [[100, 105]]),
        cand("Same as A", [[20, 50]]),
        cand("Good B two sections", [[100, 115], [300, 320]]),
        cand("Good C", [[400, 430]]),
    ]), encoding="utf-8")
    added = shortsapp.import_candidates(work, name, p, count=2)
    raw = shortsapp.read_raw(work, name)
    assert added == 2 and [s["title"] for s in raw["shorts"]] == ["Good A", "Good B two sections"]
    assert raw["shorts"][1]["ranges"] == [[100, 115], [300, 320]]            # clips from different parts of the video
    assert raw["shorts"][0]["thought"] == {"setup": "s", "point": "p", "payoff": "y"} and raw["shorts"][0]["visual"] == "a graphic"
    why = " | ".join(raw["last_find"]["skipped"])
    assert "complete thought" in why and "under the 10 s minimum" in why and "Same as A" in why and "more than the 2 asked for" in why
    assert raw["last_find"]["asked"] == 2 and raw["last_find"]["added"] == 2


def test_a_second_request_does_not_repeat_what_exists(tmp_path):
    work, name, wd = video_with_ten_minutes("Shorts Again")
    shorts_project(work, name, wd)
    p = tmp_path / "c.json"
    p.write_text(json.dumps([cand("First", [[10, 40]])]), encoding="utf-8")
    shortsapp.import_candidates(work, name, p, count=1)
    p.write_text(json.dumps([cand("Repeat", [[12, 38]]), cand("New", [[200, 230]])]), encoding="utf-8")
    assert shortsapp.import_candidates(work, name, p, count=2) == 1
    assert [s["title"] for s in shortsapp.read_raw(work, name)["shorts"]] == ["First", "New"]


def test_fifteen_seconds_with_a_complete_thought_is_accepted(tmp_path):
    work, name, wd = video_with_ten_minutes("Shorts Brief")
    shorts_project(work, name, wd)
    p = tmp_path / "c.json"
    p.write_text(json.dumps([cand("Brief", [[50, 65]])]), encoding="utf-8")
    assert shortsapp.import_candidates(work, name, p, count=1) == 1
