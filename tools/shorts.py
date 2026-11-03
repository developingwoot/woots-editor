"""Shorts: cut vertical YouTube Shorts (1080x1920) out of a finished video.

Usage:
    python shorts.py plan   <shorts.json> <id>            # build the pieces, print them, write <id>.plan.json
    python shorts.py sheet  <shorts.json> <id>            # contact sheet: each piece's frame with its crop box drawn
    python shorts.py render <shorts.json> <id> [--out F]  # render the vertical preview (NVENC)

<shorts.json> (one per finished video, in its work folder):
    {"source": "<final.mp4>", "transcript": "<transcript.json>", "speakers": "<speakers.json>",   # one source, or "sources": see below
     "shorts": [{"id": "s1", "title": "...", "hook": "NEVER USE A COLD IRON",
                 "ranges": [[20.6, 40.6], [58.3, 71.8]],      # source seconds, played in this order
                 "drop": [[24.4, 25.0]],                      # source seconds to cut out of the ranges
                 "words": {"24.5": "Spheres."},               # caption fixes by word start time
                 "crops": [{"t": 22.0, "cx": 0.27, "cy": 0.4, "zoom": 1.1}]}]}   # per-piece overrides, by source time

Several sources (a short made from more than one file): "sources": [{"id": "a", "path": "talk.mp4", "transcript": "talk.transcript.json", "kind": "talk"},
{"id": "b", "path": "bench.mp4", "kind": "broll"}], and each range names its source: {"src": "b", "a": 4.0, "b": 9.5}. A range written [a, b] is in the
first source, so a file with one "source" is the same as a file with one source "a". Times in "drop", "words" ("b:24.5" for source b) and "crops" ("src") follow the same rule.

How a short is made (all local and free):
  * Dead air is cut: only the words are kept, with 0.05 s before and 0.12 s after each phrase.
  * Fast cuts: a continuous run longer than ~3 s is split at a comma or the biggest gap, and the picture alternates between
    two zoom levels at each split (the audio does not jump), so something changes every 2 to 3 seconds.
  * Live shots are cropped to a 9:16 window on the speaker; graphics (full-screen cards in the primary colour) are fitted on a
    background in the upper middle. Crops are guesses (face finder plus "The host on the right, the co-host on the left"); the contact
    sheet is how they are checked, and "crops" overrides them.
  * Captions: ASS, big uppercase, 1 to 3 words at a time, the spoken word turns the accent colour and pops. A hook title shows in the
    first 2.8 s, a thin progress bar in the accent colour runs along the bottom, audio is loudness-matched to -14 LUFS.
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import time
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import brandstyle  # noqa: E402
import channel  # noqa: E402
import encoders  # noqa: E402
import skillrules  # noqa: E402

W, H = 1080, 1920
DEFAULT_SIZE = (1920, 1080)        # when a source cannot be probed
# How the short is paced. gap = a silence longer than this is cut out; zooms = at every real cut (silence removed, words cut out) the picture steps to the next
# of these crop zooms, a small step like a jump cut (gzooms: the same for graphic cards); speed = the whole short is played this much faster (voice pitch is kept);
# before/after = seconds kept around each phrase. "natural" is the default. (An earlier "aggressive" pace pulsed the zoom every 1.8 s inside sentences: The creator hated it,
# 2026-10-23. Aggressive CUTTING means cutting words and sentences out of the content: see the "drop" list and shortsapp's tighten.)
PACES = {
    "relaxed": {"gap": 0.40, "zooms": (1.0,), "gzooms": (1.0,), "speed": 1.0, "before": 0.06, "after": 0.15, "label": "Relaxed (keeps most pauses, no zoom steps)"},
    "natural": {"gap": 0.28, "zooms": (1.0, 1.08), "gzooms": (1.0,), "speed": 1.0, "before": 0.05, "after": 0.12, "label": "Natural (small zoom step at each cut)"},
    "tight":   {"gap": 0.18, "zooms": (1.0, 1.08), "gzooms": (1.0,), "speed": 1.05, "before": 0.03, "after": 0.08, "label": "Tight (shorter pauses, 5 % faster)"},
}
LEGACY_PACE = {"calm": "relaxed", "fast": "natural", "aggressive": "tight"}


def pace_of(short):
    k = short.get("pace") or "natural"
    return PACES.get(LEGACY_PACE.get(k, k), PACES["natural"])


FILLERS = {"okay", "yeah", "right", "yes", "mm", "hmm", "uh", "um", "alright"}
# the channel's own words that speech recognition mishears come from the profile's terms (channel.corrections), applied to every caption


def load(path):
    p = Path(path)
    cfg = json.loads(p.read_text(encoding="utf-8"))
    base = p.parent
    cfg["_base"] = base
    specs = cfg.get("sources") or [{"id": "a", "path": cfg["source"], "transcript": cfg["transcript"], "kind": "talk"}]
    cfg["_first"] = specs[0]["id"]
    cfg.setdefault("source", specs[0]["path"])
    srcs = {}
    for sp_ in specs:
        tf = sp_.get("transcript")
        if tf or sp_.get("kind", "talk") == "talk":
            tr = json.loads(Path(tf).read_text(encoding="utf-8"))
        else:
            tr = {"words": [], "segments": []}                  # b-roll has nothing said in it
        srcs[sp_["id"]] = {"id": sp_["id"], "path": sp_["path"], "kind": sp_.get("kind", "talk"), "tr": tr,
                           "size": probe_size(sp_["path"]), "audio": has_audio(sp_["path"])}
    cfg["_srcs"] = srcs
    cfg["_tr"] = srcs[cfg["_first"]]["tr"]
    cfg["_size"] = srcs[cfg["_first"]]["size"]
    sp = cfg.get("speakers")
    cfg["_spk"] = json.loads(Path(sp).read_text(encoding="utf-8")) if sp and Path(sp).exists() else []
    return cfg


def has_audio(path) -> bool:
    try:
        out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries", "stream=codec_type", "-of", "csv=p=0", str(path)],
                             capture_output=True, text=True, check=True).stdout
        return "audio" in out
    except (OSError, subprocess.SubprocessError):
        return True


def srcs(cfg) -> dict:
    """The sources of a project by id. A config built by hand (tests, tools) with only "source" and "_tr" is one source "a"."""
    if "_srcs" not in cfg:
        cfg["_first"] = "a"
        cfg["_srcs"] = {"a": {"id": "a", "path": cfg.get("source", ""), "kind": "talk", "tr": cfg.get("_tr") or {"words": [], "segments": []},
                              "size": cfg.get("_size") or DEFAULT_SIZE, "audio": True}}
    return cfg["_srcs"]


def norm_ranges(cfg, short) -> list:
    """[(source id, start, end), ...] in play order, for ranges written [a, b] (first source) or {"src", "a", "b"}."""
    srcs(cfg)
    return [(r["src"], float(r["a"]), float(r["b"])) if isinstance(r, dict) else (cfg["_first"], float(r[0]), float(r[1])) for r in short["ranges"]]


def probe_size(path) -> tuple:
    """(width, height) of a video file as it is shown (rotation applied); DEFAULT_SIZE when it cannot be read."""
    try:
        out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height:stream_side_data=rotation",
                              "-of", "json", str(path)], capture_output=True, text=True, check=True).stdout
        st = json.loads(out)["streams"][0]
        w, h = int(st["width"]), int(st["height"])
        if any(abs(int(float(d.get("rotation", 0)))) % 180 == 90 for d in st.get("side_data_list", [])):
            w, h = h, w
        return w, h
    except (OSError, subprocess.SubprocessError, ValueError, KeyError, IndexError):
        return DEFAULT_SIZE


def speaker_at(cfg, t, src=None):
    srcs(cfg)
    if src not in (None, cfg.get("_first", src)):
        return channel.host()                                   # the speaker list belongs to the first source
    for s in cfg["_spk"]:
        if s["start"] - 0.05 <= t <= s["end"] + 0.05:
            return s["speaker"]
    return channel.host()


def fix_word(w):
    core = re.sub(r"[^\w']", "", w)
    for pat, rep in channel.corrections():
        if re.match(pat, core, re.I):
            return w.replace(core, rep) if core in w else rep
    return w


def kept_words(cfg, short, flag=False):
    """Words of the short in play order, backchannel and dropped spans removed. With flag=True every word of the ranges comes back,
    each with 'cut' (True for a removed word) and 'why' (filler, drop or caption fix), for the Words panel."""
    first = cfg["_first"] if srcs(cfg) else ""
    fillers = {}
    for sid, src in srcs(cfg).items():
        fillers[sid] = []
        for s in src["tr"]["segments"]:
            toks = re.findall(r"[\w']+", s["text"].lower())
            if 0 < len(toks) <= 2 and all(t in FILLERS for t in toks):
                fillers[sid].append((s["start"] - 0.05, s["end"] + 0.05))
    drops = [(d["src"], d["a"], d["b"]) if isinstance(d, dict) else (first, d[0], d[1]) for d in short.get("drop", [])]
    over = {}
    for k, v in short.get("words", {}).items():
        sid, _, t = str(k).rpartition(":")
        over[(sid or first, round(float(t), 2))] = v
    out = []
    for ri, (src, a, b) in enumerate(norm_ranges(cfg, short)):
        words = cfg["_srcs"][src]["tr"]["words"]
        filler_spans = fillers[src]
        src_drops = [(da, db) for ds, da, db in drops if ds == src]
        skipped = False
        for w in words:
            if w["start"] < a - 0.06 or w["end"] > b + 0.04:   # a word that starts a hair before the range still belongs to it
                continue
            why = ""
            if any(fa <= w["start"] and w["end"] <= fb for fa, fb in filler_spans):
                why = "backchannel"
            elif any(fa <= w["start"] and w["end"] <= fb for fa, fb in src_drops):
                why = "cut"
            txt = over.get((src, round(w["start"], 2)), fix_word(w["word"]))
            if not why and txt == "":
                why = "removed"
            if why and not flag:
                skipped = True
                continue
            item = {"w": txt or w["word"], "s": w["start"], "e": w["end"], "r": ri, "cb": skipped, "src": src}
            if flag:
                item.update(cut=bool(why), why=why)
            elif skipped:
                item["cb"] = True
            skipped = False
            out.append(item)
    return out


def build_pieces(cfg, short):
    pace = pace_of(short)
    rngs = norm_ranges(cfg, short)
    ws = kept_words(cfg, short)
    runs, cur = [], []
    for w in ws:
        if cur and (w["r"] != cur[-1]["r"] or w.get("cb") or w["s"] - cur[-1]["e"] > pace["gap"]):   # a removed word in between is a cut, whatever the gap
            runs.append(cur)
            cur = []
        cur.append(w)
    if cur:
        runs.append(cur)
    pieces = []
    for run in runs:
        parts = [run]
        while True:
            longest = max(parts, key=lambda p: p[-1]["e"] - p[0]["s"])
            if longest[-1]["e"] - longest[0]["s"] <= pace.get("run", 999) or len(longest) < 5:
                break
            i = parts.index(longest)
            mid = (longest[0]["s"] + longest[-1]["e"]) / 2
            best, bi = None, None
            for k in range(2, len(longest) - 1):
                gap = longest[k]["s"] - longest[k - 1]["e"]
                comma = 0.15 if longest[k - 1]["w"].endswith((",", ".", "?", "!")) else 0
                score = abs(longest[k]["s"] - mid) - gap * 2 - comma
                if best is None or score < best:
                    best, bi = score, k
            parts[i:i + 1] = [longest[:bi], longest[bi:]]
        for j, p in enumerate(parts):
            pieces.append({"words": p, "cont": j > 0})
    t0 = 0.0
    for i, pc in enumerate(pieces):
        ws_ = pc["words"]
        pc["a"] = ws_[0]["s"] - (0.0 if pc["cont"] else pace["before"])
        if not pc["cont"]:
            pc["a"] = max(pc["a"], rngs[ws_[0]["r"]][1])   # never reach back before the range (title card, other shot)
        nxt = pieces[i + 1] if i + 1 < len(pieces) else None
        tail = pace["after"]
        pc["b"] = ws_[-1]["e"] + (0.0 if nxt and nxt["cont"] else tail)
        if pc["cont"]:
            pc["a"] = pieces[i - 1]["b"]
        pc["t0"] = t0
        pc["dur"] = pc["b"] - pc["a"]
        pc["src"] = ws_[0]["src"]
        source = cfg["_srcs"][pc["src"]]
        pc["sw"], pc["sh"] = source["size"]
        pc["noaudio"] = not source["audio"]
        t0 += pc["dur"]
    return pieces


def motion_cx(cap, pc, speaker, prior):
    """Where the speaker is in a wide two-shot: the column with the most movement (head, hands) on the speaker's side.
    The host stands right of the printer, the co-host left of it, in every angle of the sphere video."""
    import cv2
    import numpy as np
    lo, hi = (0.40, 0.92) if speaker == channel.host() else (0.05, 0.40)
    n = 10
    prev, acc = None, None
    for k in range(n):
        t = pc["a"] + (pc["b"] - pc["a"]) * (k + 0.5) / n
        cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
        ok, fr = cap.read()
        if not ok:
            continue
        g = cv2.GaussianBlur(cv2.cvtColor(cv2.resize(fr, (480, 270)), cv2.COLOR_BGR2GRAY), (5, 5), 0).astype(np.float32)
        if prev is not None:
            d = np.abs(g - prev)[: int(270 * 0.85)].sum(axis=0)
            acc = d if acc is None else acc + d
        prev = g
    if acc is None or acc.max() <= 0:
        return prior
    acc = np.convolve(acc, np.ones(41) / 41, mode="same")
    a, b = int(lo * 480), int(hi * 480)
    return float((a + int(np.argmax(acc[a:b]))) / 480)


OVERRIDE_KEYS = ("cx", "cy", "zoom", "layout", "gzoom", "gcx", "gcy")


def pick_face(fs, speaker, sides):
    """Which detected face is the speaker's, from mpfaces.faces() output [(cx, cy, width, score)]: a big face is a close-up; with two or more
    faces the host stands on one side (cfg 'sides', default the host right and the co-host left); one small face counts only if it is on the speaker's side."""
    good = [f for f in fs if f[1] < 0.55]                      # lower than that is the bench and the props
    if not good:
        return None
    f = max(good, key=lambda f: f[2])
    if f[2] >= 0.11 and all(o[2] < 0.6 * f[2] for o in good if o is not f):      # one clearly biggest face: a close-up of that person
        return f[0], f[1], True
    side = sides.get(speaker) or ("right" if speaker == channel.host() else "left")
    f = sorted(good, key=lambda f: f[0])[-1 if side == "right" else 0]
    if (f[0] >= 0.4) if side == "right" else (f[0] <= 0.45):     # the host's face must be on the host's side, or it is somebody else's
        return f[0], f[1], False
    return None


