"""Hide and Delete on the home screen (the host: ideas that never get recorded stay on the dashboard)."""
import pytest

import config
import shelf
import views
import workflow


def test_hide_moves_a_video_to_hidden_and_unhide_brings_it_back():
    r = workflow.create("shelf hide me")
    key = views.key_of(r["work"], r["name"])
    shelf.hide(r["work"], r["name"])
    h = views.home()
    assert key in [c["key"] for c in h["hidden"]] and key not in [c["key"] for c in h["videos"]]
    shelf.unhide(r["work"], r["name"])
    assert key in [c["key"] for c in views.home()["videos"]]


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
