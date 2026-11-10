"""Graphics plan for a short (ADR 0006, phase 2): where each graphic goes, what it will be, and draft stills of it.

For each short the host keeps, one small Claude run proposes a handful of graphics for it. Nothing is built yet: the host sees a strip (the short's
cuts and words with each graphic as a bar over the words it lands on), a card per graphic (what it shows, how it moves, its look) and 3 to 5
DRAFT stills placed on the real vertical frame. He marks each graphic OK, change (with a note) or cut. Only OK'd graphics get built (next step).

Stored in the short (<name>.shorts.json):
    short["gfx"] = {"at": ts, "note": str, "skipped": [why, ...], "graphics": [
        {"id": "g1", "t0": s, "t1": s, "words": "the words it lands on", "what": "...", "how": "...", "look": "kinetic", "place": "top|full|bottom",
         "text": "headline on the card", "beats": [{"t": s, "what": "..."}], "reuse": "B07" or "", "status": "" | "ok" | "change" | "cut", "note": ""}]}
All times are MAIN-VIDEO seconds (the same clock as the short's ranges); the strip converts them to short time.
"""
import time

import brandstyle
import channel
import shorts as sh
import gfxplan

PLACES = ("top", "full", "bottom")
STATUSES = ("", "ok", "change", "cut")
MIN_GFX_S, MAX_GFX_S = 1.0, 8.0
ONE_PER_S = 6.0                       # about one graphic per 6 s of short, plus one
MAX_STILLS = 5
REGIONS = {"top": (48, 150, 1032, 720), "full": (48, 330, 1032, 1500), "bottom": (48, 1380, 1032, 1840)}   # on the 1080x1920 frame

GFX_RULES = """You are planning the GRAPHICS for one YouTube Short from the channel. The short is vertical (1080x1920), fast paced, made of clips of the main video. Nothing is built from your plan yet: the host will look at it first and keep or cut each graphic, so make it clear WHERE each graphic goes and WHAT it will be.

Rules:
- Plan about one graphic per {per} seconds of the short (never more than {maxn} for this one, fewer is fine, one is fine). Each lasts {min_s} to {max_s} seconds.
- Time each graphic to the words: t0 is the start of the first word it lands on (up to 0.2 s earlier), t1 the end of the last word it covers. Use MAIN-VIDEO seconds from the word list below, inside the short's ranges. Graphics must not overlap each other.
- A graphic must SHOW what is being said: the mechanism, the number, the comparison, the before and after. Not decoration. Prefer the moments the main video already has a graphic for (listed below): set "reuse" to that beat id and say how it should be re-laid-out for a vertical frame.
- place: "top" (a card above the speaker, who stays visible below), "full" (replaces the speaker, for an explainer that needs the room), or "bottom". Captions sit around the middle-bottom of the frame, so keep "bottom" for small things.
- look: one of {looks}. Use "kinetic" for a key-word pop-up (0.6 to 1.5 s); the others for real explainers.
- text: the headline on the card, 6 words or fewer. For a list or a comparison put the headline first and then up to 4 items, each on its own line (a line break in the string), 4 words or fewer each: the items appear one at a time while the words are said. For "kinetic" give the one to three words that pop. what: one sentence, what it shows. how: one sentence, how it moves (what appears first, what lights up on which word).
- beats: 3 to 5 key moments in the graphic as {{"t": main-video seconds, "what": what is on screen at that moment}}: the first moment it is fully on screen, the word where the point lands, the end state. The host sees one draft still per beat.

Write the result to graphics.json in the current folder (use the Write tool), exactly this shape and nothing else:
{{"note": "one sentence on the idea of the plan", "graphics": [{{"t0": 21.4, "t1": 26.0, "words": "the words it lands on", "what": "...", "how": "...", "look": "ui", "place": "top", "text": "SHORT HEADLINE", "beats": [{{"t": 22.0, "what": "..."}}], "reuse": ""}}]}}
"""


# ----------------------------------------------------------------------------- the brief
def _short_total(ranges) -> float:
    return sum(b - a for a, b in ranges)