def has_big_face(fr, sw) -> bool:
    """A speaker in the frame (a face at least 11 % of its width): then it is a live shot, whatever colour its corners are."""
    import facedet
    import mpfaces
    if mpfaces.available():
        return any(f[2] >= 0.11 for f in mpfaces.faces(fr))
    return any(f[2] / sw >= 0.11 for f in facedet.faces(fr, 0.02))


def auto_classify(cfg, pieces):
    """Layout, crop centre and zoom for every piece: the guesses (short['crops'] is applied afterwards by apply_overrides)."""
    import cv2
    import numpy as np
    sys.path.insert(0, str(Path(__file__).parent))
    import facedet
    import mpfaces
    zooms = pace_of(cfg_short(cfg))["zooms"]
    gzooms = pace_of(cfg_short(cfg))["gzooms"]
    gi = 0
    sides = cfg.get("sides", {})
    caps = {sid: cv2.VideoCapture(src["path"]) for sid, src in srcs(cfg).items()}
    primary = brandstyle.palette()["primary"]
    card = brandstyle.bgr(primary)                                  # a full-screen card is the channel's primary colour all the way to the corners
    known = primary != brandstyle.FALLBACK["primary"]               # with no brand colour set there is no card colour to look for (dark corners are not a card)
    zi = 0
    hists = {}
    for i, pc in enumerate(pieces):
        mid = (pc["a"] + pc["b"]) / 2
        cap = caps[pc["src"]]
        cap.set(cv2.CAP_PROP_POS_MSEC, mid * 1000)
        ok, fr = cap.read()
        pc["layout"], pc["cx"], pc["cy"] = "live", 0.5, 0.42
        pc["speaker"] = speaker_at(cfg, mid, pc["src"])
        if cfg["_srcs"][pc["src"]]["kind"] == "broll":            # no one to follow: keep the whole picture
            pc["layout"], pc["zoom"], pc["face"], pc["close"] = "blur", 1.0, False, False
            continue
        if not ok:
            continue
        hists[i] = frame_hist(fr)
        sw, sh_ = pc["sw"], pc["sh"]
        corner = [fr[y, x].astype(int) for x, y in ((8, 8), (sw - 9, 8), (8, sh_ - 9), (sw - 9, sh_ - 9))]
        if known and sum(1 for c in corner if max(abs(int(c[k]) - card[k]) for k in range(3)) < 16) >= 3 and not has_big_face(fr, sw):   # dark corners alone are not a card: a card has no speaker
            pc["layout"] = "graphic"
            pc["zoom"] = 1.0
            pc["gzoom"], pc["gcy"] = gzooms[gi % len(gzooms)], 0.55
            gi += 1
            continue
        prior = 0.78 if pc["speaker"] == channel.host() else 0.27
        picks = []
        if mpfaces.available():                                 # three frames across the piece, the median of what the face finder says
            for f in (0.25, 0.5, 0.75):
                cap.set(cv2.CAP_PROP_POS_MSEC, (pc["a"] + (pc["b"] - pc["a"]) * f) * 1000)
                ok2, fr2 = cap.read()
                if ok2:
                    got = pick_face(mpfaces.faces(fr2), pc["speaker"], sides)
                    if got:
                        picks.append(got)
        else:
            big = [f for f in facedet.faces(fr, 0.02) if f[2] / sw >= 0.11]
            if big:
                x, y, w, h = big[0]
                picks.append(((x + w / 2) / sw, y / sh_ + 0.08, True))
        if picks:
            cx, cy = float(np.median([p[0] for p in picks])), float(np.median([p[1] for p in picks]))
            pc["close"] = sum(1 for p in picks if p[2]) * 2 > len(picks)
            pc["cx"], pc["cy"] = cx, min(0.5, max(0.35, cy + (0.12 if pc["close"] else 0.08)))
            pc["face"] = True
        else:
            pc["cx"], pc["cy"] = motion_cx(cap, pc, pc["speaker"], prior), 0.4
            pc["close"], pc["face"] = False, False
        pc["zoom"] = zooms[zi % len(zooms)]
        zi += 1
    for cap in caps.values():
        cap.release()
    # no face and not the place where the speaker was found: b-roll, shown whole (blur layout) instead of cropped to a guessed window
    seen = {pc["src"]: [hists[j] for j, q in enumerate(pieces) if j in hists and q["src"] == pc["src"] and q.get("face") is True] for pc in pieces}
    need = skillrules.shorts()["broll_similarity"]
    for i, pc in enumerate(pieces):
        if i in hists and pc.get("face") is False and not pc.get("close") and pc["layout"] == "live" and looks_like_broll(hists[i], seen[pc["src"]], need):
            pc["layout"], pc["zoom"], pc["broll"] = "blur", 1.0, True
    # no face found for this speaker (turned away, profile): take the position from the nearest piece of the same speaker where one was found
    for i, pc in enumerate(pieces):
        if pc.get("face") is False and not pc.get("close") and not pc.get("broll"):
            near = sorted((abs(j - i) + (0.5 if j > i else 0), j) for j, q in enumerate(pieces)
                          if q.get("face") and not q.get("close") and not q.get("broll") and q.get("speaker") == pc["speaker"] and abs(q["a"] - pc["a"]) < 12)
            if near:
                q = pieces[near[0][1]]
                pc["cx"], pc["cy"], pc["face"] = q["cx"], q["cy"], "carried"
    return pieces


