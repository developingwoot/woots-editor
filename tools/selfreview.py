"""Self-review (stage 6): Claude's checks on its own work, run on the stitched half-size preview BEFORE the host watches it.

Usage (editor venv; the app runs it as a job):
    python selfreview.py run <work> <name> [--only flash,face,...]     # writes <name>.selfreview.json + stills in selfreview\\
    python selfreview.py show <work> <name>

Needs <name>.preview-half.mp4 + <name>.stitch.json (Build tab: Stitch) and each section's out\\render.json.
The checks (the host's list, then two cheap extras). Every check reports whether it RAN, so "no findings" is never claimed
when a check was skipped:
    flash        a graphic (or take, or B-roll) on screen for a split second
    late_text    text that is fully on screen too late, or for too short a time, to read
    plays_twice  an animation that comes in twice (re-enters, moves again after landing, or the same graphic placed twice)
    face         a graphic sitting on the host's face (face found in the CLEAN footage under the graphic, overlapped with the graphic's alpha)
    repeat_word  a word or short phrase said twice in a row (re-transcribes the preview; notes when a cut caused it)
    lips         lips drifting from the voice (tools\\lipsync.py on the preview and on the source; the difference is the render's drift)
    dead_air     a long silence around a cut
    av_length    picture and sound of different lengths (drift)
Thresholds come from the video's workflow settings (min_visible_s, read_s_per_word, read_pad_s, lip_tolerance_frames).

<name>.selfreview.json:
  {"generated", "preview": {"file", "dur", "sig"}, "ran": {check: {"ran": bool, "note": str, "n": findings}},
   "findings": [{"id", "key", "check", "level": "fix"|"look", "t", "t_end", "beat", "section", "text", "fix", "still"}],
   "fixed_since_last": n, "settings": {...}}
The host's dismissals ("I looked, it is fine") live in <name>.selfreview.marks.json so they survive a re-run.
"""
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(os.path.abspath(__file__)).parent
EDITOR = HERE.parent
import config
WORK = config.WORK
PYV = config.PYTHON
sys.path.insert(0, str(HERE))
import workflow  # noqa: E402

CHECKS = [("flash", "A graphic flashes for a split second"), ("late_text", "Text lands too late to read"),
          ("plays_twice", "An animation plays twice"), ("face", "A graphic sits on the host's face"),
          ("repeat_word", "A word said twice in a row"), ("lips", "Lips drift from the voice"),
          ("dead_air", "Dead air at a cut"), ("av_length", "Picture and sound the same length")]
CHECK_IDS = [c[0] for c in CHECKS]
HITS = ("stamp", "burst")              # intentional quick hits: shorter is allowed (still >= 0.4 s)


def read_json(p: Path, default=None):
    if not p.exists():
        return default
    return json.loads(p.read_text(encoding="utf-8-sig"))


def _replace(tmp, p):
    for i in range(8):
        try:
            os.replace(tmp, p)
            return
        except PermissionError:
            if i == 7:
                raise
            time.sleep(0.05 * (i + 1))


import projectstore  # noqa: E402  (plan-file writes are recorded: ADR 0005)


def write_json(p: Path, data):
    projectstore.write_json(p, data)


def out_path(work, name):
    return WORK / work / f"{name}.selfreview.json"


def marks_path(work, name):
    return WORK / work / f"{name}.selfreview.marks.json"


def preview_path(work, name):
    try:                                                          # every stitch has its own file name (a player holding the old one open no longer blocks a new stitch)
        f = json.loads((WORK / work / f"{name}.stitch.json").read_text(encoding="utf-8-sig")).get("file")
        if f and (WORK / work / f).exists():
            return WORK / work / f
    except (OSError, ValueError):
        pass
    return WORK / work / f"{name}.preview-half.mp4"


def preview_sig(work, name) -> str:
    p = preview_path(work, name)
    if not p.exists():
        return ""
    st = p.stat()
    return f"{st.st_size}:{int(st.st_mtime)}"


def tl(t: float) -> str:
    return f"{int(t // 60)}:{t % 60:04.1f}"


