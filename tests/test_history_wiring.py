"""The tools and the server record every plan-file change (ADR 0005)."""
import json

import beatmap
import builder
import clipmap
import projectstore
import scriptedit
import workflow


def video(title):
    r = workflow.create(title)
    return r["work"], r["name"], workflow.WORK / r["work"]


def test_a_tool_write_to_a_plan_file_lands_in_the_history():
    work, name, wd = video("History Wiring")
    beatmap.write_json(wd / f"{name}.beatmap.json", {"version": 1, "beats": [{"id": "B01", "why": "a"}]})
    clipmap.write_json(wd / f"{name}.clips.json", {"spans": []})
    files = {e["file"] for e in projectstore.history(wd)}
    assert {f"{name}.beatmap.json", f"{name}.clips.json"} <= files


def test_generated_files_are_not_versioned():
    work, name, wd = video("Generated Files")
    builder.write_json(wd / f"{name}.sections.status.json", {"sections": []})
    assert all("sections.status" not in e["file"] for e in projectstore.history(wd))


def test_script_edits_are_recorded_with_what_was_done():
    work, name, wd = video("Script History")
    scriptedit._write(work, name, ["S01 hello there", "S02 more words"], "added the first lines")
    e = [x for x in projectstore.history(wd) if x["file"].endswith(".script.md")][0]
    assert e["why"] == "added the first lines" and e["summary"] in ("first version", "2 lines added, 0 removed")


def test_state_reports_what_changed_since_the_stitch_and_final_markers():
    work, name, wd = video("Since Markers")
    beatmap.write_json(wd / f"{name}.beatmap.json", {"version": 1, "beats": []})
    assert workflow.state(work, name)["since"] == {}
    projectstore.mark(wd, name, "stitch")
    beatmap.write_json(wd / f"{name}.beatmap.json", {"version": 1, "beats": [{"id": "B01"}]})
    since = workflow.state(work, name)["since"]
    assert since["stitch"]["changed"] == [f"{name}.beatmap.json"] and "final" not in since


def test_starting_a_build_marks_the_plan(tmp_path):
    work, name, wd = video("Build Marker")
    (wd / f"{name}.beatmap.json").write_text(json.dumps({"version": 1, "beats": []}), encoding="utf-8")
    try:
        builder.start(work, name)                  # may fail later (no sections); the marker is set before that
    except Exception:
        pass
    assert projectstore.changes_since(wd, name, "build") is not None


def test_files_the_app_creates_by_itself_do_not_count_as_changes():
    import gfxplan
    work, name, wd = video("Auto Files")
    beatmap.write_json(wd / f"{name}.beatmap.json", {"version": 1, "beats": [{"id": "B01", "graphic": {"kind": "gears"}, "on_screen": {}}]})
    projectstore.mark(wd, name, "stitch")
    gfxplan.ensure_plan(work, name)                      # created empty by the Dashboard on first look
    gfxplan.ensure_review(work, name)
    assert projectstore.changes_since(wd, name, "stitch") == {"since": projectstore.changes_since(wd, name, "stitch")["since"],
                                                              "changed": [], "added": [], "removed": []}
