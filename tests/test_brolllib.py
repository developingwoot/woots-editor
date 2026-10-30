import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures"))
import brolllib  # noqa: E402
import cutview  # noqa: E402
import make_project  # noqa: E402
import reviewnotes as rn  # noqa: E402
import views  # noqa: E402

needs_ffmpeg = pytest.mark.skipif(not make_project.have_ffmpeg(), reason="ffmpeg missing")


@pytest.fixture(autouse=True)
def fake_vision(monkeypatch):
    monkeypatch.setenv("WOOTS_FAKE_VISION", "1")


def project(title):
    r = make_project.build(cut=True, title=title)
    return r["work"], r["name"], r["dir"]


def test_sampling_is_coarse_for_a_talking_head_and_capped():
    assert len(brolllib.sample_times(60.0)) == 10
    assert len(brolllib.sample_times(60.0, brolllib.TALK_STEP, brolllib.TALK_CAP)) == 2
    assert len(brolllib.sample_times(100000.0)) == brolllib.CAP
    cfg = {"analysis": {"a.mp4": {"list": [["w", 0, 1]] * 40}}}
    assert brolllib.talking(cfg, "a.mp4", 60.0) is True and brolllib.talking(cfg, "b.mp4", 60.0) is False


def test_the_prompt_uses_the_videos_own_hints():
    import channel
    assert "tools" in brolllib.prompt_for({}) and "a YouTube channel" in brolllib.prompt_for({})
    channel.save({"subjects": "gears, a motor", "topic": "a 3D printing channel"})
    try:
        assert "gears, a motor" in brolllib.prompt_for({}) and "a 3D printing channel" in brolllib.prompt_for({})
    finally:
        channel.save({"subjects": "", "topic": ""})
    assert "a flexi whale shark" in brolllib.prompt_for({"vision_hints": "a flexi whale shark"})


@needs_ffmpeg
def test_every_recording_is_looked_at_not_only_broll_and_is_findable():
    w, n, d = project("bl all footage")
    cfg = json.loads((d / f"{n}.footage.json").read_text(encoding="utf-8"))
    assert brolllib.clips_of(cfg) == ["take1.mp4", "take2.mp4", "take3.mp4"]       # none of these has the B-roll role
    assert brolllib.clips_of(cfg, "broll") == []
    st = brolllib.state(w, n)
    assert (st["total"], st["described"], st["ready"]) == (3, 0, False) and len(st["missing"]) == 3
    brolllib.build(w, 2, n)
    st = brolllib.state(w, n)
    assert st["described"] == 2 and st["ready"] is False and st["missing"] == ["take3.mp4"]
    brolllib.build(w, None, n)                                                      # resumes: only the missing one is done
    assert brolllib.state(w, n)["ready"] is True
    hits = brolllib.search(w, "take2 close up", top=2, name=n)
    assert hits[0]["rel"] == "take2.mp4" and len(hits) == 2 and hits[0]["score"] > hits[1]["score"]
    assert [h["rel"] for h in brolllib.search(w, "take2", name=n, exclude=("take2.mp4",))][0] != "take2.mp4"
    assert brolllib.search(w, "  ", name=n) == []


@needs_ffmpeg
def test_nothing_is_found_before_the_footage_was_looked_at():
    w, n, d = project("bl nothing yet")
    assert brolllib.search(w, "take2", name=n) == []
    assert cutview.options(w, n, "TP01") == []
    assert cutview.vision_status(w, n) == {"ready": False, "described": 0, "total": 3, "missing": 3}


@needs_ffmpeg
def test_a_picture_only_clip_gets_options_from_what_the_footage_shows_and_can_swap():
    w, n, d = project("bl picture options")
    brolllib.build(w, None, n)
    assert cutview.has_take(w, n, "TP01") is False and cutview.has_take(w, n, "B01") is True
    opts = cutview.options(w, n, "TP01")
    assert opts[0]["rel"] == "take2.mp4" and opts[0]["span"].startswith("v|take2.mp4|") and opts[0]["why"].startswith("Looks like")
    assert "take3.mp4" not in [o["rel"] for o in opts]                              # the picture in use is not offered again
    cutview.set_choice(w, n, "TP01", "replace", "x", 5, {"span": opts[0]["span"]})
    r = cutview.apply_choices(w, n)
    assert r["changes"] == ["Swapped the picture at 0:05 for another shot"]
    beat = next(b for b in json.loads((d / f"{n}.beatmap.json").read_text(encoding="utf-8"))["beats"] if b["id"] == "TP01")
    assert beat["on_screen"]["broll"][0]["file"] == "take2.mp4" and beat["vo"]["file"] == "take1.mp4"      # the voice-over stays
    assert r["applied_ids"] == [x["id"] for x in rn.open_notes(w, n, "cut")]     # marked done when the version is kept


def test_the_vision_pipeline_has_a_plain_sentence():
    j = {"pipeline": "vision", "log": "", "done": False, "ok": None, "step": 0, "steps": ["x"], "started": 0}
    assert views.job_sentence(j, now=0)["sentence"] == "Looking at your footage"


def test_query_words_are_folded_and_matched_against_the_file_name_and_description():
    assert brolllib.words_of("Hands holding a broken 3D printed part") == ["hand", "holding", "broken", "3d", "printed", "part"]
    assert brolllib.lexical([], "x.mp4", {}) == 0.0
    sample = {"what": "A hand is adjusting a gear", "subject": "gear mechanism"}
    assert brolllib.lexical(brolllib.words_of("scotch yoke"), "B Roll/Scotch Yoke.MP4", sample) == 1.0          # both words in the file name
    assert brolllib.lexical(brolllib.words_of("hands gears"), "C0091.MP4", sample) == 0.5                        # both only in the description
    assert brolllib.lexical(brolllib.words_of("scotch yoke"), "C0091.MP4", sample) == 0.0


@needs_ffmpeg
def test_a_clip_named_for_the_query_comes_first_even_when_the_images_look_alike():
    w, n, d = project("bl names")
    brolllib.build(w, None, n)
    hits = brolllib.search(w, "take3", top=3, name=n)
    assert hits[0]["rel"] == "take3.mp4" and hits[0]["score"] > hits[1]["score"] and "visual" in hits[0]