def frame_hist(fr):
    """A small colour histogram of a frame: what the place looks like, for telling the talking-head set from b-roll."""
    import cv2
    hsv = cv2.cvtColor(cv2.resize(fr, (64, 36)), cv2.COLOR_BGR2HSV)
    hist = cv2.calcHist([hsv], [0, 1], None, [16, 8], [0, 180, 0, 256])
    cv2.normalize(hist, hist)
    return hist


def looks_like_broll(hist, face_hists, threshold) -> bool:
    """A frame with no face that looks nothing like the frames where the speaker was found (colour histogram correlation under `threshold`)
    is probably b-roll. With no frame to compare against nothing can be said."""
    import cv2
    if not face_hists:
        return False
    return max(cv2.compareHist(hist, f, cv2.HISTCMP_CORREL) for f in face_hists) < threshold


def apply_overrides(short, pieces):
    """The host's (or Claude's) crop choices on top of the guesses: layout_all for the whole short, then per-piece crops by source time."""
    pieces = [dict(p) for p in pieces]
    if short.get("layout_all"):
        for pc in pieces:
            if pc["layout"] != "graphic":
                pc["layout"] = short["layout_all"]
    for ov in short.get("crops", []):
        for pc in pieces:
            if pc["a"] - 0.05 <= ov["t"] <= pc["b"] + 0.05 and ov.get("src", pc.get("src")) == pc.get("src"):
                for k in OVERRIDE_KEYS:
                    if k in ov:
                        pc[k] = ov[k]
    return pieces


