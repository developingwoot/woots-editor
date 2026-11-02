"""What the v2 Shorts screen shows, in plain words, from files only (no renders, no Claude).

A video's shorts live in `<name>.shorts.json` next to its other work files (shortsapp.py), so the shorts project of a video has the video's own key.
Everything here is data for the page: the sentence about how many shorts the video deserves, one card per short, and the words of an opened short.
"""
import json
from pathlib import Path
from urllib.parse import quote

import config
import finalrender
import shortsapp
import shortsplan
import shorts as sh
import skillrules
import views

STATUS_TEXT = {"": "", "kept": "Kept", "dropped": "Dropped"}


def clock(seconds) -> str:
    return views.time_text(seconds)


def _first_src(short) -> str:
    r = (short.get("ranges") or [[0, 0]])[0]
    return r["src"] if isinstance(r, dict) else ""


def _first_t(short) -> float:
    r = (short.get("ranges") or [[0, 0]])[0]
    return float(r["a"] if isinstance(r, dict) else r[0])


def _length(short) -> float:
    return sum((r["b"] - r["a"]) if isinstance(r, dict) else (r[1] - r[0]) for r in short.get("ranges") or [])


def recommendation(work: str, name: str, final: dict | None) -> dict:
    """How many shorts the video deserves and why, in one sentence. Uses the beat map when there is one, else the length of the final."""
    if shortsapp.cfg_file(work, name).exists():
        rec = shortsapp.video_plan(work, name)
    else:
        rec = shortsplan.for_video(work, name)
    if not rec["runtime_s"] and final and final.get("dur"):
        rec = dict(shortsplan.recommend(None, runtime_s=_seconds(final["dur"])), has_beatmap=False)
    n = rec.get("recommended") or 0
    if not n:
        return {"count": 0, "sentence": ""}
    strong = rec.get("strong") or 0
    if rec.get("has_beatmap") and strong:
        sentence = f"This video has {strong} strong moment{'s' if strong != 1 else ''}, so room for about {n} short{'s' if n != 1 else ''}."
    elif strong and rec.get("confidence") == "medium":
        sentence = (f"This video is {clock(rec['runtime_s'])} long and {strong} stretch{'es' if strong != 1 else ''} of it look like complete little stories, "
                    f"so room for about {n} short{'s' if n != 1 else ''}.")
    else:
        sentence = f"This video is {clock(rec['runtime_s'])} long, so room for about {n} short{'s' if n != 1 else ''}."
    return {"count": n, "sentence": sentence}


def _seconds(v) -> float:
    """The final's length is saved as seconds or as 'm:ss'."""
    if isinstance(v, (int, float)):
        return float(v)
    parts = [float(x) for x in str(v).split(":") if x.strip()]
    return sum(p * 60 ** i for i, p in enumerate(reversed(parts)))


def card(work: str, name: str, wd, short: dict) -> dict:
    prev = shortsapp._render_one(wd, short, "")
    fin = shortsapp._render_one(wd, short, ".final")
    sid = short["id"]
    return {"id": sid, "title": short.get("title") or "A short", "hook": (short.get("hook") or "").replace("|", " "), "why": short.get("why", ""),
            "status": shortsapp.status_of(short), "length": clock(_length(short)), "seconds": round(_length(short), 1), "pace": short.get("pace") or "natural",
            "frame": f"/api/shorts/frame?work={quote(work)}&name={quote(name)}&t={_first_t(short):.1f}&w=360&src={quote(_first_src(short))}",
            "preview": {"url": f"/shortmedia/{quote(work)}/{quote(sid)}.mp4?v={prev['mtime']}" if prev.get("exists") else "", "old": bool(prev.get("stale"))},
            "final": {"made": bool(fin.get("exists")) and not fin.get("stale")},
            "tightened": bool(short.get("before_tighten")),
            "gfx": graphics_of(short),
            "sound": {"style": short.get("caption_style") or "", "music": short.get("music") or "", "sfx": short.get("sfx") or "on",
                      "emphasis": short.get("emphasis") or [], "made": prev.get("audio") or {}}}


def graphics_of(short: dict) -> dict:
    """The Graphics panel of an open short: what was planned (a headline and the look of each), what is cut, and whether this short can have any."""
    import shortsgfxbuild
    plan = short.get("gfx") or {}
    rows = [{"id": g["id"], "title": (g.get("text") or g.get("what") or "").splitlines()[0][:60] if (g.get("text") or g.get("what")) else "Graphic", "what": g.get("what", ""),
             "look": g.get("look") or "card", "place": g.get("place", "top"), "cut": g.get("status") == "cut", "words": g.get("words", "")} for g in plan.get("graphics", [])]
    return {"can": shortsgfxbuild.single_source(short) and not any(isinstance(r, dict) for r in short.get("ranges") or []), "planned": bool(plan), "note": plan.get("note", ""),
            "skipped": plan.get("skipped", []), "graphics": rows}