def max_graphics(ranges) -> int:
    return max(1, round(_short_total(ranges) / ONE_PER_S) + 1)


def prompt_for(short: dict, words: list[dict], beats: list[dict]) -> str:
    """`words`: kept words {w, s, e} in main-video seconds; `beats`: the main video's beats that overlap the short's ranges."""
    ranges = short["ranges"]
    n = max_graphics(ranges)
    lines, cur, t0 = [], [], None
    for w in words:                                   # one line per ~12 words, each with its start-end
        if t0 is None:
            t0 = w["s"]
        cur.append(w["w"])
        if len(cur) >= 12 or w is words[-1]:
            lines.append(f"[{t0:.2f}-{w['e']:.2f}] " + " ".join(cur))
            cur, t0 = [], None
    have = []
    for b in beats:
        g = b.get("graphic")
        if g and not g.get("struck") and b.get("start") is not None:
            have.append(f"- {b['id']} {b['start']:.1f}-{b['end']:.1f}: {g.get('kind', '')} ({g.get('style') or 'no look chosen'}): {g.get('idea') or g.get('text') or ''} (timed to: {g.get('words', '')})")
    th = short.get("thought") or {}
    return (GFX_RULES.format(per=int(ONE_PER_S), maxn=n, min_s=MIN_GFX_S, max_s=MAX_GFX_S, looks=", ".join(f'"{s["id"]}"' for s in gfxplan.STYLES))
            + f'\nTHE SHORT: "{short.get("title", "")}" (hook on screen: "{short.get("hook", "")}")\n'
            + (f"Story: setup: {th.get('setup', '')} / point: {th.get('point', '')} / payoff: {th.get('payoff', '')}\n" if th.get("point") else "")
            + (f"Why it was picked: {short['why']}\n" if short.get("why") else "")
            + "Ranges played, in order (main-video seconds): " + ", ".join(f"{a:.1f}-{b:.1f}" for a, b in ranges) + "\n"
            + "\nGRAPHICS THE MAIN VIDEO ALREADY HAS in these ranges:\n" + ("\n".join(have) if have else "(none)") + "\n"
            + "\nTHE WORDS OF THE SHORT (the transcript mishears " + (", ".join(channel.spellings()) or "some words") + "):\n" + "\n".join(lines) + "\n")


# ----------------------------------------------------------------------------- checking Claude's plan
def _inside(t0: float, t1: float, ranges) -> bool:
    return any(t0 >= a - 0.3 and t1 <= b + 0.3 for a, b in ranges)


def validate_plan(graphics, ranges) -> tuple[list[dict], list[str]]:
    """(graphics that follow the rules, with ids g1, g2, ...; the reasons the others were left out)."""
    kept, skipped = [], []
    limit = max_graphics(ranges)
    for i, g in enumerate(graphics if isinstance(graphics, list) else [], 1):
        tag = f"graphic {i}"
        try:
            t0, t1 = float(g["t0"]), float(g["t1"])
        except (KeyError, TypeError, ValueError):
            skipped.append(f"{tag}: it has no start and end time")
            continue
        what, how = str(g.get("what", "")).strip(), str(g.get("how", "")).strip()
        if not what or not how:
            skipped.append(f"{tag}: it does not say what it shows and how it moves")
            continue
        if not (MIN_GFX_S - 0.01 <= t1 - t0 <= MAX_GFX_S + 0.01):
            skipped.append(f"{tag}: {t1 - t0:.1f} s is outside {MIN_GFX_S:g} to {MAX_GFX_S:g} s")
            continue
        if not _inside(t0, t1, ranges):
            skipped.append(f"{tag}: it is not inside one of the short's clips")
            continue
        if any(min(t1, k["t1"]) - max(t0, k["t0"]) > 0.5 for k in kept):
            skipped.append(f"{tag}: it overlaps an earlier graphic")
            continue
        if len(kept) >= limit:
            skipped.append(f"{tag}: more than the {limit} planned for a short this long")
            continue
        look = str(g.get("look", ""))
        beats = []
        for b in g.get("beats") or []:
            try:
                bt = float(b["t"])
            except (KeyError, TypeError, ValueError):
                continue
            if t0 - 0.3 <= bt <= t1 + 0.3:
                beats.append({"t": round(bt, 2), "what": str(b.get("what", ""))[:200]})
        kept.append({"id": f"g{len(kept) + 1}", "t0": round(t0, 2), "t1": round(t1, 2), "words": str(g.get("words", ""))[:200], "what": what[:300], "how": how[:300],
                     "look": look if look in gfxplan.STYLE_IDS else "", "place": g.get("place") if g.get("place") in PLACES else "top",
                     "text": str(g.get("text", ""))[:160], "beats": beats[:MAX_STILLS], "reuse": str(g.get("reuse", ""))[:20], "status": "", "note": ""})
    return kept, skipped


