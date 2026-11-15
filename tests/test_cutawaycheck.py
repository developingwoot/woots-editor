"""Claude looks at each cutaway next to its words; an automatic one that does not fit goes, one the host placed is only reported."""
import json

import beatmap
import cutawaycheck
import workflow


def _plan(title):
    r = workflow.create(title)
    w, n = r["work"], r["name"]
    words = [["we", 1.0, 1.3], ["grease", 4.0, 4.4], ["these", 5.0, 5.3], ["rods", 6.0, 6.4], ["later", 15.0, 15.4]]
    beat = {"id": "B01", "said": "we grease these rods later", "dur": 20.0, "start": 60.0, "skip": False,
            "aroll": {"rel": "talk.mkv", "in": 0.0, "out": 20.0, "keep": [[0.0, 20.0]], "words": words},
            "on_screen": {"broll": [{"file": "a.mkv", "in": 10.0, "dur": 4.0, "at": 3.0, "why": "x", "auto": True},
                                    {"file": "b.mkv", "in": 0.0, "dur": 4.0, "at": 8.0, "why": "A note asked for it"},
                                    {"file": "c.mkv", "in": 0.0, "dur": 4.0, "at": 13.0, "why": "y", "auto": True}]}}
    beatmap.path_of(w, n).write_text(json.dumps({"beats": [beat]}), encoding="utf-8")
    return w, n


def test_each_cutaway_is_listed_with_the_words_under_it_and_where_to_look():
    w, n = _plan("cc items")
    got = cutawaycheck.items(w, n)
    assert [(i["id"], i["file"], i["auto"]) for i in got] == [("C01", "a.mkv", True), ("C02", "b.mkv", False), ("C03", "c.mkv", True)]
    assert got[0]["said"] == "grease these rods" and got[0]["t_cutaway"] == 12.0 and got[0]["t_talking"] == 5.0 and got[0]["at"] == 63.0


def test_an_automatic_cutaway_that_does_not_fit_goes_and_one_the_host_placed_is_reported(tmp_path):
    w, n = _plan("cc apply")
    p = tmp_path / "check.json"
    p.write_text(json.dumps({"cutaways": [{"id": "C01", "verdict": "talking", "why": "The hands are on the rods."},
                                          {"id": "C02", "verdict": "wrong", "why": "It shows the lid."},
                                          {"id": "C03", "verdict": "fits", "why": "Fine."}, {"id": "C09", "verdict": "wrong"}, {"id": "C03", "verdict": "nonsense"}]}), encoding="utf-8")
    ok, msg, lines = cutawaycheck.apply_answer(w, n, p)
    assert ok and "took out 1" in msg
    left = json.loads(beatmap.path_of(w, n).read_text(encoding="utf-8"))["beats"][0]["on_screen"]["broll"]
    assert [x["file"] for x in left] == ["b.mkv", "c.mkv"]
    assert lines == ["Cutaway at 1:03 taken out (you are already showing it yourself): The hands are on the rods.",
                     "Check the cutaway at 1:08, which you placed (it shows something else than what you say): It shows the lid."]


def test_an_answer_that_judges_nothing_changes_nothing(tmp_path):
    w, n = _plan("cc empty")
    p = tmp_path / "check.json"
    p.write_text('{"cutaways": "none"}', encoding="utf-8")
    assert cutawaycheck.apply_answer(w, n, p)[0] is False
    assert len(json.loads(beatmap.path_of(w, n).read_text(encoding="utf-8"))["beats"][0]["on_screen"]["broll"]) == 3


def test_no_footage_folder_means_nothing_to_look_at(tmp_path):
    w, n = _plan("cc nofolder")
    assert cutawaycheck.brief(w, n, tmp_path / "run") == ""
