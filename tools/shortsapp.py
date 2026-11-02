"""Shorts tab: reading and editing a video's shorts without Claude (no tokens), plus the pieces the app's jobs need.

Files (in <work>\\, next to a finished video's other work files):
    <name>.shorts.json          the project: source video, transcript, speakers, and the list of shorts (format: see shorts.py)
    shorts\\<id>.auto.json       cached automatic crops for a short (kept until its ranges, drops or caption fixes change)
    shorts\\<id>.mp4            the rendered vertical preview; <id>.render.json says which settings it was rendered with
Everything the tab changes is a field of a short in the .shorts.json; the render is rebuilt from it, so nothing is lost by re-rendering.
Pure Python plus OpenCV for one frame: the review app uses it, the render itself is shorts.py.
"""
import json
import os
import re
import sys
import time
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))
import shorts as sh                       # noqa: E402
import shortsplan                         # noqa: E402
import shortsgfx                          # noqa: E402

EDITOR = TOOLS.parent
import brandstyle
import channel
import config
import projectstore
WORK = config.WORK
STATUSES = ("", "kept", "dropped")          # not looked at yet / the host wants it / the host does not (hidden, never deleted)
LEGACY_STATUS = {"proposed": "", "approved": "kept", "rejected": "dropped"}         # older project files


def status_of(short: dict) -> str:
    st = short.get("status") or ""
    st = LEGACY_STATUS.get(st, st)
    return st if st in STATUSES else ""


def live(shorts: list) -> list:
    """The shorts that are not dropped: what the graphics, the final render and the delivery work on."""
    return [s for s in shorts if status_of(s) != "dropped"]


def wd_of(work: str) -> Path:
    if not work or "/" in work or "\\" in work or ".." in work:
        raise ValueError(f"bad name {work!r}")
    d = WORK / work
    if not d.is_dir():
        raise ValueError(f"unknown work folder {work!r}")
    return d


def cfg_file(work: str, name: str) -> Path:
    if not name or "/" in name or "\\" in name or ".." in name:
        raise ValueError(f"bad name {name!r}")
    return wd_of(work) / f"{name}.shorts.json"


def read_raw(work, name) -> dict:
    p = cfg_file(work, name)
    if not p.exists():
        raise ValueError(f"no shorts project {name!r} in {work!r}")
    raw = json.loads(p.read_text(encoding="utf-8-sig"))
    for s in raw.get("shorts", []):
        s["status"] = status_of(s)
    return raw


def save_raw(work, name, raw, why=""):
    """Written through projectstore, so every change is recorded (who, why) and can be undone."""
    projectstore.write_json(cfg_file(work, name), raw, why=why)


def projects() -> list:
    out = []
    for d in sorted(WORK.iterdir()) if WORK.is_dir() else []:
        if not d.is_dir():
            continue
        for f in sorted(d.glob("*.shorts.json")):
            try:
                raw = json.loads(f.read_text(encoding="utf-8-sig"))
            except (OSError, ValueError):
                continue
            out.append({"work": d.name, "name": f.name[: -len(".shorts.json")], "source": Path(raw.get("source", "")).name,
                        "shorts": len(raw.get("shorts", [])), "kept": sum(1 for s in raw.get("shorts", []) if status_of(s) == "kept")})
    return out


