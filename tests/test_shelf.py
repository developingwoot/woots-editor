"""Hide and Delete on the home screen (the host: ideas that never get recorded stay on the dashboard)."""
import pytest

import config
import shelf
import views
import workflow


def test_archive_cleans_up_an_unfinished_video_keeps_its_plans_and_any_final_and_unarchive_brings_it_back():
    r = workflow.create("shelf archive me")
    wd = config.WORK / r["work"]
    key = views.key_of(r["work"], r["name"])
    (wd / f"{r['name']}.cut.mp4").write_bytes(b"x" * 1000)
    (wd / "voice.wav").write_bytes(b"x")
    (wd / "cache").mkdir()
    (wd / "cache" / "a.jpg").write_bytes(b"x")
    (wd / "My video v2 (1080p).mp4").write_bytes(b"final")
    (wd / f"{r['name']}.beatmap.json").write_text("{}", encoding="utf-8")
    p = shelf.preview(r["work"], r["name"])
    assert p["kind"] == "shelve" and p["delete"] == 3 and "final render" in p["keep"]
    shelf.archive_shelve(r["work"], r["name"])
    assert sorted(f.name for f in wd.iterdir() if not f.name.startswith(".")) == sorted(["My video v2 (1080p).mp4", f"{r['name']}.beatmap.json", f"{r['name']}.workflow.json", f"{r['name']}.archived.json"])
    h = views.home()
    assert key in [c["key"] for c in h["archived"]] and key not in [c["key"] for c in h["videos"]]
    shelf.unarchive(r["work"], r["name"])
    assert key in [c["key"] for c in views.home()["videos"]]


def test_a_video_hidden_by_the_first_version_counts_as_archived():
    r = workflow.create("shelf old hidden")
    (config.WORK / r["work"] / f"{r['name']}.hidden.json").write_text("{}", encoding="utf-8")
    assert shelf.is_archived(r["work"], r["name"])
    shelf.unarchive(r["work"], r["name"])
    assert not shelf.is_archived(r["work"], r["name"])


def test_a_finished_video_gets_the_full_finish_and_archive(monkeypatch):
    import publish
    import shootplan
    r = workflow.create("shelf finished")
    wd = config.WORK / r["work"]
    assert shelf.finish_ready(r["work"], r["name"]) == (None, None)            # no final yet
    (wd / "Shelf finished v1 (1080p).mp4").write_bytes(b"final")
    publish.set_title(r["work"], r["name"], "Shelf finished")
    monkeypatch.setattr(shootplan, "footage_folder", lambda *_: (wd, "test"))
    assert shelf.finish_ready(r["work"], r["name"]) == ("Shelf finished", wd)
    assert shelf.preview(r["work"], r["name"])["kind"] == "finish"


def test_delete_moves_the_work_folder_to_the_trash_and_never_erases_it():
    r = workflow.create("shelf delete me")
    wd = config.WORK / r["work"]
    (wd / "note.txt").write_text("kept", encoding="utf-8")
    assert shelf.has_renders(r["work"]) is False
    out = shelf.delete(r["work"], r["name"])
    assert not wd.exists() and (config.EDITOR_DATA / "trash") in __import__("pathlib").Path(out["trash"]).parents
    assert (__import__("pathlib").Path(out["trash"]) / "note.txt").read_text(encoding="utf-8") == "kept"


def test_delete_is_refused_when_the_folder_holds_another_video_or_the_name_is_bad():
    r = workflow.create("shelf shared")
    (config.WORK / r["work"] / "other.script.md").write_text("# other", encoding="utf-8")
    with pytest.raises(ValueError):
        shelf.delete(r["work"], r["name"])
    assert (config.WORK / r["work"]).is_dir()
    for bad in ("..", "a/b", ""):
        with pytest.raises(ValueError):
            shelf.delete(bad, "x")


def test_a_video_with_renders_says_so():
    r = workflow.create("shelf rendered")
    (config.WORK / r["work"] / f"{r['name']}.cut.mp4").write_bytes(b"x")
    assert shelf.has_renders(r["work"]) is True
