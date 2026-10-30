import json

import pytest

import brolllib
import config
import shotmatch
import tags


@pytest.fixture
def wk(monkeypatch):
    monkeypatch.setattr(tags, "WORK", config.WORK)
    d = config.WORK / "zz-tags"
    d.mkdir(exist_ok=True)
    for f in d.glob("*"):
        if f.is_file():
            f.unlink()
    return "zz-tags", "vid"


def test_a_tag_is_added_edited_and_removed(wk):
    t = tags.add(*wk, "Fluidd/Console_1.mkv", 12, 31.5, "Fluidd dashboard, console tab")
    assert t["id"] == 1 and t["end"] == 31.5
    tags.update(*wk, 1, label="Fluidd console", end=40)
    assert tags.load(*wk)[0]["label"] == "Fluidd console" and tags.load(*wk)[0]["end"] == 40
    tags.delete(*wk, 1)
    assert tags.load(*wk) == []
    assert tags.add(*wk, "a.mkv", 0, 1, "x")["id"] == 2                 # ids are not reused


def test_a_bad_tag_says_what_is_wrong(wk):
    with pytest.raises(ValueError, match="what is on screen"):
        tags.add(*wk, "a.mkv", 0, 5, "  ")
    with pytest.raises(ValueError, match="end must come after"):
        tags.add(*wk, "a.mkv", 5, 5, "x")
    with pytest.raises(ValueError, match="past the end"):
        tags.add(*wk, "a.mkv", 70, 80, "x", length=60)
    assert tags.add(*wk, "a.mkv", 50, 80, "x", length=60)["end"] == 60


def test_tags_are_plan_files_so_changes_are_recorded(wk):
    import projectstore
    assert projectstore.is_plan("x.tags.json")
    tags.add(*wk, "a.mkv", 0, 5, "x")
    assert any(e["file"].endswith(".tags.json") for e in projectstore.history(config.WORK / wk[0]))


def test_narrowest_tag_wins_at_a_moment():
    ts = [{"rel": "a", "start": 0, "end": 60, "label": "wide"}, {"rel": "a", "start": 10, "end": 20, "label": "narrow"}]
    assert tags.at(ts, "a", 15)["label"] == "narrow"
    assert tags.at(ts, "a", 30)["label"] == "wide"
    assert tags.at(ts, "a", 60) is None and tags.at(ts, "b", 5) is None


def test_clips_with_little_data_are_flagged():
    assert tags.thin(None, 100)
    assert tags.thin({"samples": []}, 10)
    assert tags.thin({"error": "x", "samples": [{}, {}]}, 10)
    assert tags.thin({"samples": [{}]}, 60)
    assert not tags.thin({"samples": [{}]}, 8)                          # a short clip described once is fine
    assert not tags.thin({"samples": [{}, {}, {}]}, 60)


def test_a_tag_beats_the_models_description_in_footage_search(wk, monkeypatch):
    import numpy as np
    monkeypatch.setenv("WOOTS_FAKE_VISION", "1")
    d, jp, ep, _ = brolllib.paths(*wk)
    # the model called the Fluidd clip "a printer web page"; the user says it is Fluidd's console
    lib = {"clips": {"Fluidd/Console_1.mkv": {"dur": 60, "samples": [{"t": 6.0, "what": "a printer web page", "subject": "web page", "frame": ""}]},
                     "Mainsail/Dash_1.mkv": {"dur": 60, "samples": [{"t": 6.0, "what": "a printer web page", "subject": "web page", "frame": ""}]}}}
    jp.write_text(json.dumps(lib), encoding="utf-8")
    np.savez(ep, **{"Fluidd/Console_1.mkv|6.0": brolllib.fake_embed("a printer web page"), "Mainsail/Dash_1.mkv|6.0": brolllib.fake_embed("a printer web page")})
    tags.add(*wk, "Fluidd/Console_1.mkv", 0, 30, "fluidd console tab")
    hits = brolllib.search(wk[0], "fluidd console", name=wk[1])
    assert hits[0]["rel"] == "Fluidd/Console_1.mkv" and hits[0]["tagged"] and hits[0]["what"] == "fluidd console tab"
    assert not hits[1]["tagged"] and hits[0]["score"] - hits[1]["score"] > 2


def test_a_tagged_clip_with_no_library_entry_is_still_found(wk):
    tags.add(*wk, "New/Thing_1.mkv", 0, 30, "heated bed leveling screen")
    hits = brolllib.search(wk[0], "bed leveling", name=wk[1])
    assert [h["rel"] for h in hits] == ["New/Thing_1.mkv"] and hits[0]["score"] >= shotmatch.THRESH
    assert brolllib.search(wk[0], "something else entirely", name=wk[1]) == []


def test_a_tag_naming_the_program_lets_a_clip_stand_for_it():
    assert not shotmatch.of_program("Misc/Clip_1.mkv", {"fluidd"})
    assert shotmatch.of_program("Misc/Clip_1.mkv", {"fluidd"}, "Fluidd dashboard")
    ts = [{"rel": "Misc/Clip_1.mkv", "start": 0, "end": 9, "label": "Fluidd dashboard"}]
    assert shotmatch.label_at(ts, "Misc/Clip_1.mkv", 3) == "Fluidd dashboard" and shotmatch.label_at(ts, "Misc/Clip_1.mkv", 20) == ""
