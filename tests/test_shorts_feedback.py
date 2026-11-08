import json

import pytest

import projectstore
import shortsapp
import shortsview
import workflow

WORDS = [{"word": f"w{i}", "start": i * 0.5, "end": i * 0.5 + 0.4} for i in range(60)]


def project(title):
    r = workflow.create(title)
    wd = workflow.WORK / r["work"]
    tr = wd / "t.json"
    tr.write_text(json.dumps({"duration": 100, "words": WORDS, "segments": [{"start": 0, "end": 30, "text": "hello there"}]}), encoding="utf-8")
    shortsapp.new_project(r["work"], r["name"], "main.mp4", str(tr), None)
    raw = shortsapp.read_raw(r["work"], r["name"])
    raw["shorts"] = [{"id": "s1", "title": "Old", "hook": "OLD HOOK", "ranges": [[0, 30]], "status": ""}]
    shortsapp.save_raw(r["work"], r["name"], raw)
    return r["work"], r["name"]


def test_a_note_on_a_short_waits_and_a_general_note_stands():
    work, name = project("Fb Notes")
    shortsapp.add_feedback(work, name, "s1", "  Start on   the number ")
    shortsapp.add_feedback(work, name, "", "Hooks are too long")
    raw = shortsapp.read_raw(work, name)
    assert [(n["text"], n["status"]) for n in raw["shorts"][0]["feedback"]] == [("Start on the number", "open")]
    assert [(n["text"], n["status"]) for n in raw["feedback"]] == [("Hooks are too long", "standing")]
    with pytest.raises(ValueError):
        shortsapp.add_feedback(work, name, "s1", "   ")


def test_notes_can_be_reopened_and_deleted_and_the_empty_list_is_removed():
    work, name = project("Fb Edit")
    shortsapp.add_feedback(work, name, "s1", "one")
    shortsapp.edit_feedback(work, name, "s1", 1, status="done")
    assert shortsapp.feedback_of(shortsapp.read_raw(work, name), "s1")[0]["status"] == "done"
    shortsapp.edit_feedback(work, name, "s1", 1, delete=True)
    assert "feedback" not in shortsapp.read_raw(work, name)["shorts"][0]
    with pytest.raises(ValueError):
        shortsapp.edit_feedback(work, name, "s1", 9, status="open")


def test_the_notes_are_part_of_the_history_so_they_can_be_undone():
    work, name = project("Fb History")
    shortsapp.add_feedback(work, name, "s1", "cut the tangent")
    assert any(e["why"] == "feedback" for e in projectstore.history(shortsapp.wd_of(work), shortsapp.cfg_file(work, name).name))


def test_open_notes_reach_the_prompts_that_choose_tighten_plan_and_title():
    work, name = project("Fb Prompts")
    shortsapp.add_feedback(work, name, "s1", "Start on the number")
    shortsapp.add_feedback(work, name, "", "Hooks are too long")
    assert "Start on the number" in shortsapp.tighten_prompt(work, name, "s1")
    assert "Hooks are too long" in shortsapp.tighten_prompt(work, name, "s1")
    assert "Hooks are too long" in shortsapp.find_prompt(work, name, 2)
    assert "Start on the number" not in shortsapp.find_prompt(work, name, 2)          # a note on one short is not a rule for the next search
    assert "Start on the number" in shortsapp.publish_prompt(work, name, ["s1"])
    assert "Start on the number" in shortsapp.feedback_prompt(work, name, "s1")
    shortsapp.edit_feedback(work, name, "s1", 1, status="done")
    assert "Start on the number" not in shortsapp.tighten_prompt(work, name, "s1")      # applied notes are not asked for again


def test_the_feedback_run_needs_a_note():
    work, name = project("Fb None")
    with pytest.raises(ValueError):
        shortsapp.feedback_prompt(work, name, "s1")


def test_applying_feedback_changes_cuts_hook_and_title_keeps_the_undo_and_marks_notes_done(tmp_path):
    work, name = project("Fb Apply")
    shortsapp.add_feedback(work, name, "s1", "Cut the start and make the hook shorter")
    out = tmp_path / "tighten.json"
    out.write_text(json.dumps({"ranges": [[5, 30]], "drop": [[10, 11.4]], "kept_text": "x", "hook": "short hook", "title": "New title",
                               "note": "Cut the first five seconds.", "unmet": ["Music is yours to change"]}), encoding="utf-8")
    r = shortsapp.apply_feedback(work, name, "s1", out)
    assert r["changed_cuts"] and r["hook"] and r["title"] and r["unmet"] == ["Music is yours to change"]
    s = shortsapp.read_raw(work, name)["shorts"][0]
    assert s["ranges"] == [[5, 30]] and s["drop"] == [[10, 11.4]]
    assert s["hook"] == "SHORT HOOK" and s["title"] == "New title"
    assert s["before_tighten"] == {"ranges": [[0, 30]], "drop": []}
    assert [n["status"] for n in s["feedback"]] == ["done"]
    card = shortsview.feedback_of(s)
    assert card["open"] == 0 and card["result"] == "Cut the first five seconds." and card["unmet"] == ["Music is yours to change"]


def test_feedback_that_leaves_too_little_is_refused_and_the_notes_stay_open(tmp_path):
    work, name = project("Fb Refuse")
    shortsapp.add_feedback(work, name, "s1", "cut everything")
    out = tmp_path / "tighten.json"
    out.write_text(json.dumps({"ranges": [[0, 1]], "drop": []}), encoding="utf-8")
    with pytest.raises(ValueError):
        shortsapp.apply_feedback(work, name, "s1", out)
    s = shortsapp.read_raw(work, name)["shorts"][0]
    assert s["ranges"] == [[0, 30]] and s["feedback"][0]["status"] == "open"


def test_an_answer_that_changes_nothing_is_an_error_not_a_silent_success(tmp_path):
    work, name = project("Fb Nothing")
    shortsapp.add_feedback(work, name, "s1", "add music")
    out = tmp_path / "tighten.json"
    out.write_text(json.dumps({"unmet": ["Music is yours to change"]}), encoding="utf-8")
    with pytest.raises(ValueError, match="Music"):
        shortsapp.apply_feedback(work, name, "s1", out)
    assert shortsapp.read_raw(work, name)["shorts"][0]["feedback"][0]["status"] == "open"


def test_the_feedback_job_runs_the_shorts_model_and_applies_the_answer(tmp_path, monkeypatch):
    import sys
    import time
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools" / "review_app"))
    import server
    work, name = project("Fb Job")
    with pytest.raises(ValueError):
        server.shorts_v2_post("feedback", {"key": f"{work}~{name}", "id": "s1"})          # no note yet
    server.shorts_v2_post("note", {"key": f"{work}~{name}", "id": "s1", "text": "Cut the first five seconds"})
    canned = tmp_path / "canned"
    canned.mkdir()
    (canned / "tighten.json").write_text(json.dumps({"ranges": [[5, 30]], "drop": [], "kept_text": "x", "note": "Cut five seconds."}), encoding="utf-8")
    monkeypatch.setenv("WOOTS_FAKE_CLAUDE", str(canned))
    jid = server.shorts_v2_post("feedback", {"key": f"{work}~{name}", "id": "s1"})["id"]
    job = server._jobs[jid]
    for _ in range(100):
        if job.get("done"):
            break
        time.sleep(0.1)
    assert job["ok"], job["log"]
    s = shortsapp.read_raw(work, name)["shorts"][0]
    assert s["ranges"] == [[5, 30]] and s["feedback"][0]["status"] == "done"
