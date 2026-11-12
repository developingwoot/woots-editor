"""Blur (or block out) a part of the picture: a name, an address, a screen. The box follows what it covers through the clip.

The host pauses the rough cut on the first frame where the thing shows, draws a box over it, and the box is followed frame by frame (OpenCV's CSRT tracker,
on the rough cut the host watched) to the end of the clip or to where the host says it ends. Where it drifts, the host pauses there and draws it again:
the path is kept up to that moment and followed again from the new box.

On a beat it lives in `on_screen.blur`:
    {"id": "bl1", "at": 2.4, "dur": 6.0, "style": "blur|block", "what": "the username on the printer screen",
     "track": [[0.0, x, y, w, h], [0.067, ...], ...]}     # t from `at`; the box as fractions of the picture (0..1, top left corner)
A blur a note asked for (noteactions "blur") has no track yet: the review screen asks the host to place it.

sections.baseline_edit turns each into "blurs" of the section edit, per piece of a trimmed beat ({"seg", "at", "dur", "style", "track"} with t from `at`),
and sectionrender.blur_chains draws them over the picture, B-roll included, under the text cards and graphics.
"""
import itertools
import time

STYLES = ("blur", "block")
STEP = 2                 # a box is kept every STEP frames (the render goes in a straight line between them)
TRACK_W = 640            # frames are followed at this width: quick, and as good for a box of a few dozen pixels
PAD = 0.15               # the drawn box grows by this much each way in the render, so a box that lags a frame still covers
SIMPLIFY = 0.003         # boxes that move less than this (a fraction of the picture) from the straight line between two kept boxes are dropped
MAX_KEYS = 120           # a piece's path is never longer than this many boxes (the ffmpeg command has a size limit)
MIN_SIDE = 0.01


def _clean_box(box) -> list:
    x, y, w, h = (float(v) for v in box)
    w, h = max(MIN_SIDE, min(1.0, w)), max(MIN_SIDE, min(1.0, h))
    x, y = max(0.0, min(1.0 - w, x)), max(0.0, min(1.0 - h, y))
    return [round(x, 4), round(y, 4), round(w, 4), round(h, 4)]


def follow(video: str, t0: float, t1: float, box, step: int = STEP) -> list:
    """[[t, x, y, w, h]] from t0 to t1 (seconds of `video`), the box (fractions) followed through the frames. A frame where the tracker loses it keeps the last box."""
    import cv2
    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        raise ValueError("the video could not be opened")
    try:
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        f0 = int(round(t0 * fps))
        cap.set(cv2.CAP_PROP_POS_FRAMES, f0)
        ok, frame = cap.read()
        if not ok:
            raise ValueError("that moment is not in the video")
        H0, W0 = frame.shape[:2]
        k = TRACK_W / W0 if W0 > TRACK_W else 1.0
        small = lambda f: cv2.resize(f, (int(W0 * k), int(H0 * k))) if k != 1.0 else f      # noqa: E731
        x, y, w, h = _clean_box(box)
        sw, sh = int(W0 * k), int(H0 * k)
        rect = (int(x * sw), int(y * sh), max(4, int(w * sw)), max(4, int(h * sh)))
        tr = cv2.TrackerCSRT_create()
        tr.init(small(frame), rect)
        out = [[round(t0, 3), x, y, w, h]]
        last = list(rect)
        n = int(round((t1 - t0) * fps))
        for i in range(1, n + 1):
            ok, frame = cap.read()
            if not ok:
                break
            got, r = tr.update(small(frame))
            if got:
                last = [r[0], r[1], r[2], r[3]]
            if i % step == 0 or i == n:
                out.append([round(t0 + i / fps, 3), *_clean_box((last[0] / sw, last[1] / sh, last[2] / sw, last[3] / sh))])
        return out
    finally:
        cap.release()


def simplify(track: list, tol: float = SIMPLIFY, most: int = MAX_KEYS) -> list:
    """The fewest boxes that stay within tol of the path (Ramer-Douglas-Peucker on x, y, w, h); tol grows until there are at most `most`."""
    if len(track) <= 2:
        return [list(p) for p in track]

    def rdp(pts, tol):
        a, b = pts[0], pts[-1]
        span = b[0] - a[0] or 1e-9
        worst, wi = -1.0, 0
        for i in range(1, len(pts) - 1):
            f = (pts[i][0] - a[0]) / span
            d = max(abs(pts[i][j] - (a[j] + (b[j] - a[j]) * f)) for j in range(1, 5))
            if d > worst:
                worst, wi = d, i
        if worst <= tol:
            return [a, b]
        return rdp(pts[:wi + 1], tol)[:-1] + rdp(pts[wi:], tol)

    out = rdp(track, tol)
    while len(out) > most:
        tol *= 1.6
        out = rdp(track, tol)
    return [list(p) for p in out]


