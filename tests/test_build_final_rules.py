"""Building and the final render have no approval gates (ADR 0003): a beat map / a stitched preview is all they need."""
import json

import beatmap
import builder
import finalrender
import workflow


def video(title):
    r = workflow.create(title)
    return r["work"], r["name"], workflow.WORK / r["work"]


def test_cannot_build_without_a_beat_map_but_needs_no_approval():
    work, name, wd = video("Build Rules")
    ok, why = builder.can_build(work, name)
    assert not ok and "beat map" in why
    (wd / f"{name}.beatmap.json").write_text(json.dumps({"version": 1, "beats": []}), encoding="utf-8")
    assert builder.can_build(work, name) == (True, "")


def test_final_render_needs_only_a_stitched_preview():
    work, name, wd = video("Final Rules")
    st = finalrender.state(work, name)
    assert st["can_render"] is False and "stitch" in st["why_not"].lower()
    (wd / f"{name}.stitch.json").write_text("{}", encoding="utf-8")
    st = finalrender.state(work, name)
    assert st["can_render"] is True and st["why_not"] == ""


def test_beat_map_snapshot_is_taken_at_build_and_diff_shows_later_edits():
    work, name, wd = video("Snapshot Rules")
    beat = {"id": "B01", "why": "a", "start": 0, "end": 5}
    p = wd / f"{name}.beatmap.json"
    p.write_text(json.dumps({"version": 1, "beats": [beat]}), encoding="utf-8")
    assert beatmap.diff_vs_build(work, name, json.loads(p.read_text(encoding="utf-8"))) is None
    beatmap.snapshot_for_build(work, name)
    assert (wd / f"{name}.beatmap.v1.json").exists()
    edited = {"version": 1, "beats": [{**beat, "why": "changed"}, {"id": "B02", "why": "new", "start": 5, "end": 9}]}
    diff = beatmap.diff_vs_build(work, name, edited)
    assert diff["changed"] == ["B01"] and diff["added"] == ["B02"] and diff["removed"] == []


def test_final_render_warns_when_the_plan_changed_after_the_stitch():
    import projectstore
    work, name, wd = video("Final Drift")
    (wd / f"{name}.stitch.json").write_text("{}", encoding="utf-8")
    beatmap.write_json(wd / f"{name}.beatmap.json", {"version": 1, "beats": []})
    projectstore.mark(wd, name, "stitch")
    assert not any("plan changed" in w for w in finalrender.state(work, name)["warnings"])
    beatmap.write_json(wd / f"{name}.beatmap.json", {"version": 1, "beats": [{"id": "B01"}]})
    st = finalrender.state(work, name)
    assert any("plan changed since the preview was stitched" in w and "beatmap.json" in w for w in st["warnings"])
    assert st["can_render"] is True                      # a warning, not a block
