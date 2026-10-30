"""Shared helpers for <name>.footage.json (the footage library: folder, roles, intro/outro takes).

Pure Python, no heavy imports, so the review app server and assemble.py can both use it.

footage.json:
{
  "folder": "<workspace>\\<video title>",        # where all the footage lives (any depth)
  "roles": {"Intro/take 2.mp4": "intro"},               # per-clip role overrides (relative path, "/" separators)
  "bookends": {"intro": {"file": "Intro/take 2.mp4", "in": 0.4, "out": 21.3},
               "outro": {"file": "...", "in": 0.2, "out": 14.0}},
  "bridge": {"fade": 0.4, "whoosh": true, "whoosh_db": -2, "voice_chain": false},
  "analysis": {"Intro/take 2.mp4": {...}}               # written by the app (transcript of each take)
}
Roles: intro, outro, aroll, broll, unassigned. Without an override the role comes from the file name
(a leading "intro - ", "outro - ", "aroll - ", "broll - " ...), then from the folder names.
"""
import hashlib
import json
import re
from pathlib import Path

ROLES = ("intro", "outro", "aroll", "broll", "unassigned")
VIDEO_EXT = {".mp4", ".mov", ".mkv", ".m4v", ".avi", ".mts", ".webm"}
BRIDGE_DEFAULT = {"fade": 0.4, "whoosh": True, "whoosh_db": -2, "voice_chain": False}

_TOKENS = [("intro", re.compile(r"\bintro\b", re.I)), ("outro", re.compile(r"\boutro\b", re.I)),
           ("aroll", re.compile(r"\ba[ _-]?roll\b", re.I)), ("broll", re.compile(r"\bb[ _-]?roll\b", re.I))]


def auto_role(rel: str) -> str:
    """Role from the name: file name first (a take called 'intro take 2' beats the folder it sits in),
    then folder names, innermost first."""
    parts = rel.replace("\\", "/").split("/")
    name = re.sub(r"\.[^.]+$", "", parts[-1])
    for part in [name] + parts[-2::-1]:
        for role, rx in _TOKENS:
            if rx.search(part.replace("_", " ")):
                return role
    return "unassigned"


def role_of(cfg: dict, rel: str) -> tuple[str, bool]:
    """(role, is_override)."""
    ov = (cfg.get("roles") or {}).get(rel)
    return (ov, True) if ov in ROLES else (auto_role(rel), False)


def norm_name(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(s).lower())


def titles_of(work: str, name: str) -> list:
    """The names the finished video goes by: the workflow title, the outline's Title line, the chosen publishing title."""
    out = []
    try:
        import workflow
        out.append(workflow.load(work, name).get("title"))
    except Exception:                      # noqa: BLE001  (a missing title is only one fewer name to match)
        pass
    wd = Path(__import__("config").WORK) / work
    try:
        m = re.search(r"^Title\s*:\s*(.+)$", (wd / f"{name}.script.md").read_text(encoding="utf-8-sig"), re.M | re.I)
        out.append(m.group(1) if m else None)
    except OSError:
        pass
    try:
        out.append(json.loads((wd / f"{name}.publish.json").read_text(encoding="utf-8-sig")).get("title"))
    except (OSError, ValueError):
        pass
    return [t for t in out if t]


def with_titles(cfg: dict, work: str, name: str) -> dict:
    return {**cfg, "_titles": titles_of(work, name)}


def is_ignored(cfg: dict, rel: str) -> bool:
    """A recording that is not material for this video: one the host turned off, or the finished video itself sitting in its own footage folder
    (finalize puts it there, and it says every line of the outline, so the matcher would choose it for all of them), or a finished Short named "..._Short". `include` overrides."""
    if rel in (cfg.get("include") or []):
        return False
    if rel in (cfg.get("ignore") or []):
        return True
    if re.search(r"[ _-]shorts?$", Path(rel).stem, re.I):          # a finished vertical Short cut from this footage, not footage
        return True
    stem = norm_name(Path(rel).stem)
    return bool(stem) and any(stem == norm_name(t) for t in cfg.get("_titles") or [])


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig")) if path.exists() else {}


def bridge(cfg: dict) -> dict:
    return {**BRIDGE_DEFAULT, **(cfg.get("bridge") or {})}


def resolved_bookends(cfg: dict) -> dict:
    """{'intro': {...abs file, in, out}, 'outro': {...}, 'bridge': {...}} for the chosen takes only.
    Raises ValueError if a chosen file is missing."""
    out = {"bridge": bridge(cfg)}
    folder = Path(cfg.get("folder") or ".")
    for which in ("intro", "outro"):
        b = (cfg.get("bookends") or {}).get(which)
        if not b or not b.get("file"):
            continue
        p = folder / b["file"]
        if not p.exists():
            raise ValueError(f"the chosen {which} take is missing: {p}")
        if not (float(b["out"]) > float(b["in"]) >= 0):
            raise ValueError(f"{which}: trim out must be after in")
        st = p.stat()
        out[which] = {"file": str(p), "rel": b["file"], "in": round(float(b["in"]), 3), "out": round(float(b["out"]), 3),
                      "size": st.st_size, "mtime": int(st.st_mtime)}
    return out


def has_bookends(cfg: dict) -> bool:
    b = cfg.get("bookends") or {}
    return any((b.get(w) or {}).get("file") for w in ("intro", "outro"))


def bookends_hash(rb: dict) -> str:
    """Identity of what assemble.py would build (take file + size/mtime, trim, bridge settings)."""
    key = json.dumps({k: rb.get(k) for k in ("intro", "outro", "bridge")}, sort_keys=True)
    return hashlib.sha1(key.encode()).hexdigest()[:12]
