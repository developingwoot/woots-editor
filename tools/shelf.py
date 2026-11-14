"""Taking a video off the home screen: hide it (nothing changes, it comes back with Unhide) or delete it (its work folder goes to the trash).

Hidden: `<name>.hidden.json` in the work folder ({"date": ...}). The home screen lists it under "Hidden".
Deleted: the whole work folder is moved to `EDITOR_DATA/trash/<work>-<date time>/`, never erased: moving it back undoes it, and the host empties
the trash by hand. The footage folder is never touched (it is not in the work folder).
"""
import json
import shutil
import time
from pathlib import Path

import config


def trash_dir() -> Path:
    return config.EDITOR_DATA / "trash"


def _wd(work: str) -> Path:
    if not work or "/" in work or "\\" in work or ".." in work or work.startswith("."):
        raise ValueError(f"bad name {work!r}")
    d = config.WORK / work
    if not d.is_dir():
        raise ValueError("unknown video")
    return d


def is_hidden(work: str, name: str) -> bool:
    return (config.WORK / work / f"{name}.hidden.json").is_file()


def hide(work: str, name: str) -> None:
    (_wd(work) / f"{name}.hidden.json").write_text(json.dumps({"date": time.strftime("%Y-%m-%d")}), encoding="utf-8")


def unhide(work: str, name: str) -> None:
    (_wd(work) / f"{name}.hidden.json").unlink(missing_ok=True)


def has_renders(work: str) -> bool:
    """Whether the video got as far as a render (a cut, a preview, sections): the delete question then says so and suggests Hide."""
    d = config.WORK / work
    return any(d.glob("*.mp4")) or (d / "sections").is_dir() or (d / "final").is_dir()


def delete(work: str, name: str) -> dict:
    """Move the video's work folder to the trash. Refused when the folder holds another video too (deleting it would take that one as well)."""
    d = _wd(work)
    names = {p.name[:-len(".workflow.json")] for p in d.glob("*.workflow.json")} | {p.name[:-len(".script.md")] for p in d.glob("*.script.md")}
    if names - {name}:
        raise ValueError("this video's folder holds another video too, so it was not deleted: hide it instead")
    dest = trash_dir() / f"{work}-{time.strftime('%Y%m%d-%H%M%S')}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(d), str(dest))
    return {"trash": str(dest)}