def split_piece(pc, x0, x1, first):
    """The part of a piece from timeline second x0 to x1 (the piece starts at pc['t0']); `first` = it opens the piece, so it keeps the piece's own cut."""
    a = pc["a"] + (x0 - pc["t0"])
    b = pc["a"] + (x1 - pc["t0"])
    part = dict(pc, a=a, b=b, dur=b - a, t0=x0, cont=pc["cont"] if first else True)
    part["words"] = [w for w in pc["words"] if a - 1e-6 <= w["s"] < b - 1e-6]
    return part


def apply_overlays(cfg, short, pieces):
    """B-roll over talking: short['overlays'] = [{"src": b-roll source, "a", "b": seconds of it, "at": {"src": talking source, "t": the word where it comes in}}].
    The picture is the b-roll (shown whole, `blur` layout) and the sound stays the talking recording's, so the pieces it covers are split and given
    `over`. The picture comes in `overlay_lead_s` before the word (a J cut: the eye is there when the word lands). A clip shorter than asked is cut short."""
    ovs = short.get("overlays") or []
    if not ovs or not pieces:
        return pieces
    lead = skillrules.shorts()["overlay_lead_s"]
    out = [dict(p) for p in pieces]
    for o in ovs:
        at = o.get("at") or {}
        i = next((i for i, p in enumerate(out) if p["src"] == at.get("src") and p["a"] - 1e-6 <= float(at.get("t", -1)) <= p["b"] + 1e-6 and not p.get("over")), None)
        if i is None or o["src"] not in srcs(cfg):
            continue
        ts = max(0.0, out[i]["t0"] + (float(at["t"]) - out[i]["a"]) - lead)
        te = min(ts + (float(o["b"]) - float(o["a"])), out[-1]["t0"] + out[-1]["dur"])
        res = []
        for p in out:
            lo, hi = max(ts, p["t0"]), min(te, p["t0"] + p["dur"])
            if hi - lo < 0.1 or p.get("over"):
                res.append(p)
                continue
            if lo - p["t0"] < 0.1:                                    # a sliver of the piece before the picture: not worth a cut
                lo = p["t0"]
            if p["t0"] + p["dur"] - hi < 0.1:
                hi = p["t0"] + p["dur"]
            if lo > p["t0"]:
                res.append(split_piece(p, p["t0"], lo, True))
            mid = split_piece(p, lo, hi, lo == p["t0"])
            mid.update(over={"src": o["src"], "a": float(o["a"]) + (lo - ts), "b": float(o["a"]) + (hi - ts)}, layout="blur", zoom=1.0, broll=True)
            res.append(mid)
            if hi < p["t0"] + p["dur"]:
                res.append(split_piece(p, hi, p["t0"] + p["dur"], False))
        out = res
    return out