def box_at(track: list, t: float) -> list:
    """The box at t (from the entry's start) in a straight line between the kept boxes; the first or last outside them."""
    if not track:
        return []
    if t <= track[0][0]:
        return list(track[0][1:])
    for a, b in itertools.pairwise(track):
        if t <= b[0]:
            f = (t - a[0]) / ((b[0] - a[0]) or 1e-9)
            return [a[j] + (b[j] - a[j]) * f for j in range(1, 5)]
    return list(track[-1][1:])


# ----------------------------------------------------------------------------- on the beats
def _rows(b: dict) -> list:
    return (b.get("on_screen") or {}).get("blur") or []


def _new_id(beats: list) -> str:
    """Never the id of a blur taken out before: the notes of the cuts still name those."""
    import uuid
    have = {x.get("id") for b in beats for x in _rows(b)}
    return next(i for i in (f"bl{uuid.uuid4().hex[:8]}" for _ in itertools.count()) if i not in have)


def find(beats: list, bid: str):
    for b in beats:
        for x in _rows(b):
            if x.get("id") == bid:
                return b, x
    raise ValueError("that blur is not in the plan any more")


def _clip_at(beats: list, t: float, times: dict):
    import noteactions
    b, _ = noteactions.beat_at(beats, t, times)
    s, d = noteactions._span(b, times)
    return b, s, d


def add(beats: list, times: dict, video: str, t: float, box, style: str = "blur", what: str = "", follow_fn=follow) -> dict:
    """A new blur on the clip playing at t (a time in `video`), from t to the end of that clip, the box followed through it."""
    b, s, d = _clip_at(beats, t, times)
    t = max(s, min(t, s + d - 0.1))
    tr = follow_fn(video, t, s + d, box)
    e = {"id": _new_id(beats), "at": round(t - s, 3), "dur": round(s + d - t, 3), "style": style if style in STYLES else "blur", "what": " ".join(str(what).split())[:80],
         "track": [[round(p[0] - t, 3), *p[1:]] for p in tr], "made": time.strftime("%Y-%m-%d")}
    on = b.setdefault("on_screen", {"shot": "a-roll", "note": "", "broll": []})
    on["blur"] = list(on.get("blur") or []) + [e]
    return e


def ask(beats: list, t: float, what: str, times: dict | None = None) -> dict:
    """A blur a note asked for: on the clip at t, with no box yet (the host places it on the frame)."""
    import noteactions
    b, at = noteactions.beat_at(beats, t, times)
    e = {"id": _new_id(beats), "at": round(at, 3), "dur": round(max(0.5, float(noteactions._span(b, times)[1]) - at), 3), "style": "blur",
         "what": " ".join(str(what).split())[:80], "track": []}
    on = b.setdefault("on_screen", {"shot": "a-roll", "note": "", "broll": []})
    on["blur"] = list(on.get("blur") or []) + [e]
    return e


def fix(beats: list, times: dict, video: str, bid: str, t: float, box, follow_fn=follow) -> dict:
    """The box drawn again at t (a time in `video`): the path before t is kept and it is followed again from there to the blur's end.
    Before the blur's start (or on a blur with no box yet), the blur starts at t instead."""
    b, e = find(beats, bid)
    import noteactions
    s, d = noteactions._span(b, times)
    a0, a1 = s + float(e["at"]), s + float(e["at"]) + float(e["dur"])
    t = max(s, min(t, s + d - 0.1))
    if t <= a0 + 0.02 or not e.get("track"):
        if t >= a1 - 0.05:
            a1 = s + d
        e["at"], e["dur"] = round(t - s, 3), round(a1 - t, 3)
        e["track"] = [[round(p[0] - t, 3), *p[1:]] for p in follow_fn(video, t, a1, box)]
        return e
    keep = [p for p in e["track"] if p[0] < t - a0 - 0.001]
    e["track"] = keep + [[round(p[0] - a0, 3), *p[1:]] for p in follow_fn(video, t, a1, box)]
    return e


