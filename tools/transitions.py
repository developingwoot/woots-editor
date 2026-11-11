"""Transitions: how a cutaway (B-roll, a captured web page) comes in over the host and goes out again, and the sound that goes with it.

The library is `youtube-edit/transitions.json` (the user's copy in ~/.claude/skills wins, like the other skill files):
  {"presets": {id: {"label", "kind": cut|fade|slide|pop|flash, "dur": s, "from": right|left|top|bottom, "sound": a sound-kit role or "none"}},
   "defaults": {"web": id, "broll": id}}
Which preset a cutaway gets: the insert's own "transition" (set on the clip), else Settings ("transition_web" / "transition_broll"), else the library's defaults.
The edit carries the resolved preset on the first and last piece of the cutaway ("t_in" / "t_out"), so sectionrender.py needs nothing else to draw it:
  in_filters(...)  -> the filters on the cutaway's own picture (fades, flash, pop)     overlay_xy(...) -> where it sits (slides)
A transition with a sound puts one effect of its role from the sound kit (sfxkit) just before the move, in the preview and in the final mix.
"""
import json
from pathlib import Path

import config
import skillrules

FILE = "youtube-edit/transitions.json"
KINDS = ("cut", "fade", "slide", "pop", "flash")
SIDES = ("right", "left", "top", "bottom")
CUT = {"id": "cut", "label": "Cut (no transition)", "kind": "cut", "dur": 0.0, "sound": "none"}
BUILTIN = {"cut": CUT, "slide": {"id": "slide", "label": "Slide in from the right, with a whoosh", "kind": "slide", "from": "right", "dur": 0.35, "sound": "whoosh"}}
LEAD_S = 0.12                     # the sound starts this long before the move, so its loudest part lands on it


def _clean(pid: str, p) -> dict | None:
    if not isinstance(p, dict) or p.get("kind") not in KINDS:
        return None
    try:
        dur = min(1.0, max(0.1, float(p.get("dur", 0.3))))
    except (TypeError, ValueError):
        dur = 0.3
    sound = str(p.get("sound") or "none").strip().lower()
    return {"id": pid, "label": str(p.get("label") or pid)[:80], "kind": p["kind"], "dur": 0.0 if p["kind"] == "cut" else dur,
            "from": p.get("from") if p.get("from") in SIDES else "right", "sound": sound if sound in ("whoosh", "pop", "hit", "ding", "riser") else "none"}


