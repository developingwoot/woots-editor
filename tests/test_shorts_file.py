import json
import shutil
import subprocess

import pytest

import shortsapp
import shortsplan
import shortsview
import shorts
import workflow

needs_ffmpeg = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not installed")


def seg(a, b, text):
    return {"start": a, "end": b, "text": text}


STORY = [seg(0, 6, "Why did my gears keep breaking after only 3 prints?"), seg(6, 14, "I tried thicker walls but that did nothing at all."),
         seg(14, 22, "The problem was the tooth shape, not the material."), seg(22, 30, "So I changed the shape and that's why they last now.")]
DULL = [seg(40, 50, "so yeah anyway um"), seg(50, 62, "that is the next thing on the list I guess"), seg(62, 70, "okay then")]


def test_a_stretch_with_a_question_numbers_a_turn_and_a_payoff_scores_high():
    score, why = shortsplan.window_score(" ".join(s["text"] for s in STORY), 30, STORY[-1]["text"])
    assert score >= 3 and "asks a question" in why and "has a turn" in why and "ends on a payoff" in why
    dull, _ = shortsplan.window_score(" ".join(s["text"] for s in DULL), 30, DULL[-1]["text"])
    assert dull < 3


def test_spoken_moments_find_the_story_and_leave_the_dull_part_and_never_overlap():
    mo = shortsplan.spoken_moments(STORY + DULL)
    assert mo and all(m["start"] >= 0 and m["end"] <= 30.1 for m in mo)
    assert 20 <= mo[0]["dur"] <= 55
    assert all(a["end"] <= b["start"] or a["start"] >= b["end"] for i, a in enumerate(mo) for b in mo[i + 1:])
    assert shortsplan.spoken_moments(DULL) == []


def test_a_video_without_a_beat_map_uses_the_spoken_moments():
    rec = shortsplan.recommend(None, 600, spoken=shortsplan.spoken_moments(STORY))
    assert rec["confidence"] == "medium" and rec["strong"] == 1 and rec["recommended"] == rec["by_length"]
    assert "read what is said" in " ".join(rec["reasons"])
    assert shortsplan.recommend(None, 600)["confidence"] == "low"


def test_the_moments_reach_claude_in_the_find_prompt():
    text = shortsplan.moments_text(shortsplan.spoken_moments(STORY))
    assert "0.0-30.0" in text and "asks a question" in text.lower()


def test_standalone_projects_get_their_own_work_folder_and_a_free_name(tmp_path):
    work, name = shortsapp.standalone_names(tmp_path / "This 3D Printed Thing! (final).mp4")
    assert work == "_shorts-this-3d-printed-thing-final" and name == "this-3d-printed-thing-final"
    (workflow.WORK / work).mkdir(parents=True)
    assert shortsapp.standalone_names(tmp_path / "This 3D Printed Thing! (final).mp4") == (f"_shorts-{name}-2", f"{name}-2")


def make_standalone(tmp_path, stem="Some Video", size="320x180"):
    src = tmp_path / f"{stem}.mp4"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"testsrc=size={size}:rate=15:duration=3", "-f", "lavfi", "-i", "sine=frequency=300:duration=3",
                    "-pix_fmt", "yuv420p", "-shortest", str(src)], check=True)
    work, name = shortsapp.standalone_names(src)
    wd = workflow.WORK / work
    wd.mkdir(parents=True)
    tr = wd / "t.json"
    tr.write_text(json.dumps({"duration": 600, "words": [], "segments": STORY}), encoding="utf-8")
    shortsapp.new_project(work, name, str(src), str(tr), None)
    return work, name


@needs_ffmpeg
def test_the_area_lists_a_standalone_project_and_its_screen_uses_the_files_own_words(tmp_path):
    work, name = make_standalone(tmp_path, "Area Standalone")
    items = [i for i in shortsview.area()["items"] if i["key"] == f"{work}~{name}"]
    assert items and items[0]["standalone"] and items[0]["title"] == "Area Standalone" and items[0]["button"] == "Open the shorts"
    d = shortsview.project(work, name)
    assert d["has_project"] and d["title"] == "Area Standalone"
    assert "complete little stories" in d["recommendation"]["sentence"]
    assert d["note"] == "The video is 180p, so close crops look soft."


@needs_ffmpeg
def test_a_full_hd_video_gets_no_softness_note(tmp_path):
    work, name = make_standalone(tmp_path, "Sharp One", size="1920x1080")
    assert "note" not in shortsview.project(work, name)


def test_a_frame_with_no_face_that_looks_nothing_like_the_speaker_set_is_broll():
    import numpy as np
    blue = np.zeros((360, 640, 3), np.uint8)
    blue[:] = (150, 80, 20)
    blue2 = blue.copy()
    blue2[100:200, 100:200] = (160, 90, 30)
    orange = np.zeros((360, 640, 3), np.uint8)
    orange[:] = (30, 120, 230)
    orange[:, 300:] = (200, 200, 200)
    set_hist = [shorts.frame_hist(blue)]
    assert shorts.looks_like_broll(shorts.frame_hist(orange), set_hist, 0.5) is True
    assert shorts.looks_like_broll(shorts.frame_hist(blue2), set_hist, 0.5) is False
    assert shorts.looks_like_broll(shorts.frame_hist(orange), [], 0.5) is False
