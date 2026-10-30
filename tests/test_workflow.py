import pytest

import workflow


def test_create_makes_a_work_folder_and_state():
    r = workflow.create("Test Video One")
    assert r["work"] == "test-video-one"
    assert (workflow.WORK / r["work"] / f"{r['name']}.workflow.json").exists()


def test_create_rejects_short_titles_and_duplicates():
    with pytest.raises(ValueError):
        workflow.create("ab")
    workflow.create("Duplicate Check")
    with pytest.raises(ValueError):
        workflow.create("Duplicate Check")


def test_unknown_work_folder():
    with pytest.raises(ValueError):
        workflow.work_dir("nope-not-here")


def test_a_new_video_has_every_stage_waiting_and_starts_at_the_script():
    r = workflow.create("Fresh Video")
    st = workflow.state(r["work"], r["name"])
    assert {row["status"] for row in st["stages"]} == {"waiting"}
    assert st["next"]["stage"] == "script"
    assert not any("gate" in row or "blocked_by" in row for row in st["stages"])


def test_a_stage_is_done_when_its_file_exists_and_next_moves_on():
    r = workflow.create("Progress Video")
    (workflow.WORK / r["work"] / f"{r['name']}.script.md").write_text("S01 Hello there", encoding="utf-8")
    st = workflow.state(r["work"], r["name"])
    by = {row["id"]: row["status"] for row in st["stages"]}
    assert by["script"] == "done" and by["clips"] == "waiting"
    assert st["next"]["stage"] == "clips"


def test_editing_a_file_never_changes_a_status():
    """No approvals: nothing goes 'changed' or 'stale' (ADR 0003)."""
    r = workflow.create("Edit Video")
    f = workflow.WORK / r["work"] / f"{r['name']}.script.md"
    f.write_text("S01 One", encoding="utf-8")
    first = workflow.state(r["work"], r["name"])["stages"]
    f.write_text("S01 One S02 Two", encoding="utf-8")
    assert [x["status"] for x in workflow.state(r["work"], r["name"])["stages"]] == [x["status"] for x in first]


def test_old_state_files_with_gates_still_load():
    r = workflow.create("Old Gates Video")
    p = workflow.state_path(r["work"], r["name"])
    old = workflow.read_json(p)
    old["gates"] = {"A": {"approved_on": "2026-10-01T00:00:00", "fp": "sha:x", "upstream": {}}}
    workflow.write_json(p, old)
    assert workflow.state(r["work"], r["name"])["stages"]


def test_final_waits_for_the_stitched_preview():
    r = workflow.create("Final Video")
    wd = workflow.WORK / r["work"]
    by = lambda: {row["id"]: row["status"] for row in workflow.state(r["work"], r["name"])["stages"]}
    assert by()["final"] == "waiting"
    (wd / f"{r['name']}.preview-half.mp4").write_bytes(b"x")
    assert by()["final"] == "ready"


def test_json_roundtrip_and_default(tmp_path):
    p = tmp_path / "x.json"
    assert workflow.read_json(p, {"d": 1}) == {"d": 1}
    workflow.write_json(p, {"a": [1, 2]})
    assert workflow.read_json(p) == {"a": [1, 2]}


def test_set_settings_rejects_unknown_keys():
    r = workflow.create("Settings Check")
    with pytest.raises(ValueError):
        workflow.set_settings(r["work"], r["name"], {"not_a_setting": 1})
