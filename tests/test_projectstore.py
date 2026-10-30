import json

import pytest

import projectstore as ps


@pytest.fixture
def wd(tmp_path):
    return tmp_path


def test_only_plan_files_are_recorded(wd):
    ps.write_json(wd / "v.beatmap.json", {"beats": []}, who="user")
    ps.write_json(wd / "v.edit.json", {"keeps": []}, who="user")             # generated: not versioned
    assert [e["file"] for e in ps.history(wd)] == ["v.beatmap.json"]


def test_a_write_is_recorded_with_who_and_a_summary(wd):
    ps.write_json(wd / "v.beatmap.json", {"beats": [{"id": "B01", "why": "a"}]}, who="claude")
    ps.write_json(wd / "v.beatmap.json", {"beats": [{"id": "B01", "why": "b"}, {"id": "B02", "why": "c"}]}, who="user", why="tweak")
    h = ps.history(wd)
    assert [e["who"] for e in h] == ["user", "claude"]
    assert h[0]["summary"] == "changed B01; added B02" and h[0]["why"] == "tweak"
    assert h[1]["summary"] == "first version"


def test_writing_identical_content_records_nothing(wd):
    ps.write_json(wd / "v.clips.json", {"a": 1})
    ps.write_json(wd / "v.clips.json", {"a": 1})
    assert len(ps.history(wd)) == 1


def test_changes_made_outside_the_app_are_found_by_scan(wd):
    p = wd / "v.script.md"
    p.write_text("S01 one\n", encoding="utf-8")
    first = ps.history(wd)
    assert first[0]["who"] == "before history"                              # it was already there
    p.write_text("S01 one\nS02 two\nS03 three\n", encoding="utf-8")         # e.g. Claude's Edit tool
    h = ps.history(wd)
    assert h[0]["who"] == ps.OUTSIDE and h[0]["summary"] == "2 lines added, 0 removed"


def test_restore_brings_back_an_old_version_and_is_itself_undoable(wd):
    p = wd / "v.script.md"
    ps.write_text(p, "S01 original\n", who="user")
    ps.write_text(p, "S01 changed\n", who="user")
    old = ps.history(wd)[1]
    ps.restore(wd, old["id"], who="user")
    assert p.read_text(encoding="utf-8") == "S01 original\n"
    h = ps.history(wd)
    assert len(h) == 3 and "restored" in h[0]["why"]
    ps.restore(wd, h[1]["id"], who="user")                                   # undo the undo
    assert p.read_text(encoding="utf-8") == "S01 changed\n"


def test_diff_against_now_lists_ids_and_settings(wd):
    p = wd / "v.graphicsplan.json"
    ps.write_json(p, {"version": 1, "decisions": {"B01": {"style": "depth"}, "B02": {"style": "card"}}})
    v1 = ps.history(wd)[0]
    ps.write_json(p, {"version": 2, "decisions": {"B01": {"style": "kinetic"}, "B03": {"style": "card"}}})
    d = ps.diff(wd, v1["id"])
    assert d["changed"] == ["B01"] and d["added"] == ["B03"] and d["removed"] == ["B02"] and d["fields"] == ["version"]


def test_text_diff_for_the_script(wd):
    p = wd / "v.script.md"
    ps.write_text(p, "S01 hello\nS02 world\n")
    v1 = ps.history(wd)[0]
    ps.write_text(p, "S01 hello\nS02 there\n")
    d = ps.diff(wd, v1["id"])
    assert "-S02 world" in d["text"] and "+S02 there" in d["text"]


def test_markers_report_what_changed_since_the_last_build(wd):
    ps.write_json(wd / "v.beatmap.json", {"beats": []})
    ps.write_text(wd / "v.script.md", "S01 a\n")
    assert ps.changes_since(wd, "v", "build") is None
    ps.mark(wd, "v", "build")
    assert ps.changes_since(wd, "v", "build")["changed"] == []
    ps.write_text(wd / "v.script.md", "S01 b\n")
    ps.write_json(wd / "v.clips.json", {"x": 1})
    c = ps.changes_since(wd, "v", "build")
    assert c["changed"] == ["v.script.md"] and c["added"] == ["v.clips.json"]
    ps.mark(wd, "v", "build")                                               # a new build starts from here
    assert ps.changes_since(wd, "v", "build")["changed"] == []


def test_the_manifest_is_not_a_plan_file_and_survives_garbage(wd):
    ps.mark(wd, "v", "final")
    assert ps.history(wd) == []
    (wd / "v.project.json").write_text("not json", encoding="utf-8")
    ps.mark(wd, "v", "final")
    assert "final" in json.loads((wd / "v.project.json").read_text(encoding="utf-8"))["markers"]


def test_a_half_written_journal_line_is_ignored(wd):
    ps.write_json(wd / "v.clips.json", {"a": 1})
    with open(wd / ps.HISTORY / "journal.jsonl", "a", encoding="utf-8") as f:
        f.write('{"id": "broken"')
    assert len(ps.history(wd)) == 1
