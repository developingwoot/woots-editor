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

TOOLS = Path(os.path.abspath(__file__)).parent
sys.path.insert(0, str(TOOLS))
import shorts as sh                       # noqa: E402
import shortsplan                         # noqa: E402
import shortsgfx                          # noqa: E402

EDITOR = TOOLS.parent
import brandstyle
import channel
import config
import projectstore
import skillrules
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
                        "title": Path(raw["folder"]).name if raw.get("mode") == "raw" and raw.get("folder") else Path(raw.get("source", "")).stem,
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
    return {"exists": True, "file": mp4.name, "mtime": int(mp4.stat().st_mtime), "dur": meta.get("dur"), "audio": meta.get("audio"),
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


def _num_ranges(v, what, sources=None):
    """Clean list of [start, end] spans. For a short made of several recordings (`sources` = their ids) each one is {"src", "a", "b"} and stays so."""
    out = []
    for r in v or []:
        if sources is not None:
            if not (isinstance(r, dict) and r.get("src") in sources):
                raise ValueError(f"{what}: each one needs a recording ({', '.join(sorted(sources))}), a start and an end")
            a, b = float(r["a"]), float(r["b"])
            if not (0 <= a < b):
                raise ValueError(f"{what}: {a}-{b} is not a start before an end")
            out.append({"src": r["src"], "a": round(a, 2), "b": round(b, 2)})
            continue
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
            if "caption_style" in b:
                if b["caption_style"] and b["caption_style"] not in sh.CAPTION_STYLES:
                    raise ValueError("caption style is " + ", ".join(sh.CAPTION_STYLES))
                s["caption_style"] = b["caption_style"] or ""
            if "music" in b:                                       # '' = the app picks, 'none', or a track's name
                s["music"] = str(b["music"]).strip()[:120]
            if "sfx" in b:
                if b["sfx"] not in ("", "on", "off"):
                    raise ValueError("sfx is on, off or empty")
                s["sfx"] = b["sfx"]
            if "emphasis" in b:
                s["emphasis"] = [str(x).strip()[:30] for x in (b["emphasis"] or []) if str(x).strip()][:30]
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


def frame_jpeg(work, name, t: float, width: int = 960, src: str = "") -> bytes:
    import cv2
    raw = read_raw(work, name)
    path = next((s["path"] for s in raw.get("sources", []) if s["id"] == src), raw["source"])
    cap = cv2.VideoCapture(path)
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
    if any(isinstance(r, dict) for r in short["ranges"]):
        raise ValueError("graphics are not planned yet for a short made from raw footage")
    bm = {}
    try:
        bm = json.loads((wd_of(work) / f"{name}.beatmap.json").read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        pass
    ranges = short["ranges"]
    beats = [b for b in bm.get("beats", []) if not b.get("skip") and any(b["start"] < r1 and b["end"] > r0 for r0, r1 in ranges)]
    return shortsgfx.prompt_for(short, sh.kept_words(cfg, short), beats) + feedback_text(read_raw(work, name), [sid])


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


def standalone_names(src: Path) -> tuple:
    """(work folder, project name) for shorts made from a video file that is not one of the app's videos: `_shorts-<slug>` / `<slug>`, a new pair if that one is taken."""
    slug = re.sub(r"[^a-z0-9]+", "-", Path(src).stem.lower()).strip("-")[:40] or "video"
    k, name = 1, slug
    while (WORK / f"_shorts-{name}").exists():
        k += 1
        name = f"{slug}-{k}"
    return f"_shorts-{name}", name


def video_plan(work: str, name: str, cfg: dict | None = None) -> dict:
    """The recommendation for this video: how many shorts, and where its strong visual moments are (shortsplan.py)."""
    if read_raw(work, name).get("mode") == "raw":
        n = skillrules.shorts()["raw_max_shorts"]
        return {"recommended": n, "strong": 0, "moments": [], "runtime_s": 0.0, "has_beatmap": False, "raw": True}
    rec = shortsplan.for_video(work, name)
    if not rec["runtime_s"]:                                         # no beat map for this project: length from the transcript
        cfg = cfg or sh.load(cfg_file(work, name))
        rec = dict(shortsplan.recommend(None, runtime_s=float(cfg["_tr"].get("duration") or 0), spoken=shortsplan.spoken_moments(cfg["_tr"].get("segments") or [])),
                   has_beatmap=False)
    return rec


def footage_folder(work: str, name: str) -> str:
    """The folder of raw recordings a video was made from (its footage.json)."""
    try:
        f = json.loads((wd_of(work) / f"{name}.footage.json").read_text(encoding="utf-8-sig")).get("folder") or ""
    except (OSError, ValueError):
        f = ""
    if not f or not Path(f).is_dir():
        raise ValueError("this video's raw footage folder is not set or not found: choose it in the Footage step first")
    return f


def raw_brief(work: str, name: str, sid: str, text: str) -> str:
    """What to tell Claude when making a new short from the raw footage: the host's words, and the words of the short being redone (it stays as it is)."""
    text = " ".join((text or "").split())
    if not text:
        raise ValueError("say what the new short should tell, or what to fix")
    if not sid:
        return text
    cfg = sh.load(cfg_file(work, name))
    short = _short(read_raw(work, name), sid)
    spoken = " ".join(w["w"] for w in sh.kept_words(cfg, short))
    return f"{text}\n\nIt redoes this short of the finished video, which stays as it is ({short.get('title', '')!r}). Its words were: {spoken}"


def find_prompt(work: str, name: str, count: int | None = None) -> str:
    return _find_prompt(work, name, count) + feedback_text(read_raw(work, name))


def _find_prompt(work: str, name: str, count: int | None = None) -> str:
    if read_raw(work, name).get("mode") == "raw":
        import rawshorts
        return rawshorts.prompt(work, name, count)
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
    if read_raw(work, name).get("mode") == "raw":
        import rawshorts
        return rawshorts.import_candidates(work, name, path, count)
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


def is_multi(short: dict) -> bool:
    """True for a short made from several recordings (raw footage): its ranges and cuts are {"src", "a", "b"}."""
    return any(isinstance(r, dict) for r in short.get("ranges") or [])


MULTI_NOTE = """
This short is joined from several recordings, so every range and every drop span is an object {"src": the recording's id, "a": start, "b": end} instead of [start, end], times in that recording's own seconds.
"""


def tighten_prompt(work: str, name: str, sid: str) -> str:
    cfg = sh.load(cfg_file(work, name))
    short = _short(cfg, sid)
    multi = is_multi(short)
    rules = TIGHTEN_RULES + (MULTI_NOTE if multi else "")
    ctx, sel = [], []
    if multi:                                                   # several recordings: every range names its own
        sources = sh.srcs(cfg)
        for ri, (src, a, b) in enumerate(sh.norm_ranges(cfg, short)):
            tr = sources[src]["tr"]
            ctx.extend(f"[{src} {s['start']:.1f}-{s['end']:.1f}]: {s['text']}" for s in tr["segments"] if s["end"] >= a - 12 and s["start"] <= b + 15)
            ws = [w for w in tr["words"] if w["start"] >= a - 0.06 and w["end"] <= b + 0.04]
            sel.append(f"RANGE {ri + 1} (recording {src}, {a}-{b}):\n" + " ".join(f"{w['word']}<{w['start']:.2f}-{w['end']:.2f}>" for w in ws))
    else:
        words = cfg["_tr"]["words"]
        lo = max(0.0, min(a for a, _ in short["ranges"]) - 12)
        hi = max(b for _, b in short["ranges"]) + 15
        for s in cfg["_spk"] or [{"start": x["start"], "end": x["end"], "speaker": "", "text": x["text"]} for x in cfg["_tr"]["segments"]]:
            if s["end"] >= lo and s["start"] <= hi:
                ctx.append(f"[{s['start']:.1f}-{s['end']:.1f}] {s.get('speaker') or ''}: {s['text']}")
        for ri, (a, b) in enumerate(short["ranges"]):
            ws = [w for w in words if w["start"] >= a - 0.06 and w["end"] <= b + 0.04]
            sel.append(f"RANGE {ri + 1} ({a}-{b}):\n" + " ".join(f"{w['word']}<{w['start']:.2f}-{w['end']:.2f}>" for w in ws))
    return (rules + f"\nThe short: \"{short.get('title', '')}\". On-screen hook title: \"{short.get('hook', '')}\".\n"
            + ("Why it was picked: " + short["why"] + "\n" if short.get("why") else "")
            + "\nCURRENT SELECTION (every word with its start-end seconds; the transcript mishears " + (", ".join(channel.spellings()) or "some words") + "):\n" + "\n".join(sel)
            + "\n\nSURROUNDING TRANSCRIPT (for context and for choosing better start/end points):\n" + "\n".join(ctx) + "\n"
            + feedback_text(read_raw(work, name), [sid]))


def apply_tighten(work: str, name: str, sid: str, path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    raw = read_raw(work, name)
    s = _short(raw, sid)
    cfg = sh.load(cfg_file(work, name))
    ids = set(sh.srcs(cfg)) if is_multi(s) else None
    ranges = _num_ranges(data.get("ranges"), "ranges", ids) or s["ranges"]
    drop = _num_ranges(data.get("drop"), "cuts", ids)
    if not drop and ranges == s["ranges"]:
        raise ValueError("Claude proposed no cuts")
    trial = dict(s, ranges=ranges, drop=drop)
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


# ----------------------------------------------------------------------------- the host's feedback on shorts
# Notes are plain sentences. A note on one short is open until Claude has applied it (then "done"); a general note ("hooks are too long") stands and is
# given to every later run that chooses, tightens, plans or titles shorts. The buttons only save notes; Claude applies them (feedback_prompt).
MAX_NOTES = 40


def feedback_of(raw: dict, sid: str = "") -> list:
    """The notes of one short, or the general ones when `sid` is empty."""
    return list((_short(raw, sid) if sid else raw).get("feedback") or [])


def _note_holder(raw: dict, sid: str) -> dict:
    return _short(raw, sid) if sid else raw


def add_feedback(work, name, sid, text) -> dict:
    text = " ".join(str(text or "").split())[:600]
    if not text:
        raise ValueError("write what you would change")
    raw = read_raw(work, name)
    holder = _note_holder(raw, sid)
    notes = holder.setdefault("feedback", [])
    if len(notes) >= MAX_NOTES:
        raise ValueError("too many notes: delete the ones that are done")
    notes.append({"id": max([n["id"] for n in notes], default=0) + 1, "text": text, "status": "open" if sid else "standing", "at": time.time()})
    save_raw(work, name, raw, why="feedback")
    return state(work, name)


def edit_feedback(work, name, sid, fid, status=None, delete=False) -> dict:
    raw = read_raw(work, name)
    holder = _note_holder(raw, sid)
    notes = holder.get("feedback") or []
    n = next((x for x in notes if x["id"] == int(fid)), None)
    if not n:
        raise ValueError("no such note")
    if delete:
        notes.remove(n)
    else:
        if status not in ("open", "done", "standing"):
            raise ValueError("a note is open, done or standing")
        n["status"] = status
    if not notes:
        holder.pop("feedback", None)
    save_raw(work, name, raw, why="feedback")
    return state(work, name)


def feedback_text(raw: dict, sids=()) -> str:
    """The notes a Claude run must follow, as a block for its prompt ('' when there are none)."""
    general = [f"- {n['text']}" for n in feedback_of(raw) if n.get("status") != "done"]
    out = ("THE HOST'S STANDING FEEDBACK ON SHORTS (earlier shorts fell short in these ways; do not repeat them):\n" + "\n".join(general) + "\n") if general else ""
    for sid in sids:
        mine = [f"- {n['text']}" for n in feedback_of(raw, sid) if n.get("status") == "open"]
        if mine:
            out += f"\nTHE HOST'S FEEDBACK ON SHORT {sid} (apply it):\n" + "\n".join(mine) + "\n"
    return ("\n" + out) if out else ""


def open_feedback(raw: dict, sid: str) -> list:
    return [n for n in feedback_of(raw, sid) if n.get("status") == "open"]


STEP_S = 0.5                                                # how often the video is looked at to find the host's face


def sample_faces(work: str, name: str, lo: float, hi: float) -> list:
    """[(t, face)] every STEP_S seconds of the source video between lo and hi: is the host's face (a big one) the picture? Reads frames, so it takes a few seconds."""
    import cv2
    raw = read_raw(work, name)
    src = raw.get("source", "")
    if raw.get("mode") == "raw" or not Path(src).is_file():
        return []
    cap = cv2.VideoCapture(src)
    out, t = [], max(0.0, lo)
    while t <= hi:
        cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
        ok, fr = cap.read()
        if not ok:
            break
        out.append((round(t, 2), bool(sh.has_big_face(fr, fr.shape[1]))))
        t += STEP_S
    cap.release()
    return out


def no_face_spans(samples: list) -> list:
    """[(a, b)] stretches where no face was seen, from the samples."""
    spans, start = [], None
    for t, face in samples:
        if not face and start is None:
            start = t
        elif face and start is not None:
            spans.append((start, t))
            start = None
    if start is not None and samples:
        spans.append((start, samples[-1][0] + STEP_S))
    return spans


def picture_map(work: str, name: str, short: dict) -> list:
    """Where the finished video shows something other than the host's face around a short, as measured on the video itself: [(a, b)] in video seconds.
    Empty when the video cannot be read (then nothing is known). Measured, not read from the beat map: the beat map can be newer than the render."""
    ranges = [r for r in short.get("ranges") or [] if not isinstance(r, dict)]
    if not ranges:
        return []
    lo, hi = max(0.0, min(a for a, _ in ranges) - 12), max(b for _, b in ranges) + 15
    return no_face_spans(sample_faces(work, name, lo, hi))


def face_share(work: str, name: str, short: dict, cfg: dict | None = None) -> float | None:
    """The share of the words of a short (0 to 1) spoken while the host's face is the picture; None when the video cannot be read."""
    ranges = [r for r in short.get("ranges") or [] if not isinstance(r, dict)]
    if not ranges:
        return None
    lo, hi = min(a for a, _ in ranges), max(b for _, b in ranges)
    samples = sample_faces(work, name, lo, hi)
    if not samples:
        return None
    cfg = cfg or sh.load(cfg_file(work, name))
    kept = sh.kept_words(cfg, short)
    total = sum(w["e"] - w["s"] for w in kept)
    if total <= 0:
        return None
    spans = no_face_spans(samples)
    covered = sum(w["e"] - w["s"] for w in kept if any(a <= (w["s"] + w["e"]) / 2 < b for a, b in spans))
    return round(1 - covered / total, 2)


FEEDBACK_RULES = """The host watched this YouTube Short and wrote feedback on it. Change the short so the feedback is met, and change nothing else.

You may: move the start or end (inside the context given), delete words and spans (never reword, reorder or invent), and rewrite the on-screen hook title or the working title when the feedback asks for it. If a note asks for something you cannot do by those means (a different caption style, music, sound effects, a graphic, a crop), say so in "unmet" and leave it for the host. Keep the short complete and grammatical when its words are joined in order. Obey the host over any default of yours; if two notes disagree, follow the later one.

If the host does not want the talking head: the picture of a short is whatever the finished video shows at that second, and the face is on screen except in the PICTURE list below. So the way to show less of the face is to keep the words that are spoken while a listed picture is on screen, and cut the words spoken over the face (still complete sentences, still the story). You cannot add pictures. If the story cannot be told from those words alone, keep the best version you can and say in "unmet" how much of it is still over the face.

Output: write tighten.json in the current folder (Write tool), exactly this shape and nothing else:
{"ranges": [[start, end], ...], "drop": [[start, end], ...], "kept_text": "the sentences that remain, as they will be spoken", "hook": "new hook or empty to keep it", "title": "new title or empty to keep it", "note": "one or two sentences: what you changed for each note", "unmet": ["a note you could not meet, and why"]}
- Every time is a SOURCE second taken from the word timestamps below. Give the full list of ranges and drop spans the short should have now (they replace the current ones). A drop span covers whole words only. Drop spans must lie inside the ranges.
- Hook: a few words, at most 90 characters; a | marks a line break.
"""


FACE_RULE = FEEDBACK_RULES[FEEDBACK_RULES.index("If the host does not want the talking head"):FEEDBACK_RULES.index("Output: write tighten.json")]
RAW_FACE_RULE = ("This short is made from raw recordings: b-roll is laid over the words separately and this run cannot add, move or remove it. If a note is about the picture "
                 "(no talking head, more b-roll), say in \"unmet\" that it has to be done on the b-roll, and still apply what the words can do.\n\n")


def feedback_prompt(work: str, name: str, sid: str) -> str:
    raw = read_raw(work, name)
    if not open_feedback(raw, sid):
        raise ValueError("write some feedback on this short first")
    body = tighten_prompt(work, name, sid).split("\nThe short: ", 1)[1]
    spans = picture_map(work, name, _short(raw, sid))
    if is_multi(_short(raw, sid)):                             # raw footage: the picture is the talking recording, with b-roll laid over by overlays that this run does not change
        return FEEDBACK_RULES.replace(FACE_RULE, RAW_FACE_RULE) + MULTI_NOTE + "\nThe short: " + body
    pic = ("\nPICTURE (measured on the video): the host's face is NOT on screen during these seconds (b-roll, a graphic or a screen capture); any other second shows the face:\n"
           + "\n".join(f"  {a:.1f}-{b:.1f}" for a, b in spans) + "\n") if spans else (
        "\nPICTURE: the face is on screen the whole time around this short, or the video could not be read, so no second is known to be free of it.\n")
    return FEEDBACK_RULES + "\nThe short: " + body + pic


def apply_feedback(work: str, name: str, sid: str, path: Path) -> dict:
    """Apply Claude's changes for the open notes of one short, then mark those notes done. The old cuts are kept so 'undo' works."""
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    raw = read_raw(work, name)
    s = _short(raw, sid)
    cfg = sh.load(cfg_file(work, name))
    ids = set(sh.srcs(cfg)) if is_multi(s) else None
    ranges = _num_ranges(data.get("ranges"), "ranges", ids) or s["ranges"]
    drop = _num_ranges(data.get("drop"), "cuts", ids) if "drop" in data else s.get("drop", [])
    changed_cuts = ranges != s["ranges"] or drop != s.get("drop", [])
    if changed_cuts:
        trial = dict(s, ranges=ranges, drop=drop)
        kept = sh.kept_words(cfg, trial)
        speech = sum(w["e"] - w["s"] for w in kept)
        if len(kept) < 8 or speech < 4:
            raise ValueError(f"the changes leave only {len(kept)} words: refused")
        if "before_tighten" not in s:
            s["before_tighten"] = {"ranges": s["ranges"], "drop": s.get("drop", [])}
        s["ranges"], s["drop"] = ranges, drop
        if not drop:
            s.pop("drop", None)
        s["tighten"] = {"note": str(data.get("note", ""))[:400], "text": str(data.get("kept_text", ""))[:1500], "words_kept": len(kept), "at": time.time()}
    hook, title = str(data.get("hook") or "").strip()[:90].upper(), str(data.get("title") or "").strip()[:90]
    if hook:
        s["hook"] = hook
    if title:
        s["title"] = title
    unmet = [str(x)[:300] for x in (data.get("unmet") or []) if str(x).strip()][:10]
    if not (changed_cuts or hook or title):
        raise ValueError("Claude changed nothing" + (": " + "; ".join(unmet) if unmet else ""))
    for n in s.get("feedback") or []:
        if n.get("status") == "open":
            n["status"] = "done"
    s["feedback_result"] = {"note": str(data.get("note", ""))[:400], "unmet": unmet, "at": time.time()}
    save_raw(work, name, raw, why="feedback applied")
    return {"changed_cuts": changed_cuts, "hook": bool(hook), "title": bool(title), "unmet": unmet}


def record_face_share(work: str, name: str, sid: str):
    """After feedback was applied: measure how much of the short is still spoken over the face and keep it with the result (reads frames: call it outside the lock)."""
    raw = read_raw(work, name)
    s = _short(raw, sid)
    face = face_share(work, name, s)
    if face is not None and s.get("feedback_result") is not None:
        s["feedback_result"]["face"] = face
        save_raw(work, name, raw, why="feedback measured")
    return face


# ----------------------------------------------------------------------------- YouTube title, description, tags, file name
def _slug(text: str) -> str:
    t = re.sub(r"[^a-z0-9]+", "-", str(text).lower().replace("&", " and ")).strip("-")
    return t[:70].strip("-") or "short"


PUBLISH_RULES = """Write the YouTube Shorts metadata for these shorts from the channel (its subject is in the channel profile above). Goal: found in search and suggested, clicked, watched to the end. Everything must be TRUE to what the short says.

For each short give:
- title: aim for 40 to 60 characters (hard limit 80). Put the main search phrase in the first 40 characters (what a person types to find this). A concrete benefit, answer, number or question. Plain words. No clickbait lies, no ALL CAPS, no "#Shorts" in the title, at most one emoji and only if it adds meaning.
- description: 2 or 3 short sentences. The first sentence contains the main phrase and gives the answer or the hook (it shows before "more"). Then one line of context. If a full-video link is given below, add a line "Full video: <link>"; if none is given, do not mention a link. If the channel profile above names the channel and what it is about, add one line saying so; if it does not, leave that line out. Then 4 or 5 hashtags on the last line: #Shorts plus ones for the subject of the short and of the channel.
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
    return (PUBLISH_RULES + f"\nThe full video these were cut from: \"{raw_title}\".\nFull-video link: {link or '(not given yet: leave the link line out)'}\n\n" + "\n\n".join(parts) + "\n"
            + feedback_text(read_raw(work, name), ids))


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