def set_end(beats: list, times: dict, video: str, bid: str, t: float, follow_fn=follow) -> dict:
    """The blur ends at t: a shorter path, or one followed on from its last box to t (never past the clip's end)."""
    b, e = find(beats, bid)
    import noteactions
    s, d = noteactions._span(b, times)
    a0 = s + float(e["at"])
    t = min(t, s + d)
    if t <= a0 + 0.1:
        raise ValueError("the end must be after the start of the blur")
    tr = e.get("track") or []
    end = a0 + (tr[-1][0] if tr else 0.0)
    if tr and t > end + 0.05:
        more = follow_fn(video, end, t, tr[-1][1:])
        e["track"] = tr + [[round(p[0] - a0, 3), *p[1:]] for p in more[1:]]
    elif tr:
        last = box_at(tr, t - a0)
        e["track"] = [p for p in tr if p[0] < t - a0 - 0.001] + [[round(t - a0, 3), *_clean_box(last)]]
    e["dur"] = round(t - a0, 3)
    return e


def set_style(beats: list, bid: str, style: str) -> dict:
    _, e = find(beats, bid)
    if style not in STYLES:
        raise ValueError("unknown style")
    e["style"] = style
    return e


def remove(beats: list, bid: str) -> dict:
    b, e = find(beats, bid)
    b["on_screen"]["blur"] = [x for x in _rows(b) if x is not e]
    return e


# ----------------------------------------------------------------------------- into the render
def edit_rows(b: dict, pieces: list) -> list:
    """The beat's placed blurs as section-edit "blurs": one per piece of a trimmed beat it overlaps (pieces = sections._pieces, [] for one piece),
    each with its path in that piece's own time."""
    out = []
    for e in _rows(b):
        tr = e.get("track") or []
        if not tr or e.get("style", "blur") not in STYLES:
            continue
        at, dur = float(e.get("at") or 0), float(e.get("dur") or 0)
        if dur <= 0.05:
            continue
        for sid, s0, ln in pieces or [(b["id"], 0.0, float("inf"))]:
            a0, a1 = max(at, s0), min(at + dur, s0 + ln)
            if a1 - a0 <= 0.05:
                continue
            inside = [p for p in tr if a0 - at < p[0] < a1 - at]
            path = [[0.0, *box_at(tr, a0 - at)], *[[p[0] - (a0 - at), *p[1:]] for p in inside], [a1 - a0, *box_at(tr, a1 - at)]]
            out.append({"seg": sid, "at": round(a0 - s0, 3), "dur": round(a1 - a0, 3), "style": e.get("style", "blur"),
                        "track": [[round(v, 4) for v in p] for p in simplify(path)]})
    return out


def _lerp_expr(ts: list, vs: list) -> str:
    """An ffmpeg expression of t: a straight line between the (ts, vs) points, flat before the first and after the last."""
    if len(ts) == 1 or all(abs(v - vs[0]) < 0.5 for v in vs):
        return f"{vs[0]:.1f}"
    parts = [f"lt(t,{ts[0]:.3f})*{vs[0]:.1f}"]
    for (ta, va), (tb, vb) in itertools.pairwise(zip(ts, vs)):
        if tb - ta <= 1e-4:
            continue
        parts.append(f"between(t,{ta:.3f},{tb:.3f}-0.0001)*({va:.1f}+({vb - va:.1f})*(t-{ta:.3f})/{tb - ta:.3f})")
    parts.append(f"gte(t,{ts[-1]:.3f})*{vs[-1]:.1f}")
    return "+".join(parts)


