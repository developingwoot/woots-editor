import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures"))
import cutview  # noqa: E402
import make_project  # noqa: E402
import makeversion  # noqa: E402
import reviewnotes as rn  # noqa: E402
import teaching  # noqa: E402
import views  # noqa: E402

needs_ffmpeg = pytest.mark.skipif(not make_project.have_ffmpeg(), reason="ffmpeg missing")


def project(title):
    r = make_project.build(cut=True, title=title)
    return r["work"], r["name"], r["dir"]


def beats(d, n):
    return {b["id"]: b for b in json.loads((d / f"{n}.beatmap.json").read_text(encoding="utf-8"))["beats"]}


@needs_ffmpeg
def test_clip_list_and_options_skip_the_take_in_use():
    w, n, d = project("cv options")
    data = cutview.beat_data(w, n)
    assert [c["ref"] for c in cutview.clips_of(data)] == ["B01", "B02", "TP01", "B03"]
    opts = cutview.options(w, n, "B01")
    assert [o["span"] for o in opts] == ["spB"] and opts[0]["why"] == "Reads 100% of the line, 1 restart"
    assert cutview.options(w, n, "B03") == []
    with pytest.raises(ValueError):
        cutview.options(w, n, "nope")


@needs_ffmpeg
def test_one_open_choice_per_clip_and_keep_clears_it():
    w, n, d = project("cv choices")
    cutview.set_choice(w, n, "B01", "remove", "Take this clip out", 0)
    cutview.set_choice(w, n, "B01", "replace", "Use another take", 0, {"span": "spB"})
    open_ = rn.open_notes(w, n, "cut")
    assert [(x["clip"], x["kind"]) for x in open_] == [("B01", "replace")]
    cutview.set_choice(w, n, "B01", "keep", "", 0)
    assert rn.open_notes(w, n, "cut") == []
    with pytest.raises(ValueError):
        cutview.set_choice(w, n, "B01", "explode", "", 0)


@needs_ffmpeg
def test_apply_choices_replace_remove_trim():
    w, n, d = project("cv apply")
    cutview.set_choice(w, n, "B01", "replace", "x", 0, {"span": "spB"})
    cutview.set_choice(w, n, "B03", "remove", "x", 7)
    cutview.set_choice(w, n, "B02", "trim", "x", 3, {"in": 1.0, "out": 2.5})
    r = cutview.apply_choices(w, n)
    assert len(r["applied_ids"]) == 3 and "Swapped the clip at 0:00 for another take" in r["changes"]
    b = beats(d, n)
    assert b["B01"]["aroll"]["span"] == "spB" and b["B01"]["aroll"]["rel"] == "take2.mp4"
    assert b["B03"]["skip"] is True
    assert (b["B02"]["aroll"]["in"], b["B02"]["aroll"]["out"], b["B02"]["dur"]) == (1.0, 2.5, 1.5)
    assert b["B02"]["start"] == b["B01"]["end"]                        # the clips after a trim move up
    clips = json.loads((d / f"{n}.clips.json").read_text(encoding="utf-8"))
    assert clips["by_line"]["S01"]["picked"] == "spB" and clips["by_line"]["S01"]["picked_by"] == "user"
    assert [c["ref"] for c in cutview.clips_of(cutview.beat_data(w, n))] == ["B01", "B02", "TP01"]


@needs_ffmpeg
def test_trim_cannot_leave_the_take_or_go_below_the_minimum():
    w, n, d = project("cv trim bounds")
    cutview.set_choice(w, n, "B01", "trim", "x", 0, {"in": -5, "out": 99})
    cutview.apply_choices(w, n)
    a = beats(d, n)["B01"]["aroll"]
    assert (a["in"], a["out"]) == (0.0, 3.0)
    cutview.set_choice(w, n, "B02", "trim", "x", 3, {"in": 2.9, "out": 2.95})
    cutview.apply_choices(w, n)
    a = beats(d, n)["B02"]["aroll"]
    assert a["out"] - a["in"] >= cutview.TRIM_MIN - 1e-6


@needs_ffmpeg
def test_render_makes_a_cut_with_one_row_per_clip_and_versions_it():
    w, n, d = project("cv render")
    video, rows = cutview.render(w, n)
    assert video.exists() and [r["ref"] for r in rows] == ["B01", "B02", "TP01", "B03"]
    assert rows[1]["start"] == pytest.approx(rows[0]["start"] + rows[0]["dur"], abs=0.2)
    v = makeversion.finish_cut(w, n, video, rows, {})
    assert v["n"] == 1 and v["changes"] == ["The first cut"] and v["clips"][0]["ref"] == "B01"
    view = views.review(w, n, "cut")
    assert view["version"]["label"] == "Cut 1" and view["button"]["label"] == "Make cut 2 from my notes" and view["button"]["enabled"] is False
    assert [t["term"] for t in view["teaching"]] == ["pressure advance"]