# ----------------------------------------------------------------------------- state (stdlib only)
def state(work: str, name: str) -> dict:
    r = read_json(out_path(work, name))
    marks = (read_json(marks_path(work, name)) or {}).get("dismissed", {})
    out = {"ran": bool(r), "preview_ready": preview_path(work, name).exists(), "preview_file": preview_path(work, name).name, "generated": None, "stale": False, "checks": [],
           "findings": [], "dismissed": [], "counts": {"fix": 0, "look": 0, "dismissed": 0}, "clean": False, "all_checks_ran": False,
           "fixed_since_last": 0, "preview_dur": None}
    if not r:
        return out
    cur = preview_sig(work, name)
    out.update(generated=r["generated"], stale=bool(cur) and cur != (r.get("preview") or {}).get("sig"),
               fixed_since_last=r.get("fixed_since_last", 0), preview_dur=(r.get("preview") or {}).get("dur"))
    for cid, label in CHECKS:
        info = (r.get("ran") or {}).get(cid) or {"ran": False, "note": "not run"}
        out["checks"].append({"id": cid, "label": label, **info})
    for f in r["findings"]:
        if f["key"] in marks:
            out["dismissed"].append({**f, "why": marks[f["key"]].get("why", "")})
        else:
            out["findings"].append(f)
    for f in out["findings"]:
        out["counts"][f["level"]] += 1
    out["counts"]["dismissed"] = len(out["dismissed"])
    out["all_checks_ran"] = all(c["ran"] for c in out["checks"])
    out["clean"] = out["all_checks_ran"] and not out["findings"] and not out["stale"]
    return out


def dismiss(work: str, name: str, key: str, why: str = "") -> dict:
    p = marks_path(work, name)
    d = read_json(p) or {"dismissed": {}}
    d["dismissed"][key] = {"why": why.strip(), "t": time.strftime("%Y-%m-%dT%H:%M:%S")}
    write_json(p, d)
    return state(work, name)


def undismiss(work: str, name: str, key: str) -> dict:
    p = marks_path(work, name)
    d = read_json(p) or {"dismissed": {}}
    d["dismissed"].pop(key, None)
    write_json(p, d)
    return state(work, name)


# ----------------------------------------------------------------------------- media helpers
def _sr():
    import sectionrender                                   # ffmpeg/ffprobe lookup + the picture geometry
    return sectionrender


def tool_env() -> dict:
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    base = Path(os.environ.get("LOCALAPPDATA", ""))
    for p in base.glob("Microsoft/WinGet/Packages/Gyan.FFmpeg*/*/bin"):
        env["PATH"] = str(p) + os.pathsep + env.get("PATH", "")
        break
    return env


def probe(path, entries: str, stream: str | None = None) -> str:
    sr = _sr()
    cmd = [sr.FFPROBE, "-v", "error"] + (["-select_streams", stream] if stream else []) + ["-show_entries", entries, "-of", "csv=p=0", str(path)]
    return subprocess.run(cmd, capture_output=True, text=True).stdout.strip()


def grab_still(video, t: float, out: Path, w: int = 480):
    sr = _sr()
    out.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([sr.FFMPEG, "-nostdin", "-y", "-v", "error", "-ss", f"{max(0.0, t):.2f}", "-i", str(video), "-frames:v", "1",
                    "-vf", f"scale={w}:-2", "-q:v", "5", str(out)], capture_output=True)


def analyze_mov(path: str) -> dict | None:
    """Frame-by-frame facts about a rendered graphic (transparent MOV): when it appears, settles and leaves, whether it
    comes in twice. Works on a 160x90 copy. Returns None if the file cannot be read."""
    import numpy as np
    sr = _sr()
    fps_s = probe(path, "stream=r_frame_rate", "v:0")
    try:
        a, b = fps_s.split("/")
        fps = float(a) / float(b)
    except ValueError:
        fps = 30.0
    r = subprocess.run([sr.FFMPEG, "-nostdin", "-v", "error", "-i", str(path), "-vf", "scale=160:90:flags=area", "-f", "rawvideo",
                        "-pix_fmt", "rgba", "-"], capture_output=True)
    n = len(r.stdout) // (160 * 90 * 4)
    if n < 3:
        return None
    fr = np.frombuffer(r.stdout[: n * 160 * 90 * 4], np.uint8).reshape(n, 90, 160, 4)
    alpha = fr[..., 3].astype(np.float32) / 255.0
    prem = np.concatenate([fr[..., :3].astype(np.float32) * alpha[..., None], (alpha * 255.0)[..., None]], axis=3)
    cov = alpha.mean(axis=(1, 2))
    d = np.zeros(n, np.float32)
    d[1:] = np.abs(prem[1:] - prem[:-1]).mean(axis=(1, 2, 3))
    mx = float(cov.max())
    if mx < 0.0005:
        return None
    present = cov > max(0.0005, 0.15 * mx)
    appear = int(np.argmax(present))
    last = int(n - 1 - np.argmax(present[::-1]))
    gone = cov < max(0.0003, 0.05 * mx)
    reentries, run = 0, 0
    for i in range(appear, n):
        if present[i]:
            if run >= 3:
                reentries += 1
            run = 0
        elif gone[i]:
            run += 1
    peak = float(d[appear: appear + max(3, int(1.5 * fps))].max()) if n > appear else 0.0
    thr = max(0.08, 0.04 * peak)                           # small on purpose: a slow fade-in moves a little every frame
    K = max(3, int(round(0.25 * fps)))
    settle, never = None, False
    for i in range(appear, last + 1):                      # landed = fully there (alpha at its plateau) AND still for a moment
        if cov[i] >= 0.9 * mx and d[i + 1: i + 1 + K].max(initial=0) < thr and i + K <= last + 1:
            settle = i
            break
    if settle is None:
        settle, never = min(last, appear + int(0.5 * fps)), True
    ref = cov[settle]
    ok = np.where(cov[settle:] >= 0.95 * ref)[0]            # fully on screen until the exit fade has really begun
    readable_end = settle + (int(ok.max()) + 1 if len(ok) else 1)
    late = 0
    i = min(n - 1, settle + K)
    while i < readable_end:                                # motion after it landed, before it starts to leave
        if d[i] > 0.4 * max(peak, 1.0) and cov[i] >= 0.95 * ref:
            late += 1
            i += max(3, int(0.3 * fps))
        else:
            i += 1
    return {"fps": fps, "n": n, "appear": appear, "settle": settle, "last": last, "readable_end": readable_end, "maxcov": mx,
            "reentries": reentries, "late_bursts": late, "never_settles": never, "full_frame": bool(cov[settle] > 0.9),
            "alpha": alpha}