def library() -> dict:
    """{"presets": {id: preset}, "defaults": {"web", "broll"}}: the skill file, checked; a broken file or preset falls back to the built-in ones."""
    try:
        raw = json.loads((skillrules.find(FILE) or Path("missing")).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        raw = {}
    raw = raw if isinstance(raw, dict) else {}
    presets = dict(BUILTIN)
    for pid, p in (raw.get("presets") or {}).items() if isinstance(raw.get("presets"), dict) else []:
        c = _clean(str(pid), p)
        if c:
            presets[c["id"]] = c
    d = raw.get("defaults") if isinstance(raw.get("defaults"), dict) else {}
    return {"presets": presets, "defaults": {"web": d.get("web") if d.get("web") in presets else "slide", "broll": d.get("broll") if d.get("broll") in presets else "cut"}}


def defaults() -> dict:
    """{"web": id, "broll": id}: Settings first, then the library."""
    lib = library()
    s = config.user_settings()
    return {k: s.get(f"transition_{k}") if s.get(f"transition_{k}") in lib["presets"] else lib["defaults"][k] for k in ("web", "broll")}


def save_defaults(choice: dict) -> dict:
    lib = library()
    out = {}
    for k, v in (choice or {}).items():
        if k not in ("web", "broll"):
            raise ValueError("unknown kind of cutaway")
        if v not in lib["presets"]:
            raise ValueError("unknown transition")
        out[f"transition_{k}"] = v
    config.save_user_settings(out)
    return view()


def view() -> dict:
    lib = library()
    return {"presets": [{"id": p["id"], "label": p["label"]} for p in lib["presets"].values()], "defaults": defaults()}


def pick(insert: dict, lib: dict | None = None, dflt: dict | None = None) -> dict:
    """The preset for one B-roll insert of the beat map: its own choice, else the default for its kind (a web page or other B-roll)."""
    lib = lib or library()
    dflt = dflt or defaults()
    own = insert.get("transition")
    if own in lib["presets"]:
        return lib["presets"][own]
    return lib["presets"].get(dflt["web" if insert.get("source") else "broll"], CUT)


def stamp(pieces: list, preset: dict) -> list:
    """Put the transition on the cutaway's first piece (in) and last piece (out). A piece too short for both moves gets none."""
    if not pieces or preset["kind"] == "cut":
        return pieces
    small = {k: preset[k] for k in ("kind", "dur", "from", "sound")}
    if pieces[0]["dur"] >= 2 * preset["dur"] + 0.1 or len(pieces) > 1:
        pieces[0]["t_in"] = small
    if pieces[-1]["dur"] >= (2 if len(pieces) == 1 else 1) * preset["dur"] + 0.1:
        pieces[-1]["t_out"] = small
    return pieces


def sound_times(br: dict) -> list:
    """[(seconds into the piece, role)] for the sounds of one cutaway piece's transitions."""
    out = []
    at, dur = float(br.get("at", 0.0)), float(br.get("dur", 0.0))
    for side in ("t_in", "t_out"):
        t = br.get(side)
        if t and t.get("sound", "none") != "none":
            start = at if side == "t_in" else at + dur - float(t["dur"])
            out.append((round(max(0.0, start - LEAD_S), 3), t["sound"]))
    return out


def sound_file(role: str, n: int, kit: dict | None = None):
    """The n-th sound of a role in the sound kit (they take turns), or None when the kit has none."""
    import sfxkit
    files = (kit if kit is not None else sfxkit.kit()).get(role) or []
    return str(files[n % len(files)]) if files else None


def _ease(t0: float, d: float) -> str:
    p = f"clip((t-{t0:.3f})/{d:.3f},0,1)"
    return f"({p})*({p})*(3-2*({p}))"


def in_filters(br: dict, W: int, H: int) -> str:
    """Filters for the cutaway's own picture (its timestamps are already the segment's), ending in a comma, or ''."""
    at, dur = float(br.get("at", 0.0)), float(br.get("dur", 0.0))
    f = []
    ti, to = br.get("t_in") or {}, br.get("t_out") or {}
    if ti.get("kind") == "pop" or to.get("kind") == "pop":
        s_in = f"(0.6+0.4*{_ease(at, ti['dur'])})" if ti.get("kind") == "pop" else "1"
        s_out = f"(1-0.4*{_ease(at + dur - to['dur'], to['dur'])})" if to.get("kind") == "pop" else "1"
        f.append(f"scale=w='trunc({W}*{s_in}*{s_out}/2)*2':h='trunc({H}*{s_in}*{s_out}/2)*2':eval=frame")
    alpha = [(side, t) for side, t in (("in", ti), ("out", to)) if t.get("kind") in ("fade", "pop")]
    if alpha:
        f.append("format=yuva420p")
        for side, t in alpha:
            st = at if side == "in" else at + dur - t["dur"]
            f.append(f"fade=t={side}:st={st:.3f}:d={t['dur']:.3f}:alpha=1")
    if ti.get("kind") == "flash":
        f.append(f"fade=t=in:st={at:.3f}:d={ti['dur']:.3f}:color=white")
    if to.get("kind") == "flash":
        f.append(f"fade=t=out:st={at + dur - to['dur']:.3f}:d={to['dur']:.3f}:color=white")
    return "".join(x + "," for x in f)


def overlay_xy(br: dict) -> str:
    """':x=...:y=...' for the overlay filter (slides move the cutaway; a pop stays centred), or ''."""
    at, dur = float(br.get("at", 0.0)), float(br.get("dur", 0.0))
    ti, to = br.get("t_in") or {}, br.get("t_out") or {}
    x, y = [], []
    sign = {"right": ("W", x, 1), "left": ("W", x, -1), "bottom": ("H", y, 1), "top": ("H", y, -1)}
    if ti.get("kind") == "slide":
        size, axis, s = sign[ti["from"]]
        axis.append(f"{s}*{size}*(1-{_ease(at, ti['dur'])})")
    if to.get("kind") == "slide":
        size, axis, s = sign[to["from"]]                                     # it leaves the way it was going: in from the right, out to the left
        axis.append(f"{-s}*{size}*{_ease(at + dur - to['dur'], to['dur'])}")
    if "pop" in (ti.get("kind"), to.get("kind")):
        x.append("(W-w)/2")
        y.append("(H-h)/2")
    out = ""
    if x:
        out += ":x='" + "+".join(x) + "'"
    if y:
        out += ":y='" + "+".join(y) + "'"
    return out