def classify(cfg, pieces):
    return apply_overlays(cfg, cfg_short(cfg), apply_overrides(cfg_short(cfg), auto_classify(cfg, pieces)))


PIECES_VER = 7                                                                   # bump when build_pieces / auto_classify change, so cached guesses are redone
SIG_AUTO = ("ranges", "drop", "words", "pace")                                           # what the automatic guesses depend on
SIG_ALL = ("ranges", "drop", "words", "hook", "crops", "layout_all", "pace", "overlays", "caption_style", "emphasis", "music", "sfx", "gfx")             # what a render depends on


def sig(obj):
    return hashlib.md5(json.dumps(obj, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()[:12]


def short_sig(short, keys):
    return sig([short.get(k) for k in keys])


def auto_pieces(cfg, short, wd):
    """The pieces with the automatic guesses (slow: reads frames), cached in <work>/shorts/<id>.auto.json. When only the cuts or words changed (the host clicking words
    out), the crops are taken over from the earlier pieces that covered the same moment, so a click does not wait for the face finder again."""
    src_key = [[Path(src["path"]).stat().st_size, int(Path(src["path"]).stat().st_mtime)] for src in srcs(cfg).values()] + [PIECES_VER]
    key = sig([short_sig(short, SIG_AUTO), src_key])
    cache = Path(wd) / "shorts" / f"{short['id']}.auto.json"
    old = None
    try:
        c = json.loads(cache.read_text(encoding="utf-8"))
        if c.get("sig") == key:
            return c["pieces"]
        if c.get("src") == src_key and c.get("pace") == short.get("pace"):
            old = c["pieces"]
    except (OSError, ValueError, KeyError):
        pass
    pieces = build_pieces(cfg, short)
    if old:
        todo = []
        for pc in pieces:
            mid = (pc["a"] + pc["b"]) / 2
            o = next((q for q in old if q["a"] - 0.02 <= mid <= q["b"] + 0.02), None)
            if o is None:
                todo.append(pc)
                continue
            for k in ("layout", "cx", "cy", "speaker", "face", "close", "gcy"):
                if k in o:
                    pc[k] = o[k]
        if todo:
            auto_classify(cfg, todo)                     # only the moments that were not looked at before
        zooms, gzooms = pace_of(short)["zooms"], pace_of(short)["gzooms"]
        zi = gi = 0
        for pc in pieces:                                # the zoom steps follow the new order of cuts
            if pc["layout"] == "graphic":
                pc["zoom"], pc["gzoom"] = 1.0, gzooms[gi % len(gzooms)]
                gi += 1
            else:
                pc["zoom"] = zooms[zi % len(zooms)]
                zi += 1
    else:
        pieces = auto_classify(cfg, pieces)
    cache.parent.mkdir(exist_ok=True)
    tmp = cache.with_name(cache.name + f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps({"sig": key, "src": src_key, "pace": short.get("pace"), "pieces": pieces}), encoding="utf-8")
    os.replace(tmp, cache)
    return pieces


def cached_pieces(cfg, short, wd):
    return apply_overlays(cfg, short, apply_overrides(short, auto_pieces(cfg, short, wd)))


def cfg_short(cfg):
    return cfg["_short"]


def crop_box(pc):
    sw, sh_ = pc.get("sw", DEFAULT_SIZE[0]), pc.get("sh", DEFAULT_SIZE[1])
    z = pc.get("zoom", 1.0)
    ch = int(round(sh_ / z / 2) * 2)
    cw = int(round(ch * 9 / 16 / 2) * 2)
    x = int(round(min(max(pc["cx"] * sw - cw / 2, 0), sw - cw)))
    y = int(round(min(max(pc["cy"] * sh_ - ch / 2, 0), sh_ - ch)))
    return cw, ch, x - x % 2, y - y % 2


def ass_time(t):
    cs = int(round(t * 100))
    return f"{cs // 360000}:{cs // 6000 % 60:02d}:{cs // 100 % 60:02d}.{cs % 100:02d}"


def chunks_of(words):
    r = skillrules.shorts()
    out, cur = [], []
    for w in words:
        cur.append(w)
        n = sum(len(x["w"]) for x in cur) + len(cur)
        if len(cur) >= r["caption_max_words"] or n > r["caption_max_chars"] or w["w"].endswith((",", ".", "?", "!")):
            out.append(cur)
            cur = []
    if cur:
        out.append(cur)
    return out


CAPTION_STYLES = {"pop": "Pop", "box": "Box", "bounce": "Bounce", "plain": "Plain"}


def caption_style(short) -> str:
    k = short.get("caption_style") or skillrules.shorts()["caption_style"]
    return k if k in CAPTION_STYLES else "pop"


CHAR_PX = 61                                   # width of one capital of the caption font at 122 px, near enough to keep a line inside the zone


def caption_pos(layout, chars=0) -> tuple:
    """(x, y) of the centre of a caption line, inside YouTube's safe zone: below `safe_top_px`, above the bottom `safe_bottom_px`, left of the right `safe_right_px`.
    A line that fits stays centred; a wide one moves left just enough to keep its right edge out of the buttons."""
    r = skillrules.shorts()
    y = 1500 if layout == "graphic" else 1290
    half = min(chars * CHAR_PX, W - r["safe_right_px"]) / 2
    x = W // 2 if W // 2 + half <= W - r["safe_right_px"] else int(W - r["safe_right_px"] - half)
    return x, min(max(y, r["safe_top_px"] + 95), H - r["safe_bottom_px"] - 95)


CAP_SIZE = 122


def caption_size(chars) -> int:
    """The caption font size: 122 px, smaller (in steps of 4) for a line too wide for the safe zone."""
    room = W - skillrules.shorts()["safe_right_px"]
    return CAP_SIZE if chars * CHAR_PX <= room else max(40, int(CAP_SIZE * room / (chars * CHAR_PX)) // 4 * 4)


def emphasis(pieces, short) -> list:
    """The words that stand out in the captions and get a sound: [{"i": piece, "t": seconds in the short, "s": word start, "w": text, "num": bool}] in time order.
    Numbers, the channel's own terms (the profile) and the words the short lists in `emphasis`; at most one per `emphasis_gap_s` seconds (the marked words first, then numbers)."""
    terms = {re.sub(r"[^\w']", "", t).lower() for t in channel.spellings() if t}
    marked = {re.sub(r"[^\w']", "", str(x)).lower() for x in short.get("emphasis") or []}
    cands = []
    for i, pc in enumerate(pieces):
        for w in pc["words"]:
            core = re.sub(r"[^\w']", "", w["w"]).lower()
            if not core:
                continue
            num = bool(re.search(r"\d", core))
            rank = 0 if core in marked else 1 if num else 2 if core in terms else None
            if rank is not None:
                cands.append((rank, pc["t0"] + w["s"] - pc["a"], i, w, num))
    gap = skillrules.shorts()["emphasis_gap_s"]
    kept = []
    for c in sorted(cands, key=lambda c: (c[0], c[1])):
        if all(abs(c[1] - k[1]) >= gap for k in kept):
            kept.append(c)
    return [{"i": i, "t": t, "s": w["s"], "w": w["w"], "num": num} for _, t, i, w, num in sorted(kept, key=lambda c: c[1])]


def make_ass(short, pieces):
    pal = brandstyle.palette()
    accent, fnt = brandstyle.ass(pal["accent"]), brandstyle.font("headline")
    text_c, outline_c, bold = brandstyle.ass(pal["light"]), brandstyle.ass(pal["dark"]), -1 if fnt["bold"] else 0
    on_accent = outline_c if brandstyle.luminance(pal["accent"]) > 0.6 else text_c            # the hook text sits on a box in the accent colour
    style = caption_style(short)
    emph = {(e["i"], round(e["s"], 2)) for e in emphasis(pieces, short)}
    sp = pace_of(short)["speed"]                           # the whole short is played faster: caption times follow
    ev, caps = [], []
    for pi, pc in enumerate(pieces):
        ws = [dict(w, o=pc["t0"] + w["s"] - pc["a"], em=(pi, round(w["s"], 2)) in emph) for w in pc["words"]]
        for ch in chunks_of(ws):
            nchars = sum(len(re.sub(r"[.,;:]+$", "", x["w"])) for x in ch) + len(ch) - 1
            cx, y = caption_pos(pc["layout"], nchars)
            size = caption_size(nchars)
            for k, w in enumerate(ch):
                start = max(0.0, w["o"])
                end = ch[k + 1]["o"] - 0.012 if k + 1 < len(ch) else min(ch[-1]["o"] + (ch[-1]["e"] - ch[-1]["s"]) + 0.12, pc["t0"] + pc["dur"])
                if end <= start:
                    continue
                parts = []
                for j, x in enumerate(ch):
                    t = re.sub(r"[.,;:]+$", "", x["w"]).upper().replace("{", "").replace("}", "")
                    big = "{\\c" + accent + "\\fscx120\\fscy120}" if x["em"] else ""
                    if j == k and style == "pop":
                        parts.append("{\\c" + accent + "\\fscx135\\fscy135\\t(0,110,\\fscx118\\fscy118)}" + t + "{\\r}")
                    elif j == k and style == "box":
                        parts.append("{\\c" + on_accent + "\\3c" + accent + "\\bord16}" + t + "{\\r}")
                    elif big:
                        parts.append(big + t + "{\\r}")
                    else:
                        parts.append(t)
                where = f"\\move({cx},{y - 70},{cx},{y},0,140)" if style == "bounce" and k == 0 else f"\\pos({cx},{y})"
                caps.append([start, end, f"{{\\an5{where}}}" + " ".join(parts), size])
    caps.sort(key=lambda c: c[0])
    for c, nxt in zip(caps, caps[1:]):                     # one line at a time: a line ends where the next begins (the held last word of a line used to run into the next one)
        c[1] = min(c[1], nxt[0])
    sizes = sorted({c[3] for c in caps} | {CAP_SIZE})
    for start, end, text, size in caps:
        if end > start:
            ev.append(f"Dialogue: 1,{ass_time(start / sp)},{ass_time(end / sp)},{'Cap' if size == CAP_SIZE else f'Cap{size}'},,0,0,0,,{text}")
    import shortsgfxbuild
    for start, end, text in shortsgfxbuild.kinetic_events(short, pieces, sp):             # key-word pop-ups of the planned graphics
        ev.append(f"Dialogue: 3,{ass_time(start)},{ass_time(end)},Cap,,0,0,0,,{text}")
    hook = short.get("hook")
    if hook:
        lines = "\\N".join(hook.upper().split("|"))
        ev.append(f"Dialogue: 2,{ass_time(0.0)},{ass_time(skillrules.shorts()["hook_s"])},Hook,,0,0,0,,{{\\an5\\pos({caption_pos("live")[0]},230)\\fad(120,200)\\fscx60\\fscy60\\t(0,160,\\fscx100\\fscy100)}}{lines}")
    styles = "".join(f'Style: {"Cap" if n == CAP_SIZE else f"Cap{n}"},{fnt["family"]},{n},{text_c},{text_c},{outline_c},&H96000000,{bold},0,0,0,100,100,2,0,1,9,5,5,40,40,0,1\n'
                     for n in sizes)
    head = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
{styles}Style: Hook,{fnt["family"]},100,{on_accent},{on_accent},{accent},{accent},{bold},0,0,0,100,100,2,0,3,22,0,5,60,60,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    return head + "\n".join(ev) + "\n"


def ev(v):
    """An even pixel count (video wants even sizes)."""
    return int(round(v / 2) * 2)


def filter_graph(pieces, base, speed=1.0, f=1.0, inputs=None):
    """f = size factor: 1.0 = 1080x1920 (final), 0.5 = 540x960 (the quick preview). `base`: seconds each input starts at (one number for a single
    source, or {source id: seconds}); `inputs`: {source id: ffmpeg input number} (omitted: everything comes from input 0)."""
    card = brandstyle.ffmpeg(brandstyle.palette()["primary"])
    w, h = ev(W * f), ev(H * f)
    fv, fa, vs, as_ = [], [], [], []
    for i, pc in enumerate(pieces):
        k = (inputs or {}).get(pc.get("src"), 0)
        t_in = base[pc["src"]] if isinstance(base, dict) else base
        a, b = pc["a"] - t_in, pc["b"] - t_in
        ov = pc.get("over")                                      # b-roll over talking: the picture comes from another file, the sound stays this one's
        if ov:
            kv = (inputs or {}).get(ov["src"], 0)
            va = ov["a"] - (base[ov["src"]] if isinstance(base, dict) else base)
            vb = va + (ov["b"] - ov["a"])
        else:
            kv, va, vb = k, a, b
        if pc["layout"] == "graphic":
            gz = pc.get("gzoom", 1.0)
            gw = int(round(1600 / gz / 2) * 2)
            gh = int(round(1080 / gz / 2) * 2)
            sw, sh_ = pc.get("sw", DEFAULT_SIZE[0]), pc.get("sh", DEFAULT_SIZE[1])
            gw, gh = min(gw, sw // 2 * 2), min(gh, sh_ // 2 * 2)
            gx = int(round(min(max(pc.get("gcx", 0.5) * sw - gw / 2, 0), sw - gw)))
            gy = int(round(min(max(pc.get("gcy", 0.5) * sh_ - gh / 2, 0), sh_ - gh)))
            chain = f"crop={gw}:{gh}:{gx}:{gy},scale={w}:{ev(730 * f)}:flags=lanczos,pad={w}:{h}:0:{ev(400 * f)}:color={card}"
        elif pc["layout"] == "blur":
            # B-roll that should stay whole: sharp 16:9 in the middle, a blurred, enlarged copy fills the rest
            fv.append(f"[{kv}:v]trim=start={va:.3f}:end={vb:.3f},setpts=PTS-STARTPTS,split[vb{i}][vf{i}];"
                      f"[vb{i}]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},boxblur={max(2, int(40 * f))}:{max(1, int(4 * f))},eq=brightness=-0.1[bb{i}];"
                      f"[vf{i}]scale={w}:-2:flags=lanczos[ff{i}];[bb{i}][ff{i}]overlay=0:(H-h)/2-{int(90 * f)},setsar=1,fps=30[v{i}]")
            chain = None
        else:
            cw, ch, x, y = crop_box(pc)
            chain = f"crop={cw}:{ch}:{x}:{y},scale={w}:{h}:flags=lanczos" + (",unsharp=5:5:0.5" if f >= 1.0 else "")
        if chain:
            fv.append(f"[{kv}:v]trim=start={va:.3f}:end={vb:.3f},setpts=PTS-STARTPTS,{chain},setsar=1,fps=30[v{i}]")
        if pc.get("noaudio"):                                    # a file with no sound (most b-roll): silence for as long as the piece
            af = f"anullsrc=r=48000:cl=stereo,atrim=duration={b - a:.3f},asetpts=PTS-STARTPTS"
        else:
            af = f"[{k}:a]atrim=start={a:.3f}:end={b:.3f},asetpts=PTS-STARTPTS"
        d = 0.012
        if not pc["cont"]:
            af += f",afade=t=in:d={d}"
        if not (i + 1 < len(pieces) and pieces[i + 1]["cont"]):
            af += f",afade=t=out:st={max(pc['dur'] - d, 0):.3f}:d={d}"
        fa.append(af + f"[a{i}]")
        vs.append(f"[v{i}]")
        as_.append(f"[a{i}]")
    n = len(pieces)
    fv.append("".join(vs) + f"concat=n={n}:v=1:a=0" + (f",setpts=PTS/{speed}" if speed != 1.0 else "") + "[vc]")
    fa.append("".join(as_) + f"concat=n={n}:v=0:a=1" + (f",atempo={speed}" if speed != 1.0 else "") + ",loudnorm=I=-14:TP=-1.5:LRA=11[aout]")
    return fv, fa


ENCODE = {
    # preview: quick look while editing, half size; final: for approved shorts, full 1080x1920, the slowest NVENC preset and a high quality target
    "preview": {"f": 0.5, "v": ["-preset", "p4", "-cq", "26", "-b:v", "0"], "audio": "160k"},
    "final": {"f": 1.0, "v": ["-preset", "p7", "-tune", "hq", "-rc", "vbr", "-cq", "15", "-b:v", "0", "-maxrate", "16M", "-bufsize", "32M",
                              "-spatial-aq", "1", "-temporal-aq", "1", "-rc-lookahead", "24", "-profile:v", "high"], "audio": "256k"},
}


def render(cfg, short, out, pieces=None, quality="preview", report=None):
    """Render one short to `out`. `report` (a dict) gets "audio": what was mixed under the voice (the track, the SFX, and what was missing)."""
    enc = ENCODE[quality]
    f = enc["f"]
    pieces = pieces or classify(cfg, build_pieces(cfg, short))
    speed = pace_of(short)["speed"]
    total = (pieces[-1]["t0"] + pieces[-1]["dur"]) / speed          # length of the finished short
    spans = [(p["src"], p["a"], p["b"]) for p in pieces] + [(p["over"]["src"], p["over"]["a"], p["over"]["b"]) for p in pieces if p.get("over")]
    used = list(dict.fromkeys(s for s, _, _ in spans))                    # the files the pieces come from (picture or sound), in order of first use
    base = {sid: max(0.0, min(a for s, a, _ in spans if s == sid) - 1.0) for sid in used}
    span_end = {sid: max(b for s, _, b in spans if s == sid) + 1.0 for sid in used}
    fv, fa = filter_graph(pieces, base, speed, f, {sid: n for n, sid in enumerate(used)})
    tmp = Path(tempfile.mkdtemp(prefix="short_", dir=tempfile.gettempdir()))
    try:
        (tmp / "c.ass").write_text(make_ass(short, pieces), encoding="utf-8")
        shutil.copy(brandstyle.font("headline")["file"], tmp)
        import shortsgfxbuild
        cards = shortsgfxbuild.cards(short, pieces, speed, tmp, f)                       # explainer cards: one picture per step, laid over the video at their time
        chain, cur = [], "vb"
        for j, c in enumerate(cards):
            n = len(used) + j
            fades = ("fade=t=in:st={:.3f}:d={}:alpha=1".format(c["t0"], shortsgfxbuild.FADE_S) if c["first"] else "") + (
                "," if c["first"] and c["last"] else "") + ("fade=t=out:st={:.3f}:d={}:alpha=1".format(max(c["t1"] - shortsgfxbuild.FADE_S, c["t0"]), shortsgfxbuild.FADE_S) if c["last"] else "")
            chain.append(f"[{n}:v]format=rgba" + ("," + fades if fades else "") + f"[gc{j}]")
            rise = int(shortsgfxbuild.SLIDE_PX * f)
            y = f"'{c['y']}+if(lt(t,{c['t0'] + 0.2:.3f}),({c['t0'] + 0.2:.3f}-t)*{rise * 5},0)'" if c["first"] else str(c["y"])
            chain.append(f"[{cur}][gc{j}]overlay=x={c['x']}:y={y}:enable='between(t,{c['t0']:.3f},{c['t1']:.3f})':eof_action=pass[gv{j}]")
            cur = f"gv{j}"
        graph = ";".join(fv + fa + [
            f"color=c={brandstyle.ffmpeg(brandstyle.palette()['accent'])}:s={ev(W * f)}x{ev(14 * f)}:r=30:d={total:.2f}[bar]",
            f"[vc][bar]overlay=x='-w+w*t/{total:.2f}':y=H-h:shortest=1[vb]", *chain,
            f"[{cur}]subtitles=c.ass:fontsdir=.[vout]"])
        (tmp / "g.txt").write_text(graph, encoding="utf-8")
        ins = [x for sid in used for x in ("-ss", f"{base[sid]:.3f}", "-t", f"{span_end[sid] - base[sid]:.3f}", "-i", srcs(cfg)[sid]["path"])]
        ins += [x for c in cards for x in ("-loop", "1", "-framerate", "30", "-t", f"{total:.2f}", "-i", c["png"])]
        cmd = ["ffmpeg", "-y", "-v", "error", "-stats", *ins,
               "-/filter_complex", "g.txt", "-map", "[vout]", "-map", "[aout]", "-t", f"{total:.2f}",
               *encoders.adapt(["-c:v", "h264_nvenc", *enc["v"]]), "-pix_fmt", "yuv420p", "-r", "30",
               "-c:a", "aac", "-b:a", enc["audio"], "-movflags", "+faststart", str(Path(out).resolve())]
        subprocess.run(cmd, cwd=tmp, check=True)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    import shortsaudio
    extras = shortsaudio.plan(short, pieces, total, speed)
    if extras["beds"] or extras["sfx"]:
        shortsaudio.mix_into(Path(out), extras)
    if report is not None:
        report["audio"] = {"track": extras["track"], "sfx": len(extras["sfx"]), "missing": extras["missing"]}
    return total, pieces


def sheet(cfg, short, out, pieces=None):
    import cv2
    import numpy as np
    pieces = pieces or classify(cfg, build_pieces(cfg, short))
    caps = {sid: cv2.VideoCapture(src["path"]) for sid, src in srcs(cfg).items()}
    tiles = []
    for i, pc in enumerate(pieces):
        mid = (pc["a"] + pc["b"]) / 2
        cap = caps[pc.get("src", cfg["_first"])]
        cap.set(cv2.CAP_PROP_POS_MSEC, mid * 1000)
        ok, fr = cap.read()
        if not ok:
            continue
        if pc["layout"] != "graphic":
            cw, ch, x, y = crop_box(pc)
            cv2.rectangle(fr, (x, y), (x + cw, y + ch), (0, 140, 255), 8)
        fr = cv2.resize(fr, (480, 270))
        label = f"{i} {pc['a']:.1f}-{pc['b']:.1f} {pc['layout']} z{pc.get('zoom', 1)} {pc['speaker']}"
        cv2.putText(fr, label, (6, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1, cv2.LINE_AA)
        tiles.append(fr)
    cols = 4
    while len(tiles) % cols:
        tiles.append(np.zeros_like(tiles[0]))
    rows = [np.hstack(tiles[r:r + cols]) for r in range(0, len(tiles), cols)]
    cv2.imwrite(str(out), np.vstack(rows))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["plan", "sheet", "render"])
    ap.add_argument("cfg")
    ap.add_argument("id")
    ap.add_argument("--out")
    ap.add_argument("--quality", choices=sorted(ENCODE), default="preview")
    a = ap.parse_args()
    cfg = load(a.cfg)
    short = next(s for s in cfg["shorts"] if s["id"] == a.id)
    cfg["_short"] = short
    base = Path(a.cfg).parent
    (base / "shorts").mkdir(exist_ok=True)
    if a.cmd == "plan":
        pcs = cached_pieces(cfg, short, base)
        for i, p in enumerate(pcs):
            print(i, f"{p['a']:.2f}-{p['b']:.2f}", p["layout"], p["speaker"], f"cx{p['cx']:.2f} cy{p['cy']:.2f} z{p.get('zoom', 1)}", " ".join(w["w"] for w in p["words"]))
        print("total", round(pcs[-1]["t0"] + pcs[-1]["dur"], 1), "s")
    elif a.cmd == "sheet":
        out = a.out or str(base / "shorts" / f"{a.id}.sheet.png")
        sheet(cfg, short, out, cached_pieces(cfg, short, base))
        print(out)
    else:
        suffix = "" if a.quality == "preview" else ".final"
        out = Path(a.out or base / "shorts" / f"{a.id}{suffix}.mp4")
        part = out.with_name(out.stem + ".part.mp4")           # the app serves the file while it is being replaced: never write into it directly
        report = {}
        total, _ = render(cfg, short, str(part), cached_pieces(cfg, short, base), a.quality, report)
        os.replace(part, out)
        (out.parent / f"{a.id}{suffix}.render.json").write_text(json.dumps({"sig": short_sig(short, SIG_ALL), "dur": round(total, 2), "at": time.time(), "quality": a.quality, **report}), encoding="utf-8")
        print(out, round(total, 1), "s")


if __name__ == "__main__":
    main()