# ----------------------------------------------------------------------------- the timeline of the stitched preview
def timeline(work: str, name: str) -> dict:
    stitch = read_json(WORK / work / f"{name}.stitch.json")
    if not stitch:
        raise ValueError("no stitched preview yet: stitch the sections in the Build tab first")
    segs, overlays, brolls, joins = [], [], [], []
    for sec in stitch["sections"]:
        sb = WORK / work / "sections" / name / sec["id"]
        rj, ej = read_json(sb / "out" / "render.json"), read_json(sb / "section.edit.json")
        if not rj or not ej:
            raise ValueError(f"section {sec['id']} has no render.json: rebuild it")
        for s in rj["segments"]:
            segs.append({**s, "section": sec["id"], "start": sec["start"] + s["out_start"], "dur": s["out_dur"]})
        by_id = {s["id"]: s for s in segs if s["section"] == sec["id"]}
        for o in ej.get("overlays", []):
            overlays.append({**o, "section": sec["id"], "seg_info": by_id.get(o["seg"])})
        for b in ej.get("broll", []):
            brolls.append({**b, "section": sec["id"], "seg_info": by_id.get(b["seg"])})
    for a, b in zip(segs, segs[1:]):
        joins.append({"t": round(b["start"], 3), "from": a["id"], "to": b["id"]})
    return {"stitch": stitch, "segments": segs, "overlays": overlays, "broll": brolls, "joins": joins,
            "size": (read_json(WORK / work / "sections" / name / stitch["sections"][0]["id"] / "section.edit.json") or {}).get("size", [960, 540])}


def seg_at(t: float, segs: list):
    for s in segs:
        if s["start"] - 1e-6 <= t < s["start"] + s["dur"] + 1e-6:
            return s
    return None


# ----------------------------------------------------------------------------- the checks
class Ctx:
    def __init__(self, work, name, settings, T, beats, words, outdir):
        self.work, self.name, self.s, self.T, self.beats, self.words, self.outdir = work, name, settings, T, beats, words, outdir
        self.preview = preview_path(work, name)
        self.findings: list[dict] = []
        self.ran: dict = {}
        self.mov_cache: dict = {}

    def add(self, check, level, t, text, fix, beat=None, section=None, t_end=None, key=None, still=True):
        fid = f"F{len(self.findings) + 1:03d}"
        key = key or f"{check}:{beat or ''}:{round(t)}"
        f = {"id": fid, "key": key, "check": check, "level": level, "t": round(t, 2), "t_end": round(t_end, 2) if t_end else None,
             "beat": beat, "section": section, "text": text, "fix": fix, "still": None}
        if still:
            name = "s_" + hashlib.sha1(key.encode("utf-8")).hexdigest()[:10] + ".jpg"      # stable: survives a partial re-run
            grab_still(self.preview, t, self.outdir / name)
            f["still"] = name
        self.findings.append(f)
        return f

    def mov(self, path):
        st = Path(path).stat()
        k = (str(path), st.st_size, int(st.st_mtime))
        if k not in self.mov_cache:
            self.mov_cache[k] = analyze_mov(path)
        return self.mov_cache[k]

    def graphic_of(self, beat_id):
        b = next((x for x in self.beats if x["id"] == beat_id), None)
        return (b or {}).get("graphic") or {}


