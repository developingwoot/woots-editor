"""Finish and archive a video (ADR 0007, phase 6): save enough that it can be recreated from the footage, then clean up.

The project bundle is written INTO THE FOOTAGE FOLDER (`<footage>/_woots-project/`), so moving or archiving the footage folder carries
the whole project with it:
  - every plan and note file, the history and the markers (open the bundle in this program with `restore`),
  - the small transcripts and the vision library (the slow-to-make parts), without the sampled frames,
  - a DaVinci Resolve timeline (FCPXML + FCP7 XML) of the finished edit, pointing at the original recordings,
  - the final's chapters, description, publishing details and thumbnail draft, the section edit lists, a README and MANIFEST.json.
Then `finalize` moves the final into the footage folder and deletes the regenerable renders, previews and caches (permanent on the NAS).
Nothing is deleted unless the bundle was written first. `preview()` is the dry run the screen shows before the host confirms.
"""
import json
import shutil
import time
from pathlib import Path

import config
import finalize
import projectstore

WORK = config.WORK
BUNDLE = "_woots-project"
SMALL_EXT = {".json", ".md", ".txt", ".srt", ".html", ".js", ".css", ".svg", ".xml", ".fcpxml", ".npz", ".jpg"}
BIG_FILE = 25 * 2**20                       # a file over 25 MB is a render, not a plan
SKIP_DIRS = {"brolllib", "v2-cut", "v2-frames", "v2-run", "media", "cache", "parts", "frames", "check", "previews", "audio-test", "broll-sheets"}
README = """This folder is the project of "{title}": everything the editing program made or learned, saved next to the footage.

To open it again in Woot's editor: copy this folder's contents into a new work folder (the app's "Open an archived video" does this), or run
    python tools/archive.py restore "<this folder>"
To open the finished edit in DaVinci Resolve: File > Import > Timeline and choose the .fcpxml in the resolve folder (the .xml is a fallback).
The timeline points at the original recordings in this footage folder, so keep them where they are.

Not in here (the program makes them again when needed): the half-size preview and cut videos, rendered graphics, cached audio and frames, and the
sampled frames of the vision library (its descriptions are kept). Graphics are rebuilt from the program's graphics folder, not from here.
Saved {when}.
"""


def _bundle_files(wd: Path) -> list:
    """The files that go into the bundle, as paths relative to the work folder."""
    out = []
    for p in sorted(wd.iterdir()):
        if p.is_file() and p.suffix.lower() in SMALL_EXT and p.stat().st_size <= BIG_FILE and p.name != "FINALIZED.json":
            out.append(p.relative_to(wd))
        elif p.is_dir() and p.name == projectstore.HISTORY:
            out += [f.relative_to(wd) for f in sorted(p.rglob("*")) if f.is_file()]
        elif p.is_dir() and p.name == "brolllib":
            out += [f.relative_to(wd) for f in sorted(p.iterdir()) if f.is_file() and f.suffix in (".json", ".npz")]
        elif p.is_dir() and p.name in ("resolve", "final", "sections"):
            for f in sorted(p.rglob("*")):
                if f.is_file() and f.suffix.lower() in SMALL_EXT and f.stat().st_size <= BIG_FILE and not (set(f.relative_to(wd).parts) & SKIP_DIRS):
                    out.append(f.relative_to(wd))
    return out


def build_bundle(work: str, name: str, project: Path, title: str, resolve: bool = True) -> dict:
    """Write the bundle into the footage folder. Returns {folder, files, resolve: 'ok' | why it was left out}."""
    wd = WORK / work
    note = "left out"
    if resolve:
        try:
            import resolve_export
            resolve_export.export(work, name)
            note = "ok"
        except Exception as e:                  # noqa: BLE001  (a project without a stitched video has no timeline to export: the plans are still saved)
            note = f"no Resolve timeline: {e}"
    dest = Path(project) / BUNDLE
    files = _bundle_files(wd)
    for rel in files:
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(wd / rel, target)
    (dest / "README.txt").write_text(README.format(title=title, when=time.strftime("%Y-%m-%d")), encoding="utf-8")
    (dest / "MANIFEST.json").write_text(json.dumps({"title": title, "work": work, "name": name, "saved": time.strftime("%Y-%m-%dT%H:%M:%S"),
                                                    "files": [f.as_posix() for f in files], "resolve": note}, indent=1), encoding="utf-8")
    return {"folder": str(dest), "files": len(files), "resolve": note}


def restore(bundle, work_root: Path | None = None) -> dict:
    """Open an archived project again: copy the bundle back into a work folder under the work root (never over an existing one)."""
    bundle = Path(bundle)
    try:
        man = json.loads((bundle / "MANIFEST.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise ValueError("this folder is not a saved project") from None
    wd = Path(work_root or WORK) / man["work"]
    if wd.exists() and any(wd.iterdir()):
        raise ValueError("there is already a project with this name; nothing was changed")
    for rel in man["files"]:
        src = bundle / rel
        if src.is_file():
            (wd / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, wd / rel)
    return {"work": man["work"], "name": man["name"], "title": man["title"], "folder": str(wd)}


def _plain_size(n: int) -> str:
    return f"{n / 2**30:.1f} GB" if n >= 2**30 else f"{max(1, round(n / 2**20))} MB"


def preview(work: str, name: str, title: str, project: Path) -> dict:
    """The dry run: what would be kept, moved and deleted, in plain words. Raises ValueError with a plain sentence if it cannot be done."""
    wd = WORK / work
    p = finalize.plan(wd, title, project=project)
    files = _bundle_files(wd)
    renders = [v for v in p["victims"] if v.is_file()]
    caches = [v for v in p["victims"] if v.is_dir()]
    media = wd / "resolve" / "media"
    extra = finalize.size(media) if media.exists() else 0
    delete = []
    if renders:
        delete.append({"what": f"{len(renders)} old renders, previews and sound files", "size": _plain_size(sum(finalize.size(v) for v in renders))})
    if caches:
        delete.append({"what": f"{len(caches)} cache folders (pictures and audio the program can make again)", "size": _plain_size(sum(finalize.size(v) for v in caches))})
    if extra:
        delete.append({"what": "converted copies made for DaVinci Resolve", "size": _plain_size(extra)})
    return {"title": title, "final_to": str(Path(project)), "final_name": p["dest"].name, "final_size": _plain_size(p["final_bytes"]),
            "keep": f"{len(files)} plan, note and history files, saved in the footage folder", "delete": delete,
            "frees": _plain_size(p["freed"] + p["final_bytes"] + extra)}


def run(work: str, name: str, title: str, project: Path) -> dict:
    """Save the bundle, then finalize. Raises before deleting anything if the bundle or the plan fails."""
    wd = WORK / work
    p = finalize.plan(wd, title, project=project)             # validates first: no bundle is written for a move that cannot happen
    b = build_bundle(work, name, project, title)
    media = wd / "resolve" / "media"
    extra = finalize.size(media) if media.exists() else 0
    info = finalize.execute(p)
    if media.exists():
        shutil.rmtree(media, ignore_errors=True)
    return {**info, "bundle": b, "bytes_freed": info["bytes_freed"] + extra}


if __name__ == "__main__":
    import sys
    if len(sys.argv) == 3 and sys.argv[1] == "restore":
        print(json.dumps(restore(sys.argv[2]), indent=1))
    else:
        sys.exit("usage: python archive.py restore <bundle folder>")
