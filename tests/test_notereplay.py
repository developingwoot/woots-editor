"""Notes outlive a rough cut that is made again: each remembers the words it was about, is open again, and moves to where those words play now."""
import json

import beatmap
import makeversion
import notereplay
import reviewnotes
import workflow


def _beat(bid, a, z, text):
    words = [[w, a + i * 1.0, a + i * 1.0 + 0.5] for i, w in enumerate(text.split())]
    return {"id": bid, "said": text, "dur": z - a, "skip": False, "aroll": {"rel": "talk.mkv", "in": a, "out": z, "keep": [[a, z]], "words": words}, "on_screen": {"broll": []}}


def _video(title, beats, clips):
    r = workflow.create(title)
    w, n = r["work"], r["name"]
    beatmap.path_of(w, n).write_text(json.dumps({"beats": beats}), encoding="utf-8")
    j = reviewnotes.load(w, n)
    j["versions"]["cut"].append({"n": 1, "file": "x.mp4", "changes": [], "clips": clips})
    reviewnotes.save(w, n, j)
    return w, n


OLD = [_beat("B01", 0.0, 10.0, "welcome to the unboxing of the laser today friends"), _beat("B02", 50.0, 60.0, "we need to grease these two rods before the first job")]
OLD_CLIPS = [{"ref": "B01", "start": 0.0, "dur": 10.0}, {"ref": "B02", "start": 10.0, "dur": 10.0}]


def test_the_anchor_is_what_is_said_around_the_notes_time():
    w, n = _video("nr anchor", OLD, OLD_CLIPS)
    assert notereplay.anchor(w, n, "cut", 13.0) == "we need to grease these two rods"         # 3 s into the second clip, 4 s either side
    assert notereplay.anchor(w, n, "cut", 99.0) == ""


def test_a_cut_made_again_opens_its_notes_again_and_moves_them_to_their_words():
    w, n = _video("nr again", OLD, OLD_CLIPS)
    reviewnotes.add(w, n, "cut", "show the grease tube here", 13.0)
    reviewnotes.add(w, n, "cut", "cut this joke", 2.0, said="a joke that the new cut no longer has")
    reviewnotes.add(w, n, "cut", "tighter overall", 0, whole=True)
    j = reviewnotes.load(w, n)
    for note in j["cut"]:
        note.update(status="done", applied_in=1)
    j["cut"].append({"id": 9, "t": 1.0, "t_end": None, "text": "", "clip": "B01", "kind": "remove", "status": "done", "applied_in": 1, "choice": {}})
    reviewnotes.save(w, n, j)
    assert notereplay.reopen(w, n) == {"again": 3, "choices": 1}
    notes = {x["text"]: x for x in reviewnotes.load(w, n)["cut"]}
    assert notes["show the grease tube here"]["status"] == "open" and notes["show the grease tube here"]["said"].startswith("we need to grease") and notes["show the grease tube here"]["was_in"] == 1
    # the plan is built again: other beat ids, another order, the joke is gone
    new = [_beat("B01", 50.0, 62.0, "okay we need to grease these two rods before the first job runs"), _beat("B02", 0.0, 10.0, "welcome to the unboxing of the laser today friends")]
    beatmap.path_of(w, n).write_text(json.dumps({"beats": new}), encoding="utf-8")
    j = reviewnotes.load(w, n)
    j["versions"]["cut"].append({"n": 2, "file": "y.mp4", "changes": ["Cut 1 recording together"], "clips": [{"ref": "B01", "start": 0.0, "dur": 12.0}, {"ref": "B02", "start": 12.0, "dur": 10.0}]})
    reviewnotes.save(w, n, j)
    got = notereplay.place(w, n)
    assert got == {"placed": 1, "lost": ["cut this joke"]}
    notes = {x["text"]: x for x in reviewnotes.load(w, n)["cut"]}
    assert notes["show the grease tube here"]["t"] == 0.0 and notes["cut this joke"]["lost"] is True and "lost" not in notes["tighter overall"]
    changes = reviewnotes.versions(w, n, "cut")[-1]["changes"]
    assert changes[0].startswith("3 notes from earlier cuts are open again") and "cut this joke" in changes[1] and changes[-1] == "Cut 1 recording together"
    rows = json.loads((_brief(w, n) / "notes.json").read_text(encoding="utf-8"))
    by = {r["note"]: r for r in rows}
    assert by["cut this joke"]["time"] == "not in this cut" and by["show the grease tube here"]["from_an_earlier_cut"] is True and "said_there" in by["show the grease tube here"]
    assert by["tighter overall"]["time"] == "whole video"