def sounds() -> dict:
    """What the Sound panel of an open short offers: caption styles, the music (steadiest first, never a track with vocals) and the sound-effect kit."""
    import sfxkit
    import shortsaudio
    return {"styles": [{"id": k, "label": v} for k, v in sh.CAPTION_STYLES.items()], "default_style": skillrules.shorts()["caption_style"],
            "tracks": [t["name"] for t in shortsaudio.tracks()], "kit": sfxkit.view()}


def project(work: str, name: str, busy: bool = False) -> dict:
    """The Shorts step of one video."""
    wd = config.WORK / work
    finals = finalrender.finals(work, name)
    final = finals[0] if finals else None
    has_project = shortsapp.cfg_file(work, name).exists()
    out = {"key": views.key_of(work, name), "has_final": bool(final), "has_project": has_project, "busy": busy, "shorts": [], "dropped": [],
           "recommendation": recommendation(work, name, final), "paces": {k: v["label"] for k, v in sh.PACES.items()}, "last_find": "", "unlooked": 0}
    if not final and not has_project:
        out["needs"] = "Shorts are cut from the final video. Render the final first."
        return out
    if not has_project:
        return out
    raw = shortsapp.read_raw(work, name)
    shorts = raw.get("shorts", [])
    out["title"] = Path(raw["folder"]).name if raw.get("mode") == "raw" and raw.get("folder") else Path(raw.get("source", "")).stem
    height = sh.probe_size(raw["source"])[1] if raw.get("mode") != "raw" and Path(raw.get("source", "")).is_file() else 0
    if height and height < skillrules.shorts()["soft_below_px"]:
        out["note"] = f"The video is {height}p, so close crops look soft."
    out["shorts"] = [card(work, name, wd, s) for s in shorts if shortsapp.status_of(s) != "dropped"]
    out["dropped"] = [{"id": x["id"], "title": x.get("title") or "A short"} for x in shorts if shortsapp.status_of(x) == "dropped"]
    out["unlooked"] = sum(1 for c in out["shorts"] if not c["status"])
    lf = raw.get("last_find") or {}
    if lf.get("skipped"):
        out["last_find"] = f"Claude suggested {len(lf['skipped'])} more that did not fit the rules, so they were left out."
    return out


def area() -> dict:
    """The Shorts area: every video that has shorts, or a final to make them from."""
    import workflow
    projects = shortsapp.projects()
    have = {(p["work"], p["name"]): p for p in projects}
    items = []
    own = {(v["work"], n) for v in workflow.list_videos() for n in v["names"]}
    for v in workflow.list_videos():
        for name in v["names"]:
            p = have.get((v["work"], name))
            finals = finalrender.finals(v["work"], name)
            if not p and not finals:
                continue
            title = views.facts(v["work"], name)["title"]
            if p:
                sentence = f"{p['shorts']} short{'s' if p['shorts'] != 1 else ''}" + (f", {p['kept']} kept" if p["kept"] else "")
                button = "Open the shorts"
            else:
                sentence, button = "The final is ready: make shorts from it", "Make shorts"
            items.append({"key": views.key_of(v["work"], name), "title": title, "sentence": sentence, "button": button})
    for p in projects:                                    # shorts made from a video file that is not one of the app's videos
        if (p["work"], p["name"]) not in own:
            sentence = f"{p['shorts']} short{'s' if p['shorts'] != 1 else ''}" + (f", {p['kept']} kept" if p["kept"] else "")
            items.append({"key": views.key_of(p["work"], p["name"]), "title": p["title"], "sentence": sentence, "button": "Open the shorts", "standalone": True})
    return {"items": items}


def words(work: str, name: str, sid: str) -> dict:
    """The words of one short, in order, each with whether it is cut out (the host clicks a word to cut or restore it)."""
    cfg = sh.load(shortsapp.cfg_file(work, name))
    short = shortsapp._short(cfg, sid)
    cfg["_short"] = short
    out = []
    for w in sh.kept_words(cfg, short, flag=True):
        if not out or out[-1]["r"] != w["r"]:
            out.append({"r": w["r"], "words": []})
        out[-1]["words"].append({"w": w["w"], "s": round(w["s"], 3), "e": round(w["e"], 3), "cut": w["cut"], "why": w["why"]})
    return {"id": sid, "ranges": out, "hook": short.get("hook", ""), "title": short.get("title", "")}