def _render_one(wd: Path, short: dict, suffix: str) -> dict:
    mp4 = wd / "shorts" / f"{short['id']}{suffix}.mp4"
    if not mp4.exists():
        return {"exists": False}
    meta = {}
    try:
        meta = json.loads((wd / "shorts" / f"{short['id']}{suffix}.render.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    return {"exists": True, "file": mp4.name, "mtime": int(mp4.stat().st_mtime), "dur": meta.get("dur"),
            "stale": meta.get("sig") != sh.short_sig(short, sh.SIG_ALL)}


def _render_info(wd: Path, short: dict) -> dict:
    """The quick preview (half size) at the top level, the final (1080x1920, best quality) under 'final'."""
    out = _render_one(wd, short, "")
    out["final"] = _render_one(wd, short, ".final")
    return out


def state(work, name) -> dict:
    raw = read_raw(work, name)
    wd = wd_of(work)
    shorts = []
    for s in raw.get("shorts", []):
        est = sum(max(0.0, r["b"] - r["a"]) if isinstance(r, dict) else max(0.0, r[1] - r[0]) for r in s.get("ranges", []))
        shorts.append({"id": s["id"], "title": s.get("title", ""), "hook": s.get("hook", ""), "why": s.get("why", ""), "thought": s.get("thought") or {}, "visual": s.get("visual", ""), "gfx": s.get("gfx"),
                       "status": status_of(s), "ranges": s.get("ranges", []), "drop": s.get("drop", []),
                       "words": s.get("words", {}), "crops": s.get("crops", []), "layout_all": s.get("layout_all", ""),
                       "estimate": round(est, 1), "pace": sh.LEGACY_PACE.get(s.get("pace") or "natural", s.get("pace") or "natural"), "publish": s.get("publish") or {}, "delivered": s.get("delivered") or {}, "tightened": bool(s.get("before_tighten")), "tighten_note": (s.get("tighten") or {}).get("note", ""), "render": _render_info(wd, s)})
    import mpfaces
    return {"work": work, "name": name, "source": raw.get("source", ""), "has_speakers": bool(raw.get("speakers")),
            "font": brandstyle.font("headline")["name"], "faces": mpfaces.available(), "full_video_url": raw.get("full_video_url", ""), "last_find": raw.get("last_find"), "folder": str(Path(raw.get("source", "")).parent / "Shorts"),
            "paces": {k: v["label"] for k, v in sh.PACES.items()}, "shorts": shorts}


def _short(raw, sid):
    for s in raw.get("shorts", []):
        if s["id"] == sid:
            return s
    raise ValueError(f"no short {sid!r}")


def plan(work, name, sid) -> dict:
    """The pieces of one short as the tab shows them (computes and caches the automatic crops the first time: a few seconds)."""
    cfg = sh.load(cfg_file(work, name))
    short = _short(cfg, sid)
    cfg["_short"] = short
    pieces = sh.cached_pieces(cfg, short, wd_of(work))
    out = []
    for i, p in enumerate(pieces):
        item = {"i": i, "a": round(p["a"], 2), "b": round(p["b"], 2), "t0": round(p["t0"], 2), "dur": round(p["dur"], 2), "t": round((p["a"] + p["b"]) / 2, 2),
                "layout": p["layout"], "speaker": p.get("speaker", ""), "cx": round(p["cx"], 3), "cy": round(p["cy"], 3), "zoom": p.get("zoom", 1.0),
                "gzoom": p.get("gzoom", 1.0), "gcx": p.get("gcx", 0.5), "gcy": p.get("gcy", 0.5), "cont": p["cont"],
                "words": [{"w": w["w"], "s": round(w["s"], 2)} for w in p["words"]]}
        if p["layout"] != "graphic":
            cw, ch, x, y = sh.crop_box(p)
            item["box"] = [x, y, cw, ch]
        out.append(item)
    total = (pieces[-1]["t0"] + pieces[-1]["dur"]) / sh.pace_of(short)["speed"] if pieces else 0
    text = []
    for w in sh.kept_words(cfg, short, flag=True):
        if not text or text[-1]["r"] != w["r"]:
            text.append({"r": w["r"], "range": short["ranges"][w["r"]], "words": []})
        text[-1]["words"].append({"w": w["w"], "s": round(w["s"], 2), "e": round(w["e"], 2), "cut": w["cut"], "why": w["why"]})
    return {"id": sid, "pieces": out, "total": round(total, 1), "src": list(cfg.get("_size") or sh.DEFAULT_SIZE), "text": text}


def _num_ranges(v, what):
    out = []
    for r in v or []:
        if not (isinstance(r, (list, tuple)) and len(r) == 2):
            raise ValueError(f"{what}: each one needs a start and an end")
        a, b = float(r[0]), float(r[1])
        if not (0 <= a < b):
            raise ValueError(f"{what}: {a}-{b} is not a start before an end")
        out.append([round(a, 2), round(b, 2)])
    return out


def _toggle_cut(drop, a, b, add):
    """Cut one word out (add) or put it back: the spans stay a clean list. Exact word edges, never touching the neighbours."""
    spans = sorted([list(x) for x in drop])
    if add:
        spans.append([a - 0.002, b + 0.002])
        spans.sort()
        merged = [spans[0]]
        for x in spans[1:]:
            if x[0] <= merged[-1][1] + 0.01:
                merged[-1][1] = max(merged[-1][1], x[1])
            else:
                merged.append(x)
        spans = merged
    else:
        lo, hi = a + 0.001, b - 0.001
        new = []
        for s0, s1 in spans:
            if s1 <= lo or s0 >= hi:
                new.append([s0, s1])
                continue
            if s0 < lo:
                new.append([s0, lo])
            if s1 > hi:
                new.append([hi, s1])
        spans = new
    return [[round(x[0], 3), round(x[1], 3)] for x in spans if x[1] - x[0] > 0.004]


def apply_op(work, name, op, b) -> dict:
    raw = read_raw(work, name)
    wd = wd_of(work)
    if op == "project":
        raw["full_video_url"] = str(b.get("full_video_url", "")).strip()
    elif op == "add":
        ids = [int(m.group(1)) for s in raw.get("shorts", []) if (m := re.match(r"^s(\d+)$", s["id"]))]
        sid = f"s{max(ids, default=0) + 1}"
        ranges = _num_ranges(b.get("ranges"), "ranges")
        if not ranges:
            raise ValueError("give at least one range, e.g. 20.6-40.7")
        raw.setdefault("shorts", []).append({"id": sid, "title": b.get("title") or "New short", "hook": b.get("hook", ""), "why": b.get("why", ""),
                                             "status": "", "ranges": ranges})
    else:
        s = _short(raw, b["id"])
        if op == "edit":
            for k in ("title", "hook", "why"):
                if k in b:
                    s[k] = str(b[k]).strip()
            if "status" in b:
                new = LEGACY_STATUS.get(b["status"], b["status"])
                if new not in STATUSES:
                    raise ValueError("status must be kept, dropped or empty")
                s["status"] = new
            if "ranges" in b:
                s["ranges"] = _num_ranges(b["ranges"], "ranges") or s["ranges"]
            if "drop" in b:
                s["drop"] = _num_ranges(b["drop"], "cut-out spans")
            if "pace" in b:
                if b["pace"] not in sh.PACES:
                    raise ValueError("pace is " + ", ".join(sh.PACES))
                s["pace"] = b["pace"]
            if "layout_all" in b:
                if b["layout_all"] and b["layout_all"] not in ("blur", "live"):
                    raise ValueError("layout_all is blur, live or empty")
                if b["layout_all"]:
                    s["layout_all"] = b["layout_all"]
                else:
                    s.pop("layout_all", None)
        elif op == "crop":
            t = round(float(b["t"]), 2)
            crops = s.setdefault("crops", [])
            lo, hi = (float(b["a"]) - 0.05, float(b["b"]) + 0.05) if "a" in b and "b" in b else (t - 0.06, t + 0.06)
            hit = [c for c in crops if lo <= c["t"] <= hi]          # every earlier choice for this piece becomes one entry
            ent = None
            if hit:
                ent = {"t": t}
                for c in hit:
                    ent.update({k: v for k, v in c.items() if k != "t"})
                for c in hit:
                    crops.remove(c)
            if b.get("reset"):
                ent = None
            else:
                if ent is None:
                    ent = {"t": t}
                crops.append(ent)
                for k in sh.OVERRIDE_KEYS:
                    if k in b:
                        v = b[k]
                        if v is None:
                            ent.pop(k, None)
                        elif k == "layout":
                            if v not in ("live", "blur", "graphic"):
                                raise ValueError("layout is live, blur or graphic")
                            ent[k] = v
                        else:
                            ent[k] = round(float(v), 3)
                if len(ent) == 1:
                    crops.remove(ent)
            if not crops:
                s.pop("crops", None)
        elif op == "publish":
            pub = s.setdefault("publish", {})
            for k in ("title", "description", "filename"):
                if k in b:
                    pub[k] = str(b[k]).strip()
            if "tags" in b:
                pub["tags"] = [t.strip() for t in (b["tags"] if isinstance(b["tags"], list) else str(b["tags"]).split(",")) if t.strip()]
            if len(pub.get("title", "")) > 100:
                raise ValueError("a YouTube title can be at most 100 characters")
            if pub.get("filename"):
                pub["filename"] = _slug(pub["filename"])
        elif op == "cut":
            s["drop"] = _toggle_cut(s.get("drop", []), float(b["start"]), float(b["end"]), bool(b.get("cut", True)))
            if not s["drop"]:
                s.pop("drop", None)
        elif op == "untighten":
            before = s.get("before_tighten")
            if not before:
                raise ValueError("nothing to undo")
            s["ranges"], s["drop"] = before["ranges"], before.get("drop", [])
            if not s["drop"]:
                s.pop("drop", None)
            s.pop("before_tighten", None)
            s.pop("tighten", None)
        elif op == "word":
            words = s.setdefault("words", {})
            key = f"{round(float(b['start']), 2):g}"
            if b.get("restore"):
                words.pop(key, None)
            else:
                words[key] = str(b.get("text", ""))
            if not words:
                s.pop("words", None)
        elif op == "delete":
            raw["shorts"] = [x for x in raw["shorts"] if x["id"] != b["id"]]
            for f in (wd / "shorts").glob(f"{b['id']}.*"):
                try:
                    f.unlink()
                except OSError:
                    pass
        else:
            raise ValueError(f"unknown shorts operation {op!r}")
    save_raw(work, name, raw)
    return state(work, name)


def frame_jpeg(work, name, t: float, width: int = 960) -> bytes:
    import cv2
    raw = read_raw(work, name)
    cap = cv2.VideoCapture(raw["source"])
    cap.set(cv2.CAP_PROP_POS_MSEC, float(t) * 1000)
    ok, fr = cap.read()
    cap.release()
    if not ok:
        raise ValueError("could not read that frame")
    h = int(fr.shape[0] * width / fr.shape[1])
    ok, buf = cv2.imencode(".jpg", cv2.resize(fr, (width, h)), [cv2.IMWRITE_JPEG_QUALITY, 82])
    return buf.tobytes()


# ----------------------------------------------------------------------------- graphics plan of an approved short (shortsgfx.py)
def _gfx_ctx(work, name, sid):
    cfg = sh.load(cfg_file(work, name))
    short = _short(cfg, sid)
    cfg["_short"] = short
    pieces = sh.cached_pieces(cfg, short, wd_of(work))
    return cfg, short, pieces


def gfx_view(work, name, sid) -> dict:
    cfg, short, pieces = _gfx_ctx(work, name, sid)
    return shortsgfx.view(cfg, short, pieces, sid)


def gfx_still(work, name, sid, gid, k, width=360) -> bytes:
    cfg, short, pieces = _gfx_ctx(work, name, sid)
    return shortsgfx.still_jpeg(cfg, short, pieces, gid, k, width)


def gfx_prompt(work, name, sid) -> str:
    cfg = sh.load(cfg_file(work, name))
    short = _short(cfg, sid)
    bm = {}
    try:
        bm = json.loads((wd_of(work) / f"{name}.beatmap.json").read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        pass
    ranges = short["ranges"]
    beats = [b for b in bm.get("beats", []) if not b.get("skip") and any(b["start"] < r1 and b["end"] > r0 for r0, r1 in ranges)]
    return shortsgfx.prompt_for(short, sh.kept_words(cfg, short), beats)


def gfx_import(work, name, sid, path: Path) -> dict:
    raw = read_raw(work, name)
    s = _short(raw, sid)
    res = shortsgfx.import_plan(s, json.loads(path.read_text(encoding="utf-8-sig")))
    save_raw(work, name, raw)
    return res


def gfx_mark(work, name, sid, gid, status, note="") -> dict:
    raw = read_raw(work, name)
    g = shortsgfx.mark(_short(raw, sid), gid, status, note)
    save_raw(work, name, raw)
    return g


# ----------------------------------------------------------------------------- new project, Claude's candidates
def new_project(work: str, name: str, source: str, transcript: str, speakers: str | None):
    p = cfg_file(work, name)
    if p.exists():
        raise ValueError("that shorts project already exists")
    save_raw(work, name, {"source": source, "transcript": transcript, "speakers": speakers or "", "shorts": []})


def video_plan(work: str, name: str, cfg: dict | None = None) -> dict:
    """The recommendation for this video: how many shorts, and where its strong visual moments are (shortsplan.py)."""
    rec = shortsplan.for_video(work, name)
    if not rec["runtime_s"]:                                         # no beat map for this project: length from the transcript
        cfg = cfg or sh.load(cfg_file(work, name))
        rec = dict(shortsplan.recommend(None, runtime_s=float(cfg["_tr"].get("duration") or 0)), has_beatmap=False)
    return rec


def find_prompt(work: str, name: str, count: int | None = None) -> str:
    cfg = sh.load(cfg_file(work, name))
    rec = video_plan(work, name, cfg)
    count = count or rec["recommended"] or 3
    lines = []
    segs = cfg["_spk"] or [{"start": s["start"], "end": s["end"], "speaker": "", "text": s["text"]} for s in cfg["_tr"]["segments"]]
    for s in segs:
        lines.append(f"[{s['start']:.1f}-{s['end']:.1f}] {s.get('speaker') or ''}: {s['text']}")
    have = [f"{s['title']} ({s['ranges']})" for s in cfg.get("shorts", [])]
    extra = ("\nShorts that already exist (do not repeat these moments):\n- " + "\n- ".join(have) + "\n") if have else ""
    return (shortsplan.find_rules(count, rec["strong"] if rec.get("has_beatmap") else None) + "\n" + shortsplan.moments_text(rec["moments"]) + extra
            + "\nTRANSCRIPT (the finished main video; speakers: " + ", ".join(channel.people())
            + ("; the transcript mishears words like " + ", ".join(channel.spellings()) if channel.spellings() else "") + "):\n"
            + "\n".join(lines) + "\n")


def import_candidates(work: str, name: str, path: Path, count: int | None = None) -> int:
    """Add Claude's proposed shorts that follow the rules (shortsplan.validate); what was skipped, and why, is kept in raw['last_find']."""
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    raw = read_raw(work, name)
    runtime = float((sh.load(cfg_file(work, name))["_tr"] or {}).get("duration") or 0)
    ids = [int(m.group(1)) for s in raw.get("shorts", []) if (m := re.match(r"^s(\d+)$", s["id"]))]
    n = max(ids, default=0)
    kept = [{"title": s.get("title", ""), "ranges": s.get("ranges", [])} for s in raw.get("shorts", []) if status_of(s) != "dropped"]
    added, skipped = 0, []
    for c in data if isinstance(data, list) else []:
        title = str(c.get("title", "Short"))[:90]
        if count and added >= count:
            skipped.append(f"{title}: more than the {count} asked for")
            continue
        try:
            ranges = _num_ranges(c.get("ranges"), "ranges")
        except (ValueError, TypeError):
            skipped.append(f"{title}: the ranges are not numbers")
            continue
        thought = {k: str((c.get("thought") or {}).get(k, ""))[:300] for k in ("setup", "point", "payoff")}
        cand = {"title": title, "ranges": ranges, "thought": thought}
        problems = shortsplan.validate([cand], runtime) if ranges else ["no ranges"]
        if not problems and kept:
            problems = [p for p in shortsplan.validate(kept + [cand], runtime) if "same part" in p and f"short {len(kept) + 1}" in p]
        if problems:
            skipped.append(f"{title}: {problems[0]}")
            continue
        n += 1
        added += 1
        kept.append(cand)
        raw.setdefault("shorts", []).append({"id": f"s{n}", "title": title, "hook": str(c.get("hook", ""))[:90].upper(),
                                             "why": str(c.get("why", ""))[:300], "thought": thought, "visual": str(c.get("visual", ""))[:300],
                                             "status": "", "ranges": ranges})
    raw["last_find"] = {"asked": count, "added": added, "skipped": skipped, "at": time.time()}
    save_raw(work, name, raw)
    return added


# ----------------------------------------------------------------------------- tighten: cut content out so the short is dense
TIGHTEN_RULES = """The host wants this YouTube Short CUT HARD so it is informational and engaging from the first word to the last: remove parts of the content completely and shorten it. You may only DELETE words and spans; never reword, never reorder, never invent.

Goal: 18 to 35 seconds of speech after your cuts (never over 45). Every remaining sentence must earn its place. The first sentence is the hook: if the short opens with a slow set-up, cut to the real point.

Cut, in this order of preference:
1. Filler and verbal tics: um, uh, like, you know, I mean, kind of, sort of, basically, so, well, right, okay, "and stuff like that", "I would say", "to be honest", "I think" when it hedges.
2. False starts, restarts and repeated words or phrases (keep the clean version).
3. Asides, tangents, personal chatter and anything that does not serve the one point.
4. A second example or a restatement when the first already makes the point.
5. The other person's back-and-forth ("Okay.", "Yeah.", "Right.", "Mm-hm") and long questions: shorten a question to its essence by cutting its first half, or drop the question entirely when the answer stands alone (the on-screen hook title carries the question).
6. A trailing sentence that only wraps up; end on the payoff.

Keep: the claim, the key reason, the number or example that proves it, the punchline. What remains must read as complete, grammatical sentences when joined in order, and sound natural: do not cut in the middle of a phrase so that the grammar breaks. Do not leave a sentence starting with "and", "but", "so" unless it is needed.

You can also change the ranges (start earlier or end later inside the context given, e.g. to reach the payoff, or to start on the real hook), still in play order.

Output: write tighten.json in the current folder (Write tool), exactly this shape and nothing else:
{"ranges": [[start, end], ...], "drop": [[start, end], ...], "kept_text": "the sentences that remain, as they will be spoken", "note": "one or two sentences: what you cut and why"}
- Every time is a SOURCE second taken from the word timestamps below. A drop span covers whole words only: from the start of the first word you remove to the end of the last word you remove (use those exact numbers). Drop spans must lie inside the ranges.
"""


def tighten_prompt(work: str, name: str, sid: str) -> str:
    cfg = sh.load(cfg_file(work, name))
    short = _short(cfg, sid)
    words = cfg["_tr"]["words"]
    lo = max(0.0, min(a for a, _ in short["ranges"]) - 12)
    hi = max(b for _, b in short["ranges"]) + 15
    ctx = []
    for s in cfg["_spk"] or [{"start": x["start"], "end": x["end"], "speaker": "", "text": x["text"]} for x in cfg["_tr"]["segments"]]:
        if s["end"] >= lo and s["start"] <= hi:
            ctx.append(f"[{s['start']:.1f}-{s['end']:.1f}] {s.get('speaker') or ''}: {s['text']}")
    sel = []
    for ri, (a, b) in enumerate(short["ranges"]):
        ws = [w for w in words if w["start"] >= a - 0.06 and w["end"] <= b + 0.04]
        sel.append(f"RANGE {ri + 1} ({a}-{b}):\n" + " ".join(f"{w['word']}<{w['start']:.2f}-{w['end']:.2f}>" for w in ws))
    return (TIGHTEN_RULES + f"\nThe short: \"{short.get('title', '')}\". On-screen hook title: \"{short.get('hook', '')}\".\n"
            + ("Why it was picked: " + short["why"] + "\n" if short.get("why") else "")
            + "\nCURRENT SELECTION (every word with its start-end seconds; the transcript mishears " + (", ".join(channel.spellings()) or "some words") + "):\n" + "\n".join(sel)
            + "\n\nSURROUNDING TRANSCRIPT (for context and for choosing better start/end points):\n" + "\n".join(ctx) + "\n")


def apply_tighten(work: str, name: str, sid: str, path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    raw = read_raw(work, name)
    s = _short(raw, sid)
    ranges = _num_ranges(data.get("ranges"), "ranges") or s["ranges"]
    drop = _num_ranges(data.get("drop"), "cuts")
    if not drop and ranges == s["ranges"]:
        raise ValueError("Claude proposed no cuts")
    trial = dict(s, ranges=ranges, drop=drop)
    cfg = sh.load(cfg_file(work, name))
    kept = sh.kept_words(cfg, trial)
    speech = sum(w["e"] - w["s"] for w in kept)
    if len(kept) < 8 or speech < 4:
        raise ValueError(f"the cuts leave only {len(kept)} words: refused")
    if "before_tighten" not in s:
        s["before_tighten"] = {"ranges": s["ranges"], "drop": s.get("drop", [])}
    s["ranges"], s["drop"] = ranges, drop
    s["tighten"] = {"note": str(data.get("note", ""))[:400], "text": str(data.get("kept_text", ""))[:1500], "words_kept": len(kept), "at": time.time()}
    save_raw(work, name, raw)
    return {"words": len(kept), "speech": round(speech, 1)}


# ----------------------------------------------------------------------------- YouTube title, description, tags, file name
def _slug(text: str) -> str:
    t = re.sub(r"[^a-z0-9]+", "-", str(text).lower().replace("&", " and ")).strip("-")
    return t[:70].strip("-") or "short"


PUBLISH_RULES = """Write the YouTube Shorts metadata for these shorts from the channel (its subject is in the channel profile above). Goal: found in search and suggested, clicked, watched to the end. Everything must be TRUE to what the short says.

For each short give:
- title: aim for 40 to 60 characters (hard limit 80). Put the main search phrase in the first 40 characters (what a person types to find this). A concrete benefit, answer, number or question. Plain words. No clickbait lies, no ALL CAPS, no "#Shorts" in the title, at most one emoji and only if it adds meaning.
- description: 2 or 3 short sentences. The first sentence contains the main phrase and gives the answer or the hook (it shows before "more"). Then one line of context. If a full-video link is given below, add a line "Full video: <link>"; if none is given, do not mention a link. Then a line: "the channel: practical 3D printing upgrades, tests and lessons." Then 4 or 5 hashtags on the last line, always #Shorts and #3DPrinting plus topic ones (#Klipper, #Ender3, ...).
- tags: 8 to 12 lowercase search phrases, the main phrase first.
- filename: lowercase ASCII words joined by hyphens, 3 to 7 words, the main keywords (for example never-use-a-cold-iron), no stop-word padding, no dates, no ids.
Do not invent facts, prices or numbers that are not in the short's text. The co-host and the host may be named when it helps.

Write publish.json in the current folder (Write tool), exactly this shape and nothing else:
[{"id": "s1", "title": "...", "description": "...", "tags": ["..."], "filename": "..."}]
"""


def publish_prompt(work: str, name: str, ids: list) -> str:
    cfg = sh.load(cfg_file(work, name))
    raw_title = Path(cfg["source"]).stem
    parts = []
    for sid in ids:
        s = _short(cfg, sid)
        text = (s.get("tighten") or {}).get("text") or " ".join(w["w"] for w in sh.kept_words(cfg, s))
        parts.append(f"SHORT {sid}\n  working title: {s.get('title', '')}\n  on-screen hook: {s.get('hook', '').replace('|', ' ')}\n  what is said: {text}")
    link = cfg.get("full_video_url") or ""
    return (PUBLISH_RULES + f"\nThe full video these were cut from: \"{raw_title}\".\nFull-video link: {link or '(not given yet: leave the link line out)'}\n\n" + "\n\n".join(parts) + "\n")


def apply_publish(work: str, name: str, path: Path) -> int:
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    raw = read_raw(work, name)
    n = 0
    for item in data if isinstance(data, list) else []:
        try:
            s = _short(raw, item["id"])
        except (ValueError, KeyError):
            continue
        title = str(item.get("title", "")).strip()
        if not title or len(title) > 100:
            continue
        s["publish"] = {"title": title, "description": str(item.get("description", "")).strip(),
                        "tags": [str(t).strip().lower() for t in item.get("tags", []) if str(t).strip()][:15],
                        "filename": _slug(item.get("filename") or title)}
        n += 1
    save_raw(work, name, raw)
    return n


def _same_file(a: Path, b: Path) -> bool:
    import filecmp
    return a.stat().st_size == b.stat().st_size and filecmp.cmp(a, b, shallow=False)


def deliver(work: str, name: str, log=None) -> list:
    """Copy the final render of every short that is not dropped into <the finished video's folder>\\Shorts\\, named from its generated file name, with a .txt beside it
    holding the title, description and tags to paste into YouTube. Never overwrites: an identical file is skipped, a different one gets (2), (3)..."""
    import shutil
    say = log or (lambda m: None)
    raw = read_raw(work, name)
    wd = wd_of(work)
    folder = Path(raw["source"]).parent / "Shorts"
    todo = live(raw.get("shorts", []))
    if not todo:
        raise ValueError("no shorts to deliver")
    bad = [s["id"].upper() for s in todo if not _render_one(wd, s, ".final").get("exists") or _render_one(wd, s, ".final").get("stale")]
    if bad:
        raise ValueError("final render missing or out of date for " + ", ".join(bad))
    folder.mkdir(exist_ok=True)
    out = []
    for s in todo:
        pub = s.get("publish") or {}
        if not pub.get("title"):
            say(f"{s['id'].upper()}: no generated title yet, using the working title and file name")
        stem = pub.get("filename") or _slug(s.get("title", s["id"]))
        src = wd / "shorts" / f"{s['id']}.final.mp4"
        dst, k = folder / f"{stem}.mp4", 1
        while dst.exists() and not _same_file(src, dst):
            k += 1
            dst = folder / f"{stem} ({k}).mp4"
        if not dst.exists():
            shutil.copy2(src, dst)
        txt = [pub.get("title") or s.get("title", ""), "", pub.get("description", ""), "", "Tags: " + ", ".join(pub.get("tags", [])), "",
               f"Hook on screen: {s.get('hook', '').replace('|', ' ')}", f"File: {dst.name}"]
        dst.with_suffix(".txt").write_text("\n".join(txt) + "\n", encoding="utf-8")
        s["delivered"] = {"file": str(dst), "at": time.time(), "sig": sh.short_sig(s, sh.SIG_ALL)}
        out.append(str(dst))
        say(f"{s['id'].upper()} -> {dst}")
    save_raw(work, name, raw)
    return out
