import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures"))
import make_project  # noqa: E402
import makeversion  # noqa: E402
import projectstore  # noqa: E402
import reviewnotes as rn  # noqa: E402
import views  # noqa: E402
import workflow  # noqa: E402

needs_ffmpeg = pytest.mark.skipif(not make_project.have_ffmpeg(), reason="ffmpeg missing")


def video(title, preview=False):
    r = make_project.build(clips=preview, preview=preview, title=title)
    return r["work"], r["name"], r["dir"]


def test_notes_add_edit_delete_and_are_recorded_in_history():
    w, n, d = video("rn basics")
    a = rn.add(w, n, "preview", "  the shirt   changes ", 42.04, 44.0)
    assert a["text"] == "the shirt changes" and a["t"] == 42.0 and a["t_end"] == 44.0 and a["status"] == "open"
    rn.add(w, n, "preview", "second", 3)
    rn.edit(w, n, "preview", a["id"], "the shirt changes colour")
    assert [x["text"] for x in rn.notes(w, n, "preview")] == ["the shirt changes colour", "second"]
    rn.delete(w, n, "preview", a["id"])
    assert [x["id"] for x in rn.notes(w, n, "preview")] == [2]
    assert any(e["file"].endswith(".notes.json") for e in projectstore.history(d))
    with pytest.raises(ValueError):
        rn.add(w, n, "preview", " ", 1)
    with pytest.raises(ValueError):
        rn.add(w, n, "nonsense", "x", 1)


def test_old_watch_notes_are_read_once():
    w, n, d = video("rn old watch")
    (d / f"{n}.watchnotes.json").write_text(json.dumps({"notes": [{"id": 7, "t": 12.3, "text": "old one", "status": "open"},
                                                                  {"id": 8, "t": 20, "text": "old done", "status": "done"}]}), encoding="utf-8")
    got = rn.notes(w, n, "preview")
    assert [(x["text"], x["status"]) for x in got] == [("old one", "open"), ("old done", "done")]
    rn.add(w, n, "preview", "new", 1)
    (d / f"{n}.watchnotes.json").unlink()
    assert len(rn.notes(w, n, "preview")) == 3                  # read from the new store, not from the old file again


@needs_ffmpeg
def test_baseline_version_and_next_version_mark_notes_done():
    w, n, d = video("rn versions", preview=True)
    makeversion.ensure_baseline(w, n)
    makeversion.ensure_baseline(w, n)                           # twice is still one version
    vs = rn.versions(w, n, "preview")
    assert [v["n"] for v in vs] == [1] and (d / vs[0]["file"]).exists() and len(vs[0]["clips"]) == 3
    note = rn.add(w, n, "preview", "cut this shorter", 4)
    v2 = rn.add_version(w, n, "preview", d / f"{n}.preview-half.mp4", ["Shortened the middle"], vs[0]["clips"], [note["id"]])
    assert v2["n"] == 2
    got = rn.notes(w, n, "preview")[0]
    assert got["status"] == "done" and got["applied_in"] == 2
    assert "preview2" in json.loads((d / f"{n}.project.json").read_text(encoding="utf-8"))["markers"]


def test_apply_answer_rules(tmp_path):
    w, n, d = video("rn answer")
    (d / f"{n}.beatmap.json").write_text(json.dumps({"beats": [{"id": "B01"}]}), encoding="utf-8")
    a = rn.add(w, n, "preview", "move the shirt earlier", 5)
    p = tmp_path / "answer.json"
    p.write_text(json.dumps({"applied": [{"id": 99, "summary": "not mine"}]}), encoding="utf-8")
    assert makeversion.apply_answer(w, n, "preview", p)[0] is False
    p.write_text(json.dumps({"applied": [{"id": a["id"], "summary": "x"}], "beatmap": {"nope": 1}}), encoding="utf-8")
    ok, msg, _ = makeversion.apply_answer(w, n, "preview", p)
    assert not ok and json.loads((d / f"{n}.beatmap.json").read_text(encoding="utf-8")) == {"beats": [{"id": "B01"}]}
    p.write_text(json.dumps({"applied": [{"id": a["id"], "summary": "Moved the shirt earlier"}], "beatmap": {"beats": [{"id": "B02"}]}}), encoding="utf-8")
    ok, msg, res = makeversion.apply_answer(w, n, "preview", p)
    assert ok and res == {"applied_ids": [a["id"]], "changes": ["Moved the shirt earlier"], "lesson": ""}
    assert json.loads((d / f"{n}.beatmap.json").read_text(encoding="utf-8"))["beats"] == [{"id": "B02"}]
    assert any(e["file"].endswith(".beatmap.json") for e in projectstore.history(d))


def test_brief_lists_open_notes_with_readable_times(tmp_path):
    w, n, d = video("rn brief")
    rn.add(w, n, "preview", "too dark", 75, 80)
    done = rn.add(w, n, "preview", "ignore me", 1)
    j = rn.load(w, n)
    j["preview"][1]["status"] = "done"
    rn.save(w, n, j)
    prompt = makeversion.brief(w, n, "preview", tmp_path / "fd")
    notes = json.loads((tmp_path / "fd" / "notes.json").read_text(encoding="utf-8"))
    assert [(x["time"], x["until"], x["note"]) for x in notes] == [("1:15", "1:20", "too dark")] and "answer.json" in prompt and done


@needs_ffmpeg
def test_review_view_has_video_strip_notes_and_button():
    w, n, d = video("rn review", preview=True)
    v = views.review(w, n, "preview")
    assert v["version"]["label"] == "Preview 1" and v["version"]["video"].startswith("/media/")
    assert [round(c["share"], 2) for c in v["clips"]] == [0.33, 0.33, 0.33]
    assert v["button"]["enabled"] is False and v["button"]["detail"] == "Add a note first"
    rn.add(w, n, "preview", "check this", 4)
    rn.add(w, n, "preview", "and this", 6, 7)
    v = views.review(w, n, "preview")
    assert v["button"] == {"label": "Make preview 2 from my notes", "enabled": True, "first": False, "detail": "2 notes", "estimate": "about 6 min"}
    assert [x["when"] for x in v["notes"]] == ["0:04", "0:06–0:07"]
    assert views.review(w, n, "preview", running=True)["button"]["enabled"] is False
    assert views.frame_path(w, v["version"]["video"].rsplit("/", 1)[1], 1.0).stat().st_size > 100