def find_words(words: list, phrase: str, near: float, window: float = 3.0):
    """Start time of the first occurrence of `phrase` in the preview's word list within `window` s of `near`."""
    toks = re.findall(r"[a-z0-9']+", phrase.lower())
    if not toks:
        return None
    seq = [(re.sub(r"[^a-z0-9']", "", w[0].lower()), w[1], w[2]) for w in words]
    seq = [x for x in seq if x[0]]
    for i in range(len(seq) - len(toks) + 1):
        if [x[0] for x in seq[i:i + len(toks)]] == toks and abs(seq[i][1] - near) <= window:
            return seq[i][1]
    return None


def check_flash(c: Ctx):
    s, n = c.s, 0
    for o in c.T["overlays"]:
        si = o.get("seg_info")
        if not si or not Path(o["file"]).exists():
            continue
        m = c.mov(o["file"])
        if not m:
            continue
        n += 1
        t0 = si["start"] + float(o.get("at", 0))
        seg_end = si["start"] + si["dur"]
        vis = (min(m["last"] + 1, int((seg_end - t0) * m["fps"])) - m["appear"]) / m["fps"]
        g = c.graphic_of(o["seg"])
        floor = 0.4 if g.get("kind") in HITS else s["min_visible_s"]
        if vis < floor:
            cut = (seg_end - t0) < (m["last"] + 1) / m["fps"] - 0.05
            c.add("flash", "fix", t0 + m["appear"] / m["fps"], f"The graphic on {o['seg']} is on screen for only {vis:.1f} s (minimum {floor:.1f} s)"
                  + (": the take ends before the graphic does" if cut else ""),
                  "Make the graphic start earlier or last longer" + (", or end the take later" if cut else "") + ", or cut it.", o["seg"], o["section"])
    for sg in c.T["segments"]:
        n += 1
        if sg["dur"] < 1.0:
            c.add("flash", "look", sg["start"], f"The take for {sg['id']} plays for only {sg['dur']:.1f} s: it will read as a flash cut",
                  "Join it to the take before or after it, or drop it.", sg["id"], sg["section"])
    for b in c.T["broll"]:
        n += 1
        si = b.get("seg_info")
        if si and b["dur"] < 2.0:
            c.add("flash", "look", si["start"] + b.get("at", 0), f"B-roll on {b['seg']} lasts {b['dur']:.1f} s (less than 2 s)",
                  "Hold it longer or use a punch-in instead.", b["seg"], b["section"])
    c.ran["flash"] = {"ran": True, "note": f"{n} graphics, takes and B-roll inserts measured", "n": sum(1 for f in c.findings if f["check"] == "flash")}


def check_late_text(c: Ctx):
    s, n, skipped = c.s, 0, 0
    for o in c.T["overlays"]:
        si, g = o.get("seg_info"), c.graphic_of(o["seg"])
        if not si or not g.get("text") or not Path(o["file"]).exists():
            continue
        m = c.mov(o["file"])
        if not m:
            skipped += 1
            continue
        n += 1
        t0 = si["start"] + float(o.get("at", 0))
        seg_end = si["start"] + si["dur"]
        settle_t = t0 + m["settle"] / m["fps"]
        end_t = min(t0 + m["readable_end"] / m["fps"], seg_end)
        readable = max(0.0, end_t - settle_t)
        words = len(g["text"].split())
        budget = max(s["min_visible_s"], words * s["read_s_per_word"]) + s["read_pad_s"]
        if readable < budget:
            c.add("late_text", "fix", settle_t, f"The text “{g['text'][:50]}” is fully on screen for {readable:.1f} s but needs {budget:.1f} s to read ({words} words)"
                  + (" (the animation never settles, so this is an estimate)" if m["never_settles"] else ""),
                  f"Land the text {budget - readable:.1f} s earlier, hold it {budget - readable:.1f} s longer, or shorten it.", o["seg"], o["section"], t_end=end_t)
        if c.words and g.get("words"):
            tw = find_words(c.words, g["words"], t0 + (m["settle"] / m["fps"]), 4.0)
            if tw is not None and settle_t - tw > 0.3:
                c.add("late_text", "fix", tw, f"The text on {o['seg']} is complete {settle_t - tw:.1f} s after you say “{g['words']}”",
                      f"Start the graphic {settle_t - tw:.1f} s earlier so it lands on the word.", o["seg"], o["section"], t_end=settle_t,
                      key=f"late_text:{o['seg']}:late")
    c.ran["late_text"] = {"ran": True, "note": f"{n} graphics with text measured" + (f", {skipped} unreadable" if skipped else "") + ("" if c.words else "; word timing skipped (no transcript)"),
                          "n": sum(1 for f in c.findings if f["check"] == "late_text")}