def chains(blurs: list, last: str, W: int, H: int) -> tuple:
    """(filter chains, the label after them) that blur or block out each box over `last`. The box is the biggest the path ever is (plus PAD),
    so it never shrinks off what it covers; it moves with the path's centre."""
    out = []
    for i, bl in enumerate(blurs):
        at, dur, tr = float(bl["at"]), float(bl["dur"]), bl["track"]
        bw = min(W, int(max(p[3] for p in tr) * W * (1 + 2 * PAD)) // 2 * 2 + 2)
        bh = min(H, int(max(p[4] for p in tr) * H * (1 + 2 * PAD)) // 2 * 2 + 2)
        ts = [at + p[0] for p in tr]
        xs = [max(0.0, min(W - bw, (p[1] + p[3] / 2) * W - bw / 2)) for p in tr]
        ys = [max(0.0, min(H - bh, (p[2] + p[4] / 2) * H - bh / 2)) for p in tr]
        xe, ye = _lerp_expr(ts, xs), _lerp_expr(ts, ys)
        look = (f"drawbox=x=0:y=0:w=iw:h=ih:color=black@1:t=fill" if bl.get("style") == "block"
                else f"boxblur=luma_radius={max(2, min(bw, bh) // 5)}:luma_power=3:chroma_radius={max(2, min(bw, bh) // 8)}:chroma_power=2")
        out.append(f"[{last}]split[bk{i}][bs{i}]")
        out.append(f"[bs{i}]crop=w={bw}:h={bh}:x='{xe}':y='{ye}',{look}[bc{i}]")
        out.append(f"[bk{i}][bc{i}]overlay=x='{xe}':y='{ye}':enable='between(t,{at:.3f},{at + dur:.3f})'[vbl{i}]")
        last = f"vbl{i}"
    return out, last


# ----------------------------------------------------------------------------- what the review screen does
def _note(work: str, name: str, b: dict, e: dict | None, bid: str, start: float, gone: bool = False):
    """One open clip change per blur, so the next cut is asked for and Notes say what it does; it is done when that cut is made."""
    import reviewnotes
    with reviewnotes._lock:
        j = reviewnotes.load(work, name)
        mine = lambda n: n.get("kind") == "blur" and (n.get("choice") or {}).get("blur") == bid       # noqa: E731
        j["cut"] = [n for n in j["cut"] if not (mine(n) and n.get("status") != "done")]
        if gone and not any(mine(n) for n in j["cut"]):          # never in a cut: nothing to take out
            reviewnotes.save(work, name, j)
            return
        block = bool(e and e.get("style") == "block")
        thing, what, at = ("black box" if block else "blur"), (e or {}).get("what") or "a part of the picture", _clock(start)
        if gone:
            text, said = f"No {thing} at {at} any more", f"Took out the {thing} at {at}"
        elif block:
            text, said = f"Black box over {what} at {at}", f"Put a black box over {what} at {at}"
        else:
            text, said = f"Blur {what} at {at}", f"Blurred {what} at {at}"
        nid = 1 + max([n["id"] for n in j["cut"]] + [0])
        j["cut"].append({"id": nid, "t": round(start, 1), "t_end": None, "text": text, "clip": b["id"], "kind": "blur",
                         "choice": {"blur": bid, "said": said, **({"gone": True} if gone else {})}, "status": "open", "applied_in": None})
        reviewnotes.save(work, name, j)


def _clock(t: float) -> str:
    t = int(round(t or 0))
    return f"{t // 60}:{t % 60:02d}"


def do(work: str, name: str, op: str, bid: str | None = None, t: float | None = None, box=None, style: str = "blur", what: str = "", follow_fn=follow) -> dict:
    """add (t, box) / fix (bid, t, box) / end (bid, t) / style (bid, style) / delete (bid), on the latest rough cut. Writes the beat map through projectstore."""
    import beatmap
    import config
    import makeversion
    import noteactions
    import projectstore
    import reviewnotes
    vs = reviewnotes.versions(work, name, "cut")
    if not vs:
        raise ValueError("make the rough cut first")
    video = str(config.WORK / work / vs[-1]["file"])
    times = makeversion.clip_times(work, name, "cut")
    p = config.WORK / work / f"{name}.beatmap.json"
    bm = beatmap.read_json(p)
    if not bm:
        raise ValueError("there is no plan")
    beats = bm["beats"]
    if box is not None:
        box = _clean_box(box)
    if op == "add":
        e = add(beats, times, video, float(t), box, style, what, follow_fn)
    elif op == "fix":
        e = fix(beats, times, video, bid, float(t), box, follow_fn)
    elif op == "end":
        e = set_end(beats, times, video, bid, float(t), follow_fn)
    elif op == "style":
        e = set_style(beats, bid, style)
    elif op == "delete":
        b, _ = find(beats, bid)
        e = remove(beats, bid)
    else:
        raise ValueError("unknown blur change")
    if op != "delete":
        b, _ = find(beats, e["id"])
    start = noteactions._span(b, times)[0] + float(e.get("at") or 0)
    projectstore.write_json(p, bm, why={"add": "blur added", "fix": "blur box moved", "end": "blur end moved", "style": "blur style", "delete": "blur removed"}[op])
    _note(work, name, b, e, e["id"], start, gone=op == "delete")
    return e


# ----------------------------------------------------------------------------- for the review screen
def rows(beats: list, times: dict) -> list:
    """Every blur in the video the host watches: {id, beat, start, end, what, style, placed, track: [[t, x, y, w, h]] with t in the video}."""
    import noteactions
    out = []
    for b in beats:
        if b.get("skip") or b["id"] not in times:
            continue
        s, _ = noteactions._span(b, times)
        for e in _rows(b):
            a0 = s + float(e.get("at") or 0)
            out.append({"id": e["id"], "beat": b["id"], "start": round(a0, 3), "end": round(a0 + float(e.get("dur") or 0), 3), "what": e.get("what", ""),
                        "style": e.get("style", "blur"), "placed": bool(e.get("track")),
                        "track": [[round(a0 + p[0], 3), *p[1:]] for p in e.get("track") or []]})
    return sorted(out, key=lambda r: r["start"])
