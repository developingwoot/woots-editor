"""The sound effects a short uses: a kit of roles -> files, and where each effect goes.

  kit()                            -> {role: [file, ...]} from the SFX folder (guessed from the file names) with the user's changes on top
  save_kit({role: [name, ...]})    -> keeps the user's choice in <state>/sfx_kit.json (names relative to the SFX folder); [] switches a role off
  place(events, kit, total_s)      -> [{"t", "role", "file"}] for the events a short has, with the rules of the youtube-shorts skill

Events are what the picture does: {"t": seconds, "role": "whoosh" (a cut or a zoom step) | "hit" (a graphic lands) | "riser" (into the last line) |
"ding" (a number) | "pop" (a word that stands out), "first": the event sits on the first word after a cut}.
Rules (numbers in the skill): at least `sfx_gap_s` between two sounds, at most `sfx_max_per_10s` in any ten seconds, nothing on the first word after a cut;
when there is no room the more important sound wins (hit, riser, ding, pop, whoosh). Levels are the mix's (audiomix.mix scales each one to the speech peak).
"""
import json
import os
import re
from pathlib import Path

import config
import skillrules

ROLES = {"whoosh": ("whoosh", "swoosh", "swish", "swipe", "transition"),
         "pop": ("pop", "click", "blip", "bubble", "tick"),
         "ding": ("ding", "bell", "chime", "ping", "notification"),
         "hit": ("hit", "boom", "impact", "thud", "slam", "punch"),
         "riser": ("riser", "rise", "build up", "buildup", "swell", "sweep")}
PRIORITY = ["hit", "riser", "ding", "pop", "whoosh"]
AUDIO_EXT = {".mp3", ".wav", ".ogg", ".flac", ".m4a", ".aac"}
KIT_FILE = config.EDITOR_DATA / "sfx_kit.json"


def sfx_dir() -> Path:
    return config.SFX_DIR


def files() -> list:
    d = sfx_dir()
    return sorted((f for f in d.rglob("*") if f.is_file() and f.suffix.lower() in AUDIO_EXT), key=lambda f: str(f).lower()) if d.is_dir() else []


def rel(f: Path) -> str:
    return Path(os.path.relpath(f, sfx_dir())).as_posix()


def guess(found: list) -> dict:
    """{role: [files]} from the words in the file names ('Whoosh_03.wav' is a whoosh). A name that fits two roles goes to the first in ROLES order."""
    out = {r: [] for r in ROLES}
    for f in found:
        name = re.sub(r"[^a-z0-9]+", " ", f.stem.lower())
        for role, words in ROLES.items():
            if any(w in name for w in words):
                out[role].append(f)
                break
    return out


def saved() -> dict:
    try:
        data = json.loads(KIT_FILE.read_text(encoding="utf-8"))
        return {k: [str(x) for x in v] for k, v in data.items() if k in ROLES and isinstance(v, list)}
    except (OSError, ValueError, AttributeError):
        return {}


def kit() -> dict:
    found = files()
    out = guess(found)
    by_rel = {rel(f): f for f in found}
    for role, names in saved().items():                          # the user's choice replaces the guess for that role
        out[role] = [by_rel[n] for n in names if n in by_rel]
    return out


def save_kit(choice: dict):
    clean = {k: [str(x) for x in v] for k, v in (choice or {}).items() if k in ROLES and isinstance(v, list)}
    KIT_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = KIT_FILE.with_name(KIT_FILE.name + f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(clean, indent=1), encoding="utf-8")
    config.replace_retry(tmp, KIT_FILE)


def view() -> dict:
    """For the screen: each role with the files it uses and every file there is to choose from."""
    k = kit()
    return {"folder": str(sfx_dir()), "has_folder": sfx_dir().is_dir(), "roles": [{"role": r, "files": [rel(f) for f in k[r]]} for r in PRIORITY], "all": [rel(f) for f in files()]}


def spaced(times: list, gap: float, per_10: int) -> bool:
    """True when sorted times keep `gap` between them and never more than `per_10` fall in ten seconds."""
    t = sorted(times)
    if any(b - a < gap - 1e-9 for a, b in zip(t, t[1:])):
        return False
    return all(sum(1 for y in t[i:] if y - x < 10.0) <= per_10 for i, x in enumerate(t))


def place(events: list, chosen: dict, total_s: float) -> list:
    """The sounds for a list of events, one per event that has a file for its role and fits the rules. `chosen` = {role: [files]}."""
    r = skillrules.shorts()
    used = {role: 0 for role in chosen}
    taken, out = [], []
    ranked = sorted((e for e in events if chosen.get(e["role"]) and not e.get("first") and 0 <= e["t"] < total_s), key=lambda e: (PRIORITY.index(e["role"]), e["t"]))
    for e in ranked:
        if spaced(taken + [e["t"]], r["sfx_gap_s"], r["sfx_max_per_10s"]):
            files_ = chosen[e["role"]]
            out.append({"t": round(e["t"], 3), "role": e["role"], "file": str(files_[used[e["role"]] % len(files_)])})
            used[e["role"]] += 1                                 # the next one of the role: not the same sound every time
            taken.append(e["t"])
    return sorted(out, key=lambda s: s["t"])