def check_plays_twice(c: Ctx):
    n, seen = 0, {}
    for o in c.T["overlays"]:
        si = o.get("seg_info")
        if not si or not Path(o["file"]).exists():
            continue
        m = c.mov(o["file"])
        if not m:
            continue
        n += 1
        t0 = si["start"] + float(o.get("at", 0))
        if m["reentries"]:
            c.add("plays_twice", "fix", t0, f"The graphic on {o['seg']} disappears and comes in again ({m['reentries']} time{'s' if m['reentries'] != 1 else ''})",
                  "Make it play once: remove the second entrance from the composition.", o["seg"], o["section"])
        elif m["late_bursts"]:
            c.add("plays_twice", "look", t0 + m["settle"] / m["fps"], f"The graphic on {o['seg']} moves again after it landed ({m['late_bursts']} burst{'s' if m['late_bursts'] != 1 else ''}): check it is not playing twice",
                  "Watch it; if the entrance repeats, remove the second pass.", o["seg"], o["section"])
        prev = seen.get(os.path.normcase(o["file"]))
        if prev is not None and t0 - prev < 15.0:
            c.add("plays_twice", "fix", t0, f"The same graphic file is used again {t0 - prev:.0f} s after its first use",
                  "Use it once, or make a different graphic for the second moment.", o["seg"], o["section"], key=f"plays_twice:dup:{o['seg']}")
        seen[os.path.normcase(o["file"])] = t0
    c.ran["plays_twice"] = {"ran": True, "note": f"{n} graphics analysed frame by frame", "n": sum(1 for f in c.findings if f["check"] == "plays_twice")}


def clean_frames(sg: dict, src_t: float, secs: float, rate: float, size):
    """BGR frames of the SOURCE under a segment, with the segment's own crop/zoom, no graphic on top."""
    import numpy as np
    sr = _sr()
    W, H = size
    vf = sr.base_filter(W, H, 30, float(sg.get("zoom") or 1.0), float(sg.get("cx", 0.5)), float(sg.get("cy", 0.4))) + f",fps={rate}"
    r = subprocess.run([sr.FFMPEG, "-nostdin", "-v", "error", "-ss", f"{src_t:.3f}", "-t", f"{secs:.3f}", "-i", sg["src"], "-vf", vf,
                        "-f", "rawvideo", "-pix_fmt", "bgr24", "-"], capture_output=True)
    k = W * H * 3
    n = len(r.stdout) // k
    return np.frombuffer(r.stdout[: n * k], np.uint8).reshape(n, H, W, 3) if n else None


