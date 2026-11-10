import json

import beatmap
import clipmap
import config
import coldopen
import cutreview
import locks
import projectstore
import story
from test_takes import OTHER, TAKE1, cut_of


def setup(work):
    (config.WORK / work).mkdir(parents=True, exist_ok=True)
    clipmap.write_json(beatmap.path_of(work, work), cut_of(TAKE1 + OTHER))


def answer(tmp_path, body):
    p = tmp_path / "story.json"
    p.write_text(json.dumps(body), encoding="utf-8")
    return p


def test_a_story_answer_keeps_valid_ids_and_drops_invented_ones(tmp_path):
    setup("zz-story")
    ok, msg = story.apply_answer("zz-story", "zz-story", answer(tmp_path, {
        "logline": "A test", "question": "Does it work?", "answer_at": "B03.1",
        "opening": [{"ids": ["B04.1", "B99.9"], "why": "a result"}, {"ids": ["B77.1"], "why": "invented"}],
        "setback": {"ids": ["B05.1"], "why": "it broke"},
        "keep_moments": [{"ids": ["B06.1"], "kind": "joke", "why": "funny"}, {"ids": ["X1"], "kind": "joke", "why": "none"}],
        "weak": [{"ids": ["B07.1"], "why": "repeats"}], "order": [{"ids": ["B08.1"], "before": "B02.1", "why": "clearer"}, {"ids": ["B08.1"], "before": "NOPE", "why": "bad"}]}))
    s = story.load("zz-story", "zz-story")
    assert ok and s["question"] == "Does it work?" and s["answer_at"] == TAKE1[2]
    assert len(s["opening"]) == 1 and s["opening"][0]["said"] == OTHER[0]
    assert [k["said"] for k in s["keep_moments"]] == [OTHER[2]] and len(s["order"]) == 1
    assert any(f["file"].endswith(".story.json") for f in projectstore.history(config.WORK / "zz-story"))


def test_a_locked_or_kept_sentence_is_never_listed_as_weak(tmp_path):
    setup("zz-story2")
    data = clipmap.read_json(beatmap.path_of("zz-story2", "zz-story2"))
    locks.add("zz-story2", "zz-story2", data, ["B01.1"])
    story.apply_answer("zz-story2", "zz-story2", answer(tmp_path, {"keep_moments": [{"ids": ["B06.1"], "kind": "joke", "why": "x"}],
                                                                  "weak": [{"ids": ["B01.1"], "why": "locked"}, {"ids": ["B06.1"], "why": "kept"}, {"ids": ["B07.1"], "why": "ok"}]}))
    weak = [w["said"] for w in story.load("zz-story2", "zz-story2")["weak"]]
    assert weak == [OTHER[3]]


def test_the_cut_review_does_not_drop_a_story_moment_and_the_cold_open_hears_the_openings(tmp_path):
    setup("zz-story3")
    story.apply_answer("zz-story3", "zz-story3", answer(tmp_path, {"opening": [{"ids": ["B04.1"], "why": "a result"}], "keep_moments": [{"ids": ["B06.1"], "kind": "joke", "why": "x"}]}))
    assert cutreview.norm(OTHER[2]) in cutreview._held("zz-story3", "zz-story3")
    assert OTHER[0] in story.opening_hint("zz-story3", "zz-story3")
    prompt = coldopen.brief("zz-story3", "zz-story3", tmp_path / "fd")
    assert OTHER[0] in prompt and "strong openings" in prompt


def test_suggestions_are_notes_in_the_hosts_words_not_ids(tmp_path):
    setup("zz-story4")
    story.apply_answer("zz-story4", "zz-story4", answer(tmp_path, {"weak": [{"ids": ["B07.1"], "why": "repeats"}], "order": [{"ids": ["B08.1"], "before": "B02.1", "why": "clearer"}]}))
    got = story.suggestions("zz-story4", "zz-story4")
    assert [g["kind"] for g in got] == ["weak", "order"] and OTHER[3] in got[0]["text"] and "B0" not in got[0]["text"] + got[1]["text"]


def test_story_and_cut_review_suggestions_carry_the_time_they_are_said(tmp_path):
    setup("zz-story5")
    data = clipmap.read_json(beatmap.path_of("zz-story5", "zz-story5"))
    for k, b in enumerate(data["beats"]):
        b["start"] = 10.0 * k
    clipmap.write_json(beatmap.path_of("zz-story5", "zz-story5"), data)
    story.apply_answer("zz-story5", "zz-story5", answer(tmp_path, {"weak": [{"ids": ["B07.1"], "why": "repeats"}]}))
    projectstore.write_json(cutreview.path("zz-story5", "zz-story5"), {"v": cutreview.VERSION, "suggestions": [{"text": OTHER[4], "before": TAKE1[0], "why": "clearer"}]})
    got = story.note_suggestions("zz-story5", "zz-story5")
    assert len(got) == 2 and got[0]["t"] == 60.0 and got[1]["t"] == 70.0 and OTHER[4] in got[1]["text"]
