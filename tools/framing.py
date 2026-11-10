"""Punch-in zooms on the talking head that keep the eyes where they are (the host, 2026-10-29).

A minute of talking head with only the B-roll for variety is flat. At each jump cut the picture alternates between the wide shot and a slight zoom. The
zoom crops around the point (cx, cy) with the render's own formula (sectionrender.base_filter: y = (in_h - out_h) * cy), and for that formula the eyes stay
on the same line of the screen exactly when cy equals the eye line (their height as a fraction of the frame), whatever the zoom. So the one thing needed is
where the eyes are in each recording: Claude looks at one frame of each and says (framing.json: {rel: eye_y}); no zoom is made for a recording whose eyes
are not known. The zoom is in the beat as `on_screen.punch` = {"zooms": [per piece], "cy": eye_y} and baseline_edit puts it on the pieces.
"""
import os
import subprocess
from pathlib import Path

import beatmap
import clipmap
import config
import skillrules
from sectionrender import FFMPEG, FFPROBE

WORK = config.WORK
ZOOM = 1.15                      # set from the skill (rough-cut.json: punch_in_zoom) by reload_rules()
EYE_MIN, EYE_MAX = 0.15, 0.7


def reload_rules():
    global ZOOM
    ZOOM = skillrules.rules()["punch_in_zoom"]


reload_rules()


def path(work: str, name: str) -> Path:
    return WORK / work / f"{name}.framing.json"


def load(work: str, name: str) -> dict:
    return clipmap.read_json(path(work, name), {}) or {}


def talking_recordings(data: dict) -> list:
    seen = []
    for b in data["beats"]:
        ar = b.get("aroll")
        if ar and not b.get("skip") and not b.get("vo") and ar["rel"] not in seen:
            seen.append(ar["rel"])
    return seen


def missing(work: str, name: str, data: dict) -> list:
    known = load(work, name)
    return [r for r in talking_recordings(data) if r not in known]


def centre_crop(face_x: float, zoom: float) -> float:
    """The crop point cx that puts the face in the middle of a zoomed frame (the render crops x = (in_w - out_w) * cx; out_w = in_w / zoom), kept inside the picture:
    a face at 0.38 of the width is centered at zoom 1.3, a face further out is as near the middle as the edge allows."""
    if zoom <= 1.0:
        return 0.5
    return round(max(0.0, min(1.0, (face_x - 0.5 / zoom) / (1.0 - 1.0 / zoom))), 3)