def _brief(w, n):
    import config
    fd = config.WORK / w / "v2-run" / "notes"
    assert "from_an_earlier_cut" in makeversion.brief(w, n, "cut", fd)
    return fd


def test_the_first_cut_has_nothing_to_carry():
    r = workflow.create("nr first")
    assert notereplay.reopen(r["work"], r["name"]) == {"again": 0, "choices": 0}
    assert notereplay.place(r["work"], r["name"]) == {"placed": 0, "lost": []}


def test_a_place_is_found_by_the_share_of_its_words():
    beats = [_beat("B01", 0.0, 5.0, "something else entirely"), _beat("B02", 5.0, 10.0, "grease these two rods now")]
    assert notereplay.find("we grease these rods", beats)["id"] == "B02"
    assert notereplay.find("nothing like any of it", beats) is None and notereplay.find("", beats) is None


def test_an_old_note_gets_the_words_of_the_cut_it_was_written_on_not_of_the_latest(tmp_path):
    import config
    import projectstore
    w, n = _video("nr old", OLD, OLD_CLIPS)
    wd = config.WORK / w
    projectstore.write_json(beatmap.path_of(w, n), {"beats": OLD})
    projectstore.mark(wd, n, "cut1")                                                        # cut 1 was made from this plan
    later = [_beat("B01", 300.0, 320.0, "something said much later in a quite different cut of the same video")]
    projectstore.write_json(beatmap.path_of(w, n), {"beats": later})
    j = reviewnotes.load(w, n)
    j["versions"]["cut"] += [{"n": 2, "file": "b.mp4", "changes": ["Took out \"grease these two rods\" at 0:13"], "clips": [{"ref": "B01", "start": 0.0, "dur": 20.0}]},
                             {"n": 3, "file": "c.mp4", "changes": [], "clips": [{"ref": "B01", "start": 0.0, "dur": 20.0}]}]
    j["cut"] = [{"id": 1, "t": 13.0, "t_end": None, "text": "cut 0:13 to 0:14", "clip": None, "kind": "note", "status": "done", "applied_in": 2},
                {"id": 2, "t": 2.0, "t_end": None, "text": "more energy here", "clip": None, "kind": "note", "status": "open", "applied_in": None},
                {"id": 3, "t": 5.0, "t_end": None, "text": "a later note", "clip": None, "kind": "note", "status": "done", "applied_in": 2},
                {"id": 4, "t": 5.0, "t_end": None, "text": "written on the latest", "clip": None, "kind": "note", "status": "open", "applied_in": None}]
    reviewnotes.save(w, n, j)
    assert [notereplay.written_on(x, j["cut"], 3) for x in j["cut"]] == [1, 1, 1, 3]         # note 2 is open but note 3, written after it, went into cut 2
    assert notereplay.reopen(w, n)["again"] == 2
    notes = {x["id"]: x for x in reviewnotes.load(w, n)["cut"]}
    assert notes[1]["said"].startswith("we need to grease") and notes[1]["written_on"] == 1  # cut 1's words at 0:13, not cut 3's
    assert notes[2]["said"].startswith("welcome to the unboxing") and "said much later" in notes[4]["said"]
    fd = tmp_path / "run"
    makeversion.brief(w, n, "cut", fd)
    assert json.loads((fd / "earlier_cuts.json").read_text(encoding="utf-8")) == {"2": ["Took out \"grease these two rods\" at 0:13"]}
    assert [r.get("applied_in_cut") for r in json.loads((fd / "notes.json").read_text(encoding="utf-8"))] == [2, None, 2, None]
