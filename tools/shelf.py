"""Taking a video off the home screen: archive it (with the clean-up) or delete it (its work folder goes to the trash).

Archive, from the card's menu:
  - a finished video (a final render, a chosen title and a footage folder): the full "Finish and archive" of the Final screen (archive.py):
    the project is saved next to the footage, the final moves there, the renders and caches are deleted. FINALIZED.json marks it.
  - any other video (an idea that was never recorded, a video put aside): the renders, previews, sound files and caches the app can make again
    are deleted (the same kinds finalize.py deletes); every plan and note stays, and so does any final render. `<name>.archived.json` marks it.
    Unarchive takes the mark off: the renders are made again when they are needed.
Both are listed under "Archived" on the home screen. (`<name>.hidden.json`, from the first version of this, counts as archived.)
Delete: the whole work folder is moved to `EDITOR_DATA/trash/<work>-<date time>/`, never erased: moving it back undoes it, and the host empties
the trash by hand. The footage folder is never touched (it is not in the work folder).
"""
import json
import shutil
import time
from pathlib import Path

import config
import finalize

MARKS = ("archived.json", "hidden.json")


def trash_dir() -> Path:
    return config.EDITOR_DATA / "trash"


def _wd(work: str) -> Path:
    if not work or "/" in work or "\\" in work or ".." in work or work.startswith("."):
        raise ValueError(f"bad name {work!r}")
    d = config.WORK / work
    if not d.is_dir():
        raise ValueError("unknown video")
    return d


def is_archived(work: str, name: str) -> bool:
    d = config.WORK / work
    return any((d / f"{name}.{m}").is_file() for m in MARKS) or (d / "FINALIZED.json").is_file()


def has_renders(work: str) -> bool:
    """Whether the video got as far as a render (a cut, a preview, sections): the delete question then says so and suggests Archive."""
    d = config.WORK / work
    return any(d.glob("*.mp4")) or (d / "sections").is_dir() or (d / "final").is_dir()


def _finals(d: Path) -> list:
    return [f for f in d.glob("*.mp4") if finalize.VER.search(f.name)]


def cleanup(work: str) -> list:
    """What archiving an unfinished video deletes: renders, previews and sound files in the work folder and the cache folders. Never a final render."""
    d = _wd(work)
    keep = {f.name for f in _finals(d)}
    out = []
    for f in d.iterdir():
        if f.name in keep:
            continue
        if f.is_file() and f.suffix.lower() in finalize.BIG_EXT:
            out.append(f)
        elif f.is_dir() and f.name in finalize.DROP_DIRS:
            out.append(f)
    return sorted(out, key=lambda p: p.name)


def _size(n: int) -> str:
    return f"{n / 2**30:.1f} GB" if n >= 2**30 else f"{max(1, round(n / 2**20))} MB" if n else "nothing"


def finish_ready(work: str, name: str) -> tuple:
    """(title, footage folder) when the video can have the full Finish and archive, else (None, None)."""
    import publish
    import shootplan
    d = _wd(work)
    if (d / "FINALIZED.json").exists() or not _finals(d):
        return None, None
    title = publish.load(work, name)["title"]
    folder, _ = shootplan.footage_folder(work, name)
    return (title, folder) if title and folder else (None, None)


def preview(work: str, name: str) -> dict:
    """What Archive would do, in plain words, for the question the card asks before it does it."""
    title, folder = finish_ready(work, name)
    if title:
        import archive
        return {"kind": "finish", **archive.preview(work, name, title, folder)}
    files = cleanup(work)
    n = sum(finalize.size(f) for f in files)
    kept = len(_finals(_wd(work)))
    return {"kind": "shelve", "delete": len(files), "frees": _size(n),
            "keep": "Every outline, note and plan stays" + (", and the final render" if kept else "") + "; Unarchive brings the video back."}


def archive_shelve(work: str, name: str) -> dict:
    """Archive a video that is not finished: delete what the app can make again, then mark it archived."""
    d = _wd(work)
    files = cleanup(work)
    freed = sum(finalize.size(f) for f in files)
    for f in files:
        shutil.rmtree(f, ignore_errors=True) if f.is_dir() else f.unlink(missing_ok=True)
    (d / f"{name}.archived.json").write_text(json.dumps({"date": time.strftime("%Y-%m-%d"), "bytes_freed": freed}), encoding="utf-8")
    return {"bytes_freed": freed}


def unarchive(work: str, name: str) -> None:
    """Back on the home screen. A finished video (FINALIZED.json) stays finished: its final is in the footage folder."""
    d = _wd(work)
    for m in MARKS:
        (d / f"{name}.{m}").unlink(missing_ok=True)


def delete(work: str, name: str) -> dict:
    """Move the video's work folder to the trash. Refused when the folder holds another video too (deleting it would take that one as well)."""
    d = _wd(work)
    names = {p.name[:-len(".workflow.json")] for p in d.glob("*.workflow.json")} | {p.name[:-len(".script.md")] for p in d.glob("*.script.md")}
    if names - {name}:
        raise ValueError("this video's folder holds another video too, so it was not deleted: archive it instead")
    dest = trash_dir() / f"{work}-{time.strftime('%Y%m%d-%H%M%S')}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(d), str(dest))
    return {"trash": str(dest)}