def check_face(c: Ctx):
    import facedet
    import numpy as np
    if not facedet.available():
        c.ran["face"] = {"ran": False, "note": "no face model (models\\haarcascade_frontalface_default.xml)", "n": 0}
        return
    n, nofind = 0, 0
    W, H = c.T["size"]
    for o in c.T["overlays"]:
        si = o.get("seg_info")
        if not si or not Path(o["file"]).exists():
            continue
        m = c.mov(o["file"])
        if not m or m["full_frame"]:
            continue
        n += 1
        rate = 5.0
        t0 = si["start"] + float(o.get("at", 0))
        g0, g1 = m["settle"] / m["fps"], m["readable_end"] / m["fps"]
        g1 = min(g1, (si["start"] + si["dur"]) - t0)
        if g1 - g0 < 0.2:
            continue
        src_t = si["in"] + (t0 + g0 - si["start"])
        frames = clean_frames(si, src_t, g1 - g0, rate, (W, H))
        if frames is None:
            continue
        hits, found, worst = [], 0, 0.0
        for k in range(len(frames)):
            g = g0 + k / rate
            fi = min(m["n"] - 1, int(round(g * m["fps"])))
            faces = facedet.faces(frames[k])
            if not faces:
                hits.append(False)
                continue
            found += 1
            x, y, w, h = faces[0]
            ax0, ay0, ax1, ay1 = int(x * 160 / W), int(y * 90 / H), max(int(x * 160 / W) + 1, int((x + w) * 160 / W)), max(int(y * 90 / H) + 1, int((y + h) * 90 / H))
            cov = float((m["alpha"][fi, ay0:ay1, ax0:ax1] > 0.25).mean())
            worst = max(worst, cov)
            hits.append(cov >= 0.10)
        if found < max(1, len(frames) // 3):
            nofind += 1
            c.add("face", "look", t0 + g0, f"No face found in the footage under the graphic on {o['seg']}: could not check it is clear of your face",
                  "Look at it yourself.", o["seg"], o["section"], key=f"face:{o['seg']}:nofind")
            continue
        run = best = 0
        for hflag in hits:
            run = run + 1 if hflag else 0
            best = max(best, run)
        if best >= 2 or worst >= 0.4:
            c.add("face", "fix", t0 + g0, f"The graphic on {o['seg']} covers up to {int(worst * 100)}% of your face for about {best / rate:.1f} s",
                  "Move the graphic to a side or the lower third (clear of the face), shrink it, or make it a full-frame graphic.", o["seg"], o["section"], t_end=t0 + g1)
    note = f"{n} overlay graphics checked against the face in the clean footage" + (f"; {nofind} had no face to check" if nofind else "")
    c.ran["face"] = {"ran": True, "note": note, "n": sum(1 for f in c.findings if f["check"] == "face")}


def check_repeat_word(c: Ctx):
    if not c.words:
        c.ran["repeat_word"] = {"ran": False, "note": "the preview could not be transcribed", "n": 0}
        return
    seq = [(re.sub(r"[^a-z0-9']", "", w[0].lower()), w[1], w[2]) for w in c.words]
    seq = [x for x in seq if x[0]]
    flagged = set()
    for size in (6, 5, 4, 3, 2, 1):                          # longest repeated phrase first
        for i in range(len(seq) - 2 * size + 1):
            a, b = seq[i:i + size], seq[i + size:i + 2 * size]
            if i in flagged or any(j in flagged for j in range(i, i + 2 * size)):
                continue
            if [x[0] for x in a] == [x[0] for x in b] and b[0][1] - a[-1][2] < 0.8:
                if size == 1 and len(a[0][0]) < 2:
                    continue
                flagged.update(range(i, i + 2 * size))
                phrase = " ".join(x[0] for x in a)
                t = b[0][1]
                join = next((j for j in c.T["joins"] if abs(j["t"] - t) < 0.7 or (a[-1][2] - 0.2 <= j["t"] <= b[0][1] + 0.2)), None)
                cause = (f" It sits on the cut between {join['from']} and {join['to']}: one take ends with the word and the next starts with it."
                         if join else " It is in the speech itself, not at a cut.")
                c.add("repeat_word", "fix", a[0][1], f"“{phrase}” is said twice in a row at {tl(a[0][1])}.{cause}",
                      ("Trim the start of the next take (or the end of the previous one) past the repeated word." if join else "Cut one of the two."),
                      join["to"] if join else None, None, t_end=b[-1][2], key=f"repeat_word:{phrase}:{round(a[0][1])}")
    c.ran["repeat_word"] = {"ran": True, "note": f"{len(seq)} words from the preview's own transcript", "n": sum(1 for f in c.findings if f["check"] == "repeat_word")}


def check_lips(c: Ctx):
    try:
        import lipsync
    except Exception as e:                                   # noqa: BLE001
        c.ran["lips"] = {"ran": False, "note": f"lipsync tool unavailable: {e}", "n": 0}
        return
    tol_ms = c.s["lip_tolerance_frames"] * 1000.0 / 30.0
    cand = [sg for sg in c.T["segments"] if sg["dur"] >= 9.0 and not sg.get("broll")]
    step = max(1, len(cand) // 6)
    picks = cand[::step][:6]
    rows = []
    for sg in picks:
        dur = min(15.0, sg["dur"] - 1.0)
        pv = lipsync.measure(str(c.preview), sg["start"] + 0.5, dur)
        src = lipsync.measure(sg["src"], sg["in"] + 0.5, dur)
        if pv and src and pv[1] >= 0.12 and src[1] >= 0.12:
            rows.append({"seg": sg["id"], "t": sg["start"] + 0.5, "preview": pv[0], "source": src[0], "drift": pv[0] - src[0], "section": sg["section"]})
    if len(rows) < 2:
        c.ran["lips"] = {"ran": False, "note": f"only {len(rows)} of {len(picks)} windows had a face that could be measured (the tool needs the face to be at least ~12% of the frame width)", "n": 0}
        return
    import statistics
    drift = statistics.median(r["drift"] for r in rows)
    rec = statistics.median(r["source"] for r in rows)
    same = sum(1 for r in rows if (r["drift"] > 0) == (drift > 0) and abs(r["drift"]) > tol_ms / 2)
    if abs(drift) > tol_ms and same >= max(2, len(rows) // 2 + 1):
        r0 = max(rows, key=lambda r: abs(r["drift"]))
        c.add("lips", "fix", r0["t"], f"Your lips are {drift:+.0f} ms off your voice in the preview compared with the footage ({same} of {len(rows)} windows agree; tolerance {tol_ms:.0f} ms)",
              "The render shifted picture or sound: rebuild the sections; if it stays, the sound needs a delay of the opposite sign.", r0["seg"], r0["section"], key="lips:drift")
    if abs(rec) > tol_ms and sum(1 for r in rows if abs(r["source"]) > tol_ms / 2) >= max(2, len(rows) // 2 + 1):
        c.add("lips", "look", rows[0]["t"], f"The footage itself has your lips {rec:+.0f} ms off your voice (it was already like this before editing)",
              "Re-sync the recording (shift the audio) if it is noticeable.", rows[0]["seg"], rows[0]["section"], key="lips:recording")
    c.ran["lips"] = {"ran": True, "note": f"{len(rows)} windows: render drift {drift:+.0f} ms, recording {rec:+.0f} ms (one window is about +-100 ms noisy; the median is what counts)",
                     "n": sum(1 for f in c.findings if f["check"] == "lips")}


def check_dead_air(c: Ctx):
    import numpy as np
    sr = _sr()
    r = subprocess.run([sr.FFMPEG, "-nostdin", "-v", "error", "-i", str(c.preview), "-vn", "-ac", "1", "-ar", "16000", "-f", "f32le", "-"], capture_output=True)
    a = np.frombuffer(r.stdout, np.float32)
    if len(a) < 16000:
        c.ran["dead_air"] = {"ran": False, "note": "no audio to measure", "n": 0}
        return
    w = 80                                                   # 5 ms
    env = np.sqrt(np.mean(a[: len(a) // w * w].reshape(-1, w) ** 2, axis=1))
    silent = env < 10 ** (-55 / 20)
    for j in c.T["joins"]:
        i = int(j["t"] / 0.005)
        if i >= len(silent):
            continue
        lo = i
        while lo > 0 and silent[lo - 1]:
            lo -= 1
        hi = i
        while hi < len(silent) - 1 and silent[hi + 1]:
            hi += 1
        run = (hi - lo + 1) * 0.005 if silent[min(i, len(silent) - 1)] or silent[max(0, i - 1)] else 0.0
        if run > 0.8:
            c.add("dead_air", "look", j["t"], f"{run:.1f} s of silence around the cut between {j['from']} and {j['to']}",
                  f"Trim about {run - 0.5:.1f} s of the pause at the cut (the end of {j['from']} or the start of {j['to']}).", j["to"], None, t_end=j["t"] + 0.1,
                  key=f"dead_air:{j['from']}>{j['to']}")
    c.ran["dead_air"] = {"ran": True, "note": f"{len(c.T['joins'])} cuts measured (silence = below -55 dBFS)", "n": sum(1 for f in c.findings if f["check"] == "dead_air")}


def check_av_length(c: Ctx):
    n = 0
    files = [("the stitched preview", c.preview)] + [(f"section {s['id']}", WORK / c.work / "sections" / c.name / s["id"] / "out" / "preview-half.mp4") for s in c.T["stitch"]["sections"]]
    for label, p in files:
        if not Path(p).exists():
            continue
        v, a = probe(p, "stream=duration", "v:0"), probe(p, "stream=duration", "a:0")
        try:
            dv, da = float(v), float(a)
        except ValueError:
            continue
        n += 1
        if abs(dv - da) > 0.07:
            c.add("av_length", "fix", 0.0, f"In {label} the picture is {dv:.2f} s and the sound {da:.2f} s: {abs(dv - da) * 1000:.0f} ms apart, so sync drifts toward the end",
                  "Rebuild the section(s); if it persists, the sound needs resampling to the picture's length.", None, None, still=False, key=f"av_length:{label}")
    c.ran["av_length"] = {"ran": True, "note": f"{n} files measured (limit 70 ms)", "n": sum(1 for f in c.findings if f["check"] == "av_length")}


def transcribe_preview(work: str, name: str, outdir: Path):
    """Parakeet on the preview itself (loads the model once, a few seconds): [[word, start, end], ...] in preview time."""
    man, out = outdir / "transcribe.manifest.json", outdir / "preview.transcript.json"
    out.unlink(missing_ok=True)
    man.write_text(json.dumps([{"src": str(preview_path(work, name)), "out": str(out)}]), encoding="utf-8")
    r = subprocess.run([str(PYV), str(HERE / "analyze_takes.py"), str(man)], capture_output=True, text=True, encoding="utf-8", errors="replace",
                       env=tool_env(), cwd=HERE, stdin=subprocess.DEVNULL, timeout=1800)
    d = read_json(out)
    if r.returncode != 0 or not d:
        return None, (r.stdout + r.stderr).strip()[-200:]
    return [[w["word"], w["start"], w["end"]] for w in d.get("words", [])], ""


RUNNERS = {"flash": check_flash, "late_text": check_late_text, "plays_twice": check_plays_twice, "face": check_face,
           "repeat_word": check_repeat_word, "lips": check_lips, "dead_air": check_dead_air, "av_length": check_av_length}


# ----------------------------------------------------------------------------- run
def run(work: str, name: str, only: list[str] | None = None) -> dict:
    if not preview_path(work, name).exists():
        raise ValueError("no stitched preview yet: stitch the sections in the Build tab first")
    settings = {**workflow.DEFAULT_SETTINGS, **workflow.load(work, name)["settings"]}
    T = timeline(work, name)
    bm = read_json(WORK / work / f"{name}.beatmap.json") or {"beats": []}
    outdir = WORK / work / "selfreview"
    outdir.mkdir(exist_ok=True)
    old = read_json(out_path(work, name)) or {}
    words, why = None, ""
    todo = [c for c in CHECK_IDS if not only or c in only]
    if only and old and (old.get("preview") or {}).get("sig") != preview_sig(work, name):
        only, todo = None, list(CHECK_IDS)                      # the preview changed: old results are void, run everything
        print("the preview changed since the last run: running every check", flush=True)
    for f in old.get("findings", []):                            # stills of checks that re-run are replaced; the rest are kept
        if f.get("still") and f["check"] in todo:
            (outdir / f["still"]).unlink(missing_ok=True)
    if any(c in todo for c in ("repeat_word", "late_text")):
        print("TRANSCRIBE the stitched preview", flush=True)
        words, why = transcribe_preview(work, name, outdir)
        print(f"  {len(words) if words else 0} words {why}", flush=True)
    c = Ctx(work, name, settings, T, bm["beats"], words, outdir)
    for cid in todo:
        print(f"CHECK {cid}", flush=True)
        try:
            RUNNERS[cid](c)
        except Exception as e:                                       # noqa: BLE001 - a broken check must say so, not look clean
            c.ran[cid] = {"ran": False, "note": f"crashed: {type(e).__name__}: {e}"[:200], "n": 0}
        print(f"  -> {c.ran[cid]['note']}; {c.ran[cid].get('n', 0)} finding(s)", flush=True)
    if words is None and "repeat_word" in todo and "repeat_word" in c.ran and c.ran["repeat_word"].get("ran") is False:
        c.ran["repeat_word"]["note"] = f"the preview could not be transcribed: {why}"
    if only:                                                         # a partial run keeps the other checks' last results
        for cid in CHECK_IDS:
            if cid not in todo and cid in (old.get("ran") or {}):
                c.ran[cid] = old["ran"][cid]
        c.findings += [f for f in old.get("findings", []) if f["check"] not in todo]
    c.findings.sort(key=lambda f: (f["t"], f["check"]))
    for i, f in enumerate(c.findings, 1):
        f["id"] = f"F{i:03d}"
    keep = {f["still"] for f in c.findings if f.get("still")}
    for img in outdir.glob("*.jpg"):
        if img.name not in keep:
            img.unlink(missing_ok=True)
    old_open = {f["key"] for f in old.get("findings", [])}
    new_open = {f["key"] for f in c.findings}
    st = preview_path(work, name).stat()
    data = {"generated": time.strftime("%Y-%m-%dT%H:%M:%S"), "preview": {"file": preview_path(work, name).name, "dur": T["stitch"].get("dur"), "sig": preview_sig(work, name)},
            "ran": c.ran, "findings": c.findings, "fixed_since_last": len(old_open - new_open) if old else 0,
            "settings": {k: settings[k] for k in ("min_visible_s", "read_s_per_word", "read_pad_s", "lip_tolerance_frames")}}
    write_json(out_path(work, name), data)
    s = state(work, name)
    print(f"DONE {s['counts']['fix']} to fix, {s['counts']['look']} to look at; all checks ran: {s['all_checks_ran']}", flush=True)
    return s


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["run", "show"])
    ap.add_argument("work")
    ap.add_argument("name")
    ap.add_argument("--only", default="")
    a = ap.parse_args()
    try:
        s = run(a.work, a.name, [x for x in a.only.split(",") if x] or None) if a.cmd == "run" else state(a.work, a.name)
    except ValueError as e:
        sys.exit(f"selfreview: {e}")
    for ch in s["checks"]:
        print(f"  [{'x' if ch['ran'] else ' '}] {ch['label']}: {ch['note']}")
    for f in s["findings"]:
        print(f"  {f['level'].upper():4} {tl(f['t'])} {f['check']}: {f['text']}")


if __name__ == "__main__":
    main()
