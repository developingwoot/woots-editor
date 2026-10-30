import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import clipmap  # noqa: E402
import shotmatch  # noqa: E402


def span(sid, text, cov=None, dur=10.0):
    return {"id": sid, "text": text, "coverage": cov or {}, "dur": dur, "skip": False, "confidence": 0.3, "restarts": 0, "wpm": 150,
            "slow": 0, "script_lines": [], "flags": [], "start": 0, "end": dur}


SCRIPT = [
    {"id": "S01", "text": "", "said": "Tinkercad is the baseline, it took me under five minutes", "heading": "A", "tokens": []},
    {"id": "S02", "text": "", "said": "Onshape is my daily driver so the sketches were easy", "heading": "B", "tokens": []},
    {"id": "S03", "text": "", "said": "Plasticity is hyped as the CAD for artists", "heading": "C", "tokens": []},
]
for ln in SCRIPT:
    ln["tokens"] = clipmap.tokens_of(ln["said"])


def test_a_take_that_talks_about_the_same_things_stands_in_for_a_line_nobody_read_word_for_word():
    spans = [span("a", "ok so tinkercad was the baseline for this and honestly under five minutes"),
             span("b", "onshape is what i use every day so sketching was easy"),
             span("c", "completely unrelated chatter about my cat")]
    got = clipmap.loose_matches(clipmap.Script(SCRIPT), spans, {"S01", "S02", "S03"})
    assert got["S01"][0][1]["id"] == "a"
    assert got["S02"][0][1]["id"] == "b"
    assert "S03" not in got                                   # nothing talks about Plasticity: no guess


def test_a_take_is_used_for_one_line_only_and_a_take_reading_another_line_is_left_alone():
    spans = [span("a", "tinkercad and onshape both in one take", dur=8),
             span("r", "onshape is my daily driver so the sketches were easy", cov={"S02": 1.0})]
    got = clipmap.loose_matches(clipmap.Script(SCRIPT), spans, {"S01", "S02"})
    used = [sp["id"] for v in got.values() for _, sp in v]
    assert "r" not in used and len(used) == len(set(used))


def test_rank_lines_marks_a_topic_match_as_loose_and_keeps_word_for_word_takes_normal():
    sp_exact = span("x", "plasticity is hyped as the cad for artists", cov={"S03": 1.0})
    sp_loose = span("a", "ok so tinkercad was the baseline for this and honestly under five minutes")
    data = {"clips": [{"rel": "t.mkv", "spans": [sp_exact, sp_loose]}], "by_line": {}}
    clipmap.rank_lines(data, clipmap.Script(SCRIPT))
    assert data["by_line"]["S03"]["picked"] == "x" and not data["by_line"]["S03"].get("loose")
    assert data["by_line"]["S01"]["picked"] == "a" and data["by_line"]["S01"]["loose"]
    assert "not word for word" in data["by_line"]["S01"]["reason"]
    assert data["missing_lines"] == ["S02"]


def test_a_shot_that_names_a_program_only_takes_footage_of_that_program():
    known = shotmatch.programs(["Fusion/a.mp4", "Shapr3D/b.mp4", "Nomad/c.mp4", "Intro_1.mkv", "B Roll/x.mp4"])
    assert known == {"fusion", "shapr3d", "nomad", "broll"}                                    # files at the top level name no program
    assert shotmatch.named_programs("Placing Shapr3D in S-Tier with a crown asset", known) == {"shapr3d"}
    assert shotmatch.named_programs("Placing Onshape and Autodesk Fusion in A-Tier", known) == {"fusion"}
    assert shotmatch.named_programs("B-Roll of dragging blocks together", known) == set()
    assert shotmatch.of_program("Shapr3D/2026-07-23 13-14-53.mp4", {"shapr3d"})
    assert not shotmatch.of_program("Plasticity/2026-07-23 14-42-01.mp4", {"shapr3d"})
    assert shotmatch.of_program("Solidworks login issues.mp4", {"solidworks"})


def test_a_finished_short_is_not_footage_and_user_talking_to_the_camera_is_not_a_cutaway():
    import footage_cfg
    assert footage_cfg.is_ignored({}, "Blender_Short.mp4") and footage_cfg.is_ignored({}, "Tinkercad Short.mp4")
    assert not footage_cfg.is_ignored({}, "Blender.mkv")
    assert footage_cfg.is_ignored({"include": ["Blender_Short.mp4"]}, "Blender_Short.mp4") is False
    assert shotmatch.TO_CAMERA.search("A man with glasses and a beard is speaking to the camera in a workshop.")
    assert not shotmatch.TO_CAMERA.search("A CAD program interface showing a sketch")


def test_a_new_render_does_not_rewrite_an_older_version_kept_as_a_hard_link(tmp_path):
    import os
    import cutview
    cur = tmp_path / "cut.mp4"
    cur.write_bytes(b"first cut")
    old = tmp_path / "cut-v1.mp4"
    os.link(cur, old)
    cutview.free_output(cur)
    cur.write_bytes(b"second cut, written in place like ffmpeg does")
    assert old.read_bytes() == b"first cut"
    cutview.free_output(tmp_path / "nothing-there.mp4")           # nothing to free is fine