def test_first_cut_button_needs_a_plan():
    r = make_project.build(clips=False, title="cv no plan")
    b = views.review(r["work"], r["name"], "cut")["button"]
    assert b["label"] == "Make the rough cut" and b["enabled"] is False and b["detail"] == "There is no plan to cut from yet"


@needs_ffmpeg
def test_button_counts_notes_and_clip_changes():
    w, n, d = project("cv button")
    cutview.set_choice(w, n, "B01", "remove", "Take this clip out", 0)
    rn.add(w, n, "cut", "the shirt changes", 4)
    rn.add(w, n, "cut", "again", 5)
    b = views.review(w, n, "cut")["button"]
    assert b["label"] == "Make the rough cut" and b["enabled"] is True            # no version yet: the first cut
    makeversion.finish_cut(w, n, d / "footage" / "take1.mp4", [{"start": 0, "dur": 3, "ref": "B01"}], {})
    b = views.review(w, n, "cut")["button"]
    assert b["detail"] == "2 notes, 1 clip change" and b["enabled"] is True


@needs_ffmpeg
def test_teaching_moments_seed_once_answer_and_find_more(tmp_path):
    w, n, d = project("cv teaching")
    assert len(teaching.seed(w, n)) == 1 and len(teaching.seed(w, n)) == 1
    teaching.set_status(w, n, "m1", "yes")
    assert [m["term"] for m in teaching.accepted(w, n)] == ["pressure advance"]
    with pytest.raises(ValueError):
        teaching.set_status(w, n, "m1", "maybe")
    p = tmp_path / "teaching.json"
    p.write_text(json.dumps({"moments": [{"beat": "B02", "term": "retraction", "why": "newcomers do not know it"}, {"beat": "ZZ", "term": "bad"}]}),
                 encoding="utf-8")
    ok, msg = teaching.import_found(w, n, p)                                     # B02 is seconds from the teaching voice-over: too close (teaching_gap_s 60)
    assert not ok and msg == "Claude found nothing to add."
    import os
    import skillrules
    mine = Path(os.environ["WOOTS_SKILLS_DIR"]) / "youtube-graphics" / "graphics.json"
    mine.parent.mkdir(parents=True, exist_ok=True)
    mine.write_text(json.dumps({"teaching_gap_s": 1}), encoding="utf-8")         # the host's own copy of the skill wins
    try:
        assert skillrules.graphics()["teaching_gap_s"] == 1.0 and skillrules.graphics()["moment_gap_s"] == 4.0
        assert "at least 1 seconds apart" in teaching.find_prompt(w, n, tmp_path / "fd")
        ok, msg = teaching.import_found(w, n, p)
        assert ok and msg == "Claude found 1 more teaching moment." and [m["term"] for m in teaching.load(w, n)] == ["pressure advance", "retraction"]
    finally:
        mine.unlink()


@needs_ffmpeg
def test_search_all_footage_prompt_and_import(tmp_path):
    w, n, d = project("cv search")
    cfg = json.loads((d / f"{n}.footage.json").read_text(encoding="utf-8"))
    cfg["analysis"] = {"take2.mp4": {"list": [["the", 0.0, 0.2], ["end", 0.3, 0.6], ["comes", 4.0, 4.3], ["now", 4.4, 4.7]]}}
    (d / f"{n}.footage.json").write_text(json.dumps(cfg), encoding="utf-8")
    assert [c["text"] for c in cutview.transcript_chunks(w, n)] == ["the end", "comes now"]
    prompt = cutview.search_prompt(w, n, "B03", tmp_path / "fd")
    assert "options.json" in prompt and (tmp_path / "fd" / "transcripts.json").exists()
    p = tmp_path / "options.json"
    p.write_text(json.dumps({"options": [{"rel": "take2.mp4", "start": 0.0, "end": 0.6, "why": "x"},          # too short
                                         {"rel": "nope.mp4", "start": 0, "end": 3},                          # not a recording
                                         {"rel": "take2.mp4", "start": 0.0, "end": 2.0, "why": "He says it again"}]}), encoding="utf-8")
    ok, msg = cutview.import_found(w, n, "B03", p)
    assert ok and msg == "Claude found 1 more take."
    opts = cutview.options(w, n, "B03")
    assert len(opts) == 1 and opts[0]["rel"] == "take2.mp4" and opts[0]["said"] == "the end"
    ok, _ = cutview.import_found(w, n, "B03", p)                                    # the same answer again adds nothing
    assert not ok and len(cutview.options(w, n, "B03")) == 1