def face_x(src: str, frames: int = 7):
    """Where the face is across the picture (0 = left edge, 1 = right edge): the median over several frames of the recording, or None when no face is found."""
    import subprocess
    import numpy as np
    import facedet
    try:
        dur = float(subprocess.run([FFPROBE, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", src], capture_output=True, text=True).stdout.strip())
    except ValueError:
        return None
    xs = []
    for k in range(1, frames + 1):
        raw = subprocess.run([FFMPEG, "-nostdin", "-v", "error", "-ss", f"{dur * k / (frames + 1):.2f}", "-i", src, "-frames:v", "1", "-vf", "scale=640:360",
                              "-f", "rawvideo", "-pix_fmt", "bgr24", "-"], capture_output=True).stdout
        if len(raw) < 640 * 360 * 3:
            continue
        found = facedet.faces(np.frombuffer(raw, np.uint8).reshape(360, 640, 3))
        if found:
            x, _, w, _ = found[0]
            xs.append((x + w / 2) / 640)
    return round(float(np.median(xs)), 3) if len(xs) >= 3 else None


def find_faces(work: str, name: str, folder: str, rels: list) -> int:
    """Measure where the face is in each recording not measured yet (saved in framing.json under `_face_x`). Returns how many were measured."""
    saved = load(work, name)
    have = saved.setdefault("_face_x", {})
    n = 0
    for rel in rels:
        if rel not in have:
            x = face_x(os.path.join(folder, rel))
            if x is not None:
                have[rel] = x
                n += 1
    if n:
        clipmap.write_json(path(work, name), saved)
    return n


def brief(work: str, name: str, folder: str, rels: list, fd: Path) -> str:
    """Take a frame from each recording and ask where the eyes are."""
    fd.mkdir(parents=True, exist_ok=True)
    lines = []
    for i, rel in enumerate(rels, start=1):
        src = os.path.join(folder, rel)
        try:
            dur = float(subprocess.run([FFPROBE, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", src], capture_output=True, text=True).stdout.strip())
        except ValueError:
            continue
        out = fd / f"{i:02d}.png"
        subprocess.run([FFMPEG, "-nostdin", "-y", "-v", "error", "-ss", f"{dur * 0.3:.2f}", "-i", src, "-frames:v", "1", "-vf", "scale=960:-1", str(out)], capture_output=True)
        if out.exists():
            lines.append(f"{out.name} = {rel}")
    (fd / "frames.txt").write_text("\n".join(lines), encoding="utf-8")
    return ("Each picture in this folder is one frame of the host talking to the camera (frames.txt says which recording each is). For each one say how far down the frame the host's eyes are, "
            "as a fraction of the picture height (0 = top edge, 1 = bottom edge; the line through the middle of both eyes). Look at every picture; do not guess from one. "
            'Write framing.json here: {"frames": [{"file": "01.png", "eye_y": 0.38}]}. Write nowhere else.')


def apply_answer(work: str, name: str, p: Path, fd: Path) -> tuple[bool, str]:
    import json
    try:
        raw = json.loads(Path(p).read_text(encoding="utf-8-sig")).get("frames", [])
        names = dict(ln.split(" = ", 1) for ln in (fd / "frames.txt").read_text(encoding="utf-8").splitlines() if " = " in ln)
    except (OSError, ValueError, AttributeError):
        return False, "Claude's answer could not be read."
    saved = load(work, name)
    n = 0
    for f in raw if isinstance(raw, list) else []:
        try:
            y = float(f["eye_y"])
        except (KeyError, TypeError, ValueError):
            continue
        if f.get("file") in names and EYE_MIN <= y <= EYE_MAX:
            saved[names[f["file"]]] = round(y, 3)
            n += 1
    if not n:
        return False, "Claude did not say where the eyes are."
    clipmap.write_json(path(work, name), saved)
    return True, f"Claude found the eye line in {n} recording{'' if n == 1 else 's'}."


def plan_zoom(pieces: list, min_hold: float, max_wide: float, edges: list = (), min_shot: float = 3.0) -> list:
    """pieces = [(start, end, intense)] in cut order -> the zoom of each (1.0 or ZOOM). A piece with an intense sentence is zoomed. The framing changes only
    when it has held for min_hold seconds (a change a second after the last one looks like a mistake), so a short piece takes the framing of the one before;
    a change is also held back when a cut to or from a cutaway (`edges`, seconds) lies within min_shot of it, unless it happens under the cutaway (then nobody sees it);
    after max_wide seconds without any zoom the next piece that may change is zoomed, so a long talking stretch does not stay flat."""
    out, state, changed = [], 1.0, -1e9
    since = pieces[0][0] if pieces else 0.0                                # when the framing last changed (the start counts)
    for p in pieces:
        a, z, intense = p[0], p[1], p[2]
        hidden = len(p) > 3 and p[3]
        blocked = not hidden and any(0.3 < abs(a - e) < min_shot for e in edges)
        want = ZOOM if intense else state
        if state == 1.0 and not intense and a - since >= max_wide and z - a >= 4.0:
            want = ZOOM
        if state > 1.0 and not intense and a - since >= max_wide / 2:
            want = 1.0                                                      # a zoom is not held for more than half the flat stretch
        if want != state and a - changed >= min_hold and not blocked:
            state, changed, since = want, a, a
        out.append(state)
    return out


def apply_zoom(work: str, name: str, emphasis: set | None = None) -> int:
    """Put the zoom plan on every talking beat whose recording has a known eye line. `emphasis` = the normalized sentences Claude called intense
    (cutreview.json). Returns how many pieces are zoomed."""
    import cutreview
    bp = beatmap.path_of(work, name)
    data = clipmap.read_json(bp, None)
    eyes = load(work, name)
    if not data:
        return 0
    emphasis = emphasis if emphasis is not None else {cutreview.norm(t) for t in cutreview.load(work, name).get("emphasis", [])}
    rows, pieces, edges, last_rel = [], [], [], None
    import locks
    locked = locks.beat_ids(work, name, data)                                    # a beat with a good-marked sentence keeps its framing as it is
    for b in data["beats"]:
        ar = b.get("aroll")
        if not ar or b.get("skip") or b.get("vo") or b["id"] in locked:
            continue
        b.setdefault("on_screen", {}).pop("punch", None)
        keep = ar.get("keep") or [[ar["in"], ar["out"]]]
        loud = [cutreview.norm(t) in emphasis for t, _ in cutreview.sentence_runs(b)]
        spans = [(ar["words"][idx[0]][1], ar["words"][idx[-1]][2]) for _, idx in cutreview.sentence_runs(b)]
        t = float(b.get("start", 0.0))
        covers = [(t + float(x.get("at", 0)), t + float(x.get("at", 0)) + float(x["dur"])) for x in b["on_screen"].get("broll", []) if x.get("file")]
        if last_rel is not None and ar["rel"] != last_rel:
            edges.append(t)
        last_rel = ar["rel"]
        for s0, s1 in covers:
            edges += [s0, min(s1, t + float(b["dur"]))]
        for k, (a, z) in enumerate(keep):
            hot = any(l and s0 < z and s1 > a for l, (s0, s1) in zip(loud, spans))
            pieces.append((t, t + (z - a), hot, any(s0 <= t < s1 for s0, s1 in covers)))
            rows.append((b, k))
            t += z - a
    rules = skillrules.rules()
    zooms = plan_zoom(pieces, rules["punch_hold_s"], rules["punch_flat_s"], edges, rules["min_piece_s"])
    zoomed = 0
    per_beat: dict = {}
    for (b, k), z in zip(rows, zooms):
        per_beat.setdefault(id(b), (b, []))[1].append(z)
    for b, zs in per_beat.values():
        ey = eyes.get(b["aroll"]["rel"])
        if ey is not None and b["on_screen"].get("shot", "a-roll") == "a-roll":
            fx = (eyes.get("_face_x") or {}).get(b["aroll"]["rel"])
            b["on_screen"]["punch"] = {"zooms": zs, "cy": ey, **({"cx": centre_crop(fx, ZOOM)} if fx is not None else {})}
            zoomed += sum(1 for x in zs if x > 1.0)
    clipmap.write_json(bp, data)
    return zoomed
