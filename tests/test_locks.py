import json

import pytest

import beatmap
import clipmap
import config
import cutreview
import locks


def beat(i, start, sents):
    words, t = [], 0.0
    for s in sents:
        for w in s.split():
            words.append([w, t, t + 0.3])
            t += 0.35
    return {"id": f"B{i:02d}", "aroll": {"rel": "Talk_1.mkv", "words": words, "keep": [[0.0, t]], "in": 0.0, "out": t, "dur": t}, "start": start, "dur": t, "said": " ".join(sents),
            "on_screen": {"broll": [{"file": "x/y.mkv", "in": 0, "dur": 2, "at": 0, "auto": True}]}}


@pytest.fixture
def cut():
    wk, name = "zz-locks", "vid"
    d = config.WORK / wk
    d.mkdir(exist_ok=True)
    for f in d.glob("*"):
        if f.is_file():
            f.unlink()
    data = {"beats": [beat(1, 0.0, ["The first thing is screen real estate.", "It matters a lot."]), beat(2, 6.0, ["Then we talk about the console tab here."])]}
    clipmap.write_json(beatmap.path_of(wk, name), data)
    return wk, name, data


def test_transcript_gives_ids_and_places_in_the_cut(cut):
    wk, name, data = cut
    t = locks.transcript(data)
    assert [s["id"] for s in t] == ["B01.1", "B01.2", "B02.1"]
    assert t[0]["start"] == 0.0 and t[1]["start"] > t[0]["end"] - 0.01 and t[2]["start"] >= 6.0


def test_a_mark_is_kept_by_words_and_locks_its_beat(cut):
    wk, name, data = cut
    locks.add(wk, name, data, ["B01.2"], "good")
    assert cutreview.norm("It matters a lot.") in locks.texts(wk, name)
    assert locks.beat_ids(wk, name, data) == {"B01"}
    assert [s["lock"] for s in locks.view(wk, name, data)] == [None, 1, None]
    with pytest.raises(ValueError):
        locks.add(wk, name, data, ["nope"])


def test_unlock_a_sentence_or_the_whole_mark(cut):
    wk, name, data = cut
    locks.add(wk, name, data, ["B01.1", "B01.2"])
    locks.unlock(wk, name, 1, ["B01.1"], data)
    assert locks.texts(wk, name) == {cutreview.norm("It matters a lot.")}
    locks.unlock(wk, name, 1)
    assert locks.load(wk, name) == []


def test_a_locked_sentence_is_not_dropped_and_is_reported(cut):
    wk, name, data = cut
    locks.add(wk, name, data, ["B01.2"])
    drops = [{"text": "It matters a lot.", "kind": "repeat", "why": "said twice"}, {"text": "Then we talk about the console tab here.", "kind": "repeat", "why": "x"}]
    done = cutreview.apply(wk, name, 0.5, 0.05, 0.05, extra=drops)
    assert [d["text"] for d in done] == ["Then we talk about the console tab here."]
    assert [d["text"] for d in cutreview.LOCKED_SKIPPED] == ["It matters a lot."]
    left = clipmap.read_json(beatmap.path_of(wk, name), None)["beats"]
    assert [b["id"] for b in left] == ["B01"] and "matters" in left[0]["said"]


def test_claudes_cut_read_cannot_drop_a_locked_sentence(cut):
    wk, name, data = cut
    locks.add(wk, name, data, ["B01.2"])
    p = config.WORK / wk / "review.json"
    p.write_text(json.dumps({"drops": [{"id": "B01.2", "kind": "repeat"}, {"id": "B02.1", "kind": "repeat"}]}))
    cutreview.apply_review(wk, name, p)
    assert [d["text"] for d in cutreview.load(wk, name)["drops"]] == ["Then we talk about the console tab here."]


def test_the_brief_marks_locked_sentences(cut, tmp_path):
    wk, name, data = cut
    locks.add(wk, name, data, ["B01.2"])
    cutreview.brief(wk, name, tmp_path)
    rows = json.loads((tmp_path / "cut.json").read_text())
    assert [r.get("locked") for r in rows] == [None, True, None]


def test_cutaways_and_framing_leave_a_locked_beat_alone(cut):
    import framing
    import recut
    wk, name, data = cut
    for b in data["beats"]:
        b["on_screen"]["punch"] = [{"x": 1}]
    clipmap.write_json(beatmap.path_of(wk, name), data)
    locks.add(wk, name, data, ["B01.1"])
    (config.WORK / wk / f"{name}.brolllib.json").write_text(json.dumps({"clips": {}}))
    assert recut.audit_cutaways(wk, name) == []
    framing.apply_zoom(wk, name)
    after = clipmap.read_json(beatmap.path_of(wk, name), None)["beats"]
    assert after[0]["on_screen"]["broll"] and after[0]["on_screen"].get("punch") == [{"x": 1}]


def test_marks_are_plan_files():
    import projectstore
    assert projectstore.is_plan("v.locks.json")