def key_moments(g: dict) -> list[dict]:
    """3 to 5 moments to draw a still of: Claude's beats, topped up with the entry, the middle and the end when it gave fewer than 3."""
    out = [{"t": b["t"], "what": b.get("what", "")} for b in g.get("beats") or []][:MAX_STILLS]
    if len(out) < 3:
        d = g["t1"] - g["t0"]
        for t, w in ((g["t0"] + min(0.5, d * 0.2), "it is fully on screen"), ((g["t0"] + g["t1"]) / 2, "the point lands"), (g["t1"] - min(0.4, d * 0.15), "the end state")):
            if len(out) >= 3:
                break
            if all(abs(t - o["t"]) > 0.25 for o in out):
                out.append({"t": round(t, 2), "what": w})
    return sorted(out, key=lambda m: m["t"])[:MAX_STILLS]


# ----------------------------------------------------------------------------- storing the plan and the creator's marks
def import_plan(short: dict, data: dict) -> dict:
    """Put Claude's plan into the short (replacing an earlier plan); returns {'added': n, 'skipped': [...]}."""
    kept, skipped = validate_plan((data or {}).get("graphics"), short["ranges"])
    short["gfx"] = {"at": time.time(), "note": str((data or {}).get("note", ""))[:300], "skipped": skipped, "graphics": kept}
    return {"added": len(kept), "skipped": skipped}


def mark(short: dict, gid: str, status: str, note: str = "") -> dict:
    if status not in STATUSES:
        raise ValueError("status must be ok, change, cut or empty")
    g = next((x for x in (short.get("gfx") or {}).get("graphics", []) if x["id"] == gid), None)
    if not g:
        raise ValueError(f"no graphic {gid!r}")
    g["status"] = status
    g["note"] = note.strip()[:400]
    return g


# ----------------------------------------------------------------------------- where it goes: main-video time -> short time
def to_short(pieces: list[dict], speed: float, t: float) -> float:
    """Seconds into the finished short for main-video second `t` (a time in a cut-out part snaps to the nearest kept one)."""
    best, dist = 0.0, 1e9
    for pc in pieces:
        if pc["a"] - 0.01 <= t <= pc["b"] + 0.01:
            return round((pc["t0"] + (t - pc["a"])) / speed, 3)
        d = min(abs(t - pc["a"]), abs(t - pc["b"]))
        if d < dist:
            best, dist = (pc["t0"] if abs(t - pc["a"]) <= abs(t - pc["b"]) else pc["t0"] + pc["dur"]) / speed, d
    return round(best, 3)


def piece_at(pieces: list[dict], t: float) -> dict | None:
    return next((pc for pc in pieces if pc["a"] - 0.01 <= t <= pc["b"] + 0.01), pieces[0] if pieces else None)


