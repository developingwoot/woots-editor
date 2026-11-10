r"""Finalize a video: name it after its YouTube title, move it into the footage folder, clear out the work area.

Usage:
    python finalize.py <work_dir> --title "<YouTube title>" [--final "<file.mp4>"] [--project "<footage folder>"] [--yes]

Default is a DRY RUN: it prints what would be moved and deleted, with sizes. Add --yes to do it.
Run only when the full-quality render is the one to keep and the title is locked.

What it does
  1. Picks the final render (--final, else the newest "* vN (1080p).mp4" in the work dir).
  2. Moves it to <project>/<title>.mp4 (project = "folder" in the splice json unless --project), checks the size,
     and refuses to overwrite an existing file.
  3. Moves youtube-metadata.md next to it, renamed <title>.md.
  4. Deletes the big regenerable stuff in the work dir: older vN renders, rendered gfx-*.mp4/.mov, previews,
     proxy, review clips, test wavs, and the cache/parts/frames/check/previews/audio-test/broll-sheets folders.
  5. Keeps every plan/notes json, transcript, srt, md and the final's assembly json (renamed .final.assembly.json),
     so the edit can be re-opened and re-rendered later (graphics re-render from graphics\<video>\...).
  6. Writes <work_dir>/FINALIZED.json (title, final path, date, bytes freed).
"""
import argparse
import json
import re
import shutil
import sys
from datetime import date
from pathlib import Path

BIG_EXT = {".mp4", ".mov", ".mkv", ".wav"}
DROP_DIRS = ["cache", "parts", "frames", "check", "previews", "audio-test", "broll-sheets", "v2-cut", "v2-frames", "v2-run"]
DELIVERABLES = ["youtube-metadata.md"]
VER = re.compile(r" v(\d+) \(1080p\)\.mp4$")


def size(p):
    p = Path(p)
    if p.is_file():
        return p.stat().st_size
    return sum(f.stat().st_size for f in p.rglob("*") if f.is_file())


def gb(n):
    return f"{n / 2**30:.2f} GB"


def safe_name(title):
    return re.sub(r'[\/:*?"<>|]', "", title).strip().rstrip(".")


def plan(work_dir, title: str, final=None, project=None, keep=()) -> dict:
    """What finalizing would do, without doing it. Raises ValueError (a plain sentence) when it cannot be done."""
    work = Path(work_dir)
    name = safe_name(title)
    if final:
        final = work / final if not Path(final).is_absolute() else Path(final)
    else:
        vers = [(int(VER.search(f.name).group(1)), f) for f in work.glob("*.mp4") if VER.search(f.name)]
        if not vers:
            raise ValueError("no final render found: render the final first")
        final = max(vers)[1]
    if not final.is_file():
        raise ValueError(f"final render not found: {final}")

    project = Path(project) if project else None
    if not project:
        for sj in sorted(work.glob("*.splice.json")):
            folder = json.loads(sj.read_text(encoding="utf-8")).get("folder")
            if folder:
                project = Path(folder)
                break
    if not project or not project.is_dir():
        raise ValueError("the footage folder is not set")
    dest = project / f"{name}.mp4"
    if dest.exists():
        raise ValueError(f"refusing to overwrite {dest.name}: it is already in the footage folder")

    final_asm = final.with_suffix(".assembly.json")
    keep = {final.name, final_asm.name, *keep}
    victims = []
    for f in work.iterdir():
        if f.name in keep or f.name == "FINALIZED.json":
            continue
        if f.is_file() and f.suffix.lower() in BIG_EXT:
            victims.append(f)
        elif f.is_file() and f.name.endswith(".assembly.json"):
            victims.append(f)
        elif f.is_dir() and f.name in DROP_DIRS:
            victims.append(f)
    return {"work": work, "name": name, "title": title, "final": final, "final_asm": final_asm, "project": project, "dest": dest,
            "victims": sorted(victims, key=lambda p: -size(p)), "freed": sum(size(v) for v in victims), "final_bytes": size(final),
            "deliverables": [d for d in DELIVERABLES if (work / d).exists()]}


def execute(p: dict) -> dict:
    """Do what plan() described. Deletion is permanent (NAS share, no recycle bin): callers show the plan first."""
    work, name, final, dest = p["work"], p["name"], p["final"], p["dest"]
    want = size(final)
    shutil.move(str(final), str(dest))
    if size(dest) != want:
        raise ValueError(f"size mismatch after the move; stop and check {dest}")
    if p["final_asm"].exists():
        shutil.move(str(p["final_asm"]), str(work / f"{name}.final.assembly.json"))
    for d in p["deliverables"]:
        shutil.move(str(work / d), str(p["project"] / f"{name}.md"))
    for v in p["victims"]:
        shutil.rmtree(v) if v.is_dir() else v.unlink()
    info = {"title": p["title"], "final": str(dest), "date": date.today().isoformat(), "bytes_freed": p["freed"] + want}
    (work / "FINALIZED.json").write_text(json.dumps(info, indent=2), encoding="utf-8")
    return info


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("work_dir")
    ap.add_argument("--title", required=True)
    ap.add_argument("--final")
    ap.add_argument("--project")
    ap.add_argument("--keep", nargs="*", default=[], help="extra file/folder names in the work dir to keep")
    ap.add_argument("--yes", action="store_true")
    a = ap.parse_args()
    try:
        p = plan(a.work_dir, a.title, a.final, a.project, a.keep)
    except ValueError as e:
        sys.exit(str(e))
    print(f"Final render : {p['final'].name} ({gb(p['final_bytes'])})")
    print(f"Moves to     : {p['dest']}")
    for d in p["deliverables"]:
        print(f"Moves        : {d} -> {p['project'] / (p['name'] + '.md')}")
    print(f"Deletes {len(p['victims'])} items, frees {gb(p['freed'])} (the final's move frees another {gb(p['final_bytes'])} of work area):")
    for v in p["victims"]:
        print(f"  {gb(size(v)):>9}  {v.name}{'/' if v.is_dir() else ''}")
    if not a.yes:
        print("\nDRY RUN. Nothing changed. Re-run with --yes to do it.")
        return
    try:
        info = execute(p)
    except ValueError as e:
        sys.exit(str(e))
    print(f"\nDone. {p['dest'].name} is in {p['project']}; freed {gb(info['bytes_freed'])} in the work area.")


if __name__ == "__main__":
    main()