def view(cfg: dict, short: dict, pieces: list[dict], sid: str) -> dict:
    """What the strip needs: the short's length, its cuts and words in SHORT time, and each graphic placed over them."""
    speed = sh.pace_of(short)["speed"]
    total = (pieces[-1]["t0"] + pieces[-1]["dur"]) / speed if pieces else 0.0
    words = [{"w": w["w"], "s": to_short(pieces, speed, w["s"]), "e": to_short(pieces, speed, w["e"])} for w in sh.kept_words(cfg, short)]
    out = []
    for g in (short.get("gfx") or {}).get("graphics", []):
        moments = [{"t": m["t"], "ts": to_short(pieces, speed, m["t"]), "what": m["what"]} for m in key_moments(g)]
        out.append({**g, "ts0": to_short(pieces, speed, g["t0"]), "ts1": to_short(pieces, speed, g["t1"]), "moments": moments})
    gfx = short.get("gfx") or {}
    return {"id": sid, "total": round(total, 2), "cuts": [round(pc["t0"] / speed, 2) for pc in pieces], "words": words, "planned": bool(gfx),
            "note": gfx.get("note", ""), "skipped": gfx.get("skipped", []), "max": max_graphics(short["ranges"]), "graphics": out}


# ----------------------------------------------------------------------------- draft stills on the real vertical frame
def still_jpeg(cfg: dict, short: dict, pieces: list[dict], gid: str, k: int, width: int = 360) -> bytes:
    import cv2
    import io
    from PIL import Image, ImageDraw, ImageFilter
    import storyboard
    g = next((x for x in (short.get("gfx") or {}).get("graphics", []) if x["id"] == gid), None)
    if not g:
        raise ValueError(f"no graphic {gid!r}")
    moments = key_moments(g)
    if not 0 <= k < len(moments):
        raise ValueError("no such still")
    t, what = moments[k]["t"], moments[k]["what"]
    cap = cv2.VideoCapture(cfg["source"])
    cap.set(cv2.CAP_PROP_POS_MSEC, float(t) * 1000)
    ok, fr = cap.read()
    cap.release()
    if not ok:
        raise ValueError("could not read the frame for this still")
    src = Image.fromarray(cv2.cvtColor(fr, cv2.COLOR_BGR2RGB))
    pc = piece_at(pieces, t) or {"layout": "live", "cx": 0.5, "cy": 0.5, "zoom": 1.0}
    W, H = sh.W, sh.H
    card_c = brandstyle.rgb(brandstyle.palette()["primary"])
    sw, sh_ = src.size
    if pc.get("layout") == "graphic":
        gz = pc.get("gzoom", 1.0)
        gw, gh = int(1600 / gz), int(1080 / gz)
        gw, gh = min(gw, sw), min(gh, sh_)
        gx = int(min(max(pc.get("gcx", 0.5) * sw - gw / 2, 0), sw - gw))
        gy = int(min(max(pc.get("gcy", 0.5) * sh_ - gh / 2, 0), sh_ - gh))
        base = Image.new("RGB", (W, H), card_c)
        base.paste(src.crop((gx, gy, gx + gw, gy + gh)).resize((W, 730)), (0, 400))
    elif pc.get("layout") == "blur":
        bg = src.resize((W, H)).filter(ImageFilter.GaussianBlur(24))
        fg = src.resize((W, int(W * sh_ / sw)))
        base = bg
        base.paste(fg, (0, (H - fg.height) // 2 - 90))
    else:
        cw, ch, x, y = sh.crop_box(pc)
        base = src.crop((x, y, x + cw, y + ch)).resize((W, H))
    card = {"kind": g.get("look") or "brand", "text": g.get("text") or g.get("what", ""), "words": g.get("words", ""), "idea": g.get("what", "")}
    base = storyboard.draw_card(base, REGIONS[g.get("place", "top")], card, opaque=g.get("place") == "full")
    d = ImageDraw.Draw(base)
    d.rectangle((0, H - 120, W, H), fill=brandstyle.rgb(brandstyle.palette()["dark"]))
    storyboard.wrap_text(d, f"STILL {k + 1} OF {len(moments)} · {what}", (30, H - 110, W - 30, H - 20), brandstyle.rgb(brandstyle.palette()["light"]), 34, valign="center")
    base = base.resize((width, int(width * H / W)))
    buf = io.BytesIO()
    base.save(buf, "JPEG", quality=82)
    return buf.getvalue()
