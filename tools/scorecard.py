"""How a finished video compares with reference videos (docs/quality-plan.md, phase 1).

Measures a video file: how often the picture changes, the longest stretch with no change, how much of the time is on the face, how often the framing of the face changes,
how fast the host talks and how soon the first shot of the thing (not the face) comes. Each number is shown next to the range of the reference videos: the ones in
`youtube-edit/references.json` (a study of maker and tech videos) and any the user added with `scorecard.py reference <video>` (kept in EDITOR_DATA/references).
A reading, never a rule: nothing is blocked by it.

  scorecard.py run <work> <name>                        the latest final of a project -> <work>/<name>.scorecard.json
  scorecard.py file <video> [transcript.json]           print the numbers for any video
  scorecard.py reference <video> [transcript.json] [label]   measure a reference video and keep it
"""
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import clipmap
import config
import skillrules

SCENE = 0.12            # scene-change threshold: low enough to see a cut between two shots of the same place
STEP_S = 1.0            # one frame looked at every this many seconds for the face
LONG_S = 15.0           # a shot longer than this counts as long
FACE_MIN_SCORE = 0.5    # a guess either way: lower also "sees" faces in dogs and machine parts, higher misses a host filmed wide (Nov 2026 study)
METRICS = [("changes_per_min", "Picture changes a minute", ""), ("median_shot_s", "Median shot", " s"), ("longest_s", "Longest stretch with no change", " s"),
           ("long_share", "Time in shots over 15 s", "%"), ("face_share", "Time with a face on screen (rough)", "%"),
           ("face_cuts_per_min", "Cuts from one face shot to another a minute", ""), ("words_per_min", "Words a minute", ""),
           ("first_thing_s", "First shot with no face", " s")]
REFS_FILE = "youtube-edit/references.json"


def refs_dir() -> Path:
    return config.EDITOR_DATA / "references"


# ----------------------------------------------------------------------------- the numbers (pure: the tests call these)
def shot_stats(cuts: list, dur: float) -> dict:
    """From the times the picture changed and the length: changes a minute, the median and longest shot, the share of time in shots over LONG_S."""
    marks = [0.0] + sorted(t for t in cuts if 0 < t < dur) + [dur]
    shots = sorted(b - a for a, b in zip(marks, marks[1:]) if b - a > 0)
    if not shots or dur <= 0:
        return {}
    mid = len(shots) // 2
    median = shots[mid] if len(shots) % 2 else (shots[mid - 1] + shots[mid]) / 2
    return {"changes_per_min": round((len(shots) - 1) / (dur / 60), 1), "median_shot_s": round(median, 1), "longest_s": round(shots[-1]),
            "long_share": round(100 * sum(s for s in shots if s > LONG_S) / dur)}


def face_stats(faces: list, cuts: list = (), step: float = STEP_S) -> dict:
    """`faces` = one entry a sampled frame (frame i at i * step s): True when a face is on screen. The share of frames with a face, the cuts a minute that go from a
    shot with a face to another shot with a face (a new angle or a new crop of the host: the frames a second either side both have one), and the time of the first
    frame with no face. Comparing face framings frame by frame does not work: the face finder's box jumps around on the same shot."""
    if not faces:
        return {}
    dur_min = len(faces) * step / 60
    at = lambda t: faces[int(t / step)] if 0 <= int(t / step) < len(faces) else False
    face_cuts = sum(1 for t in cuts if at(t - 1.0) and at(t + 1.0))
    first = next((i * step for i, f in enumerate(faces) if not f), None)
    return {"face_share": round(100 * sum(1 for f in faces if f) / len(faces)), "face_cuts_per_min": round(face_cuts / dur_min, 1), "first_thing_s": first}


def speech_stats(n_words: int, dur: float) -> dict:
    return {"words_per_min": round(n_words / (dur / 60))} if n_words and dur > 0 else {}


def ranges(videos: list) -> dict:
    """{metric: (low, high, n)} over the reference videos that have it."""
    out = {}
    for k, _, _ in METRICS:
        vals = [v[k] for v in videos if isinstance(v.get(k), (int, float))]
        if vals:
            out[k] = (min(vals), max(vals), len(vals))
    return out


def compare(numbers: dict, refs: dict) -> list:
    """One row a metric: its value, the reference range and where it sits (inside, below, above; '' without a range)."""
    rows = []
    for k, label, unit in METRICS:
        v = numbers.get(k)
        if v is None:
            continue
        lo, hi, n = refs.get(k, (None, None, 0))
        where = "" if lo is None else "below" if v < lo else "above" if v > hi else "inside"
        rows.append({"key": k, "label": label, "unit": unit, "value": v, "low": lo, "high": hi, "n": n, "where": where})
    return rows


def reference_videos() -> list:
    """The study's videos (the skill file) and the ones the user measured."""
    p = skillrules.find(REFS_FILE)
    vids = []
    try:
        vids = [v for v in json.loads(p.read_text(encoding="utf-8-sig")).get("videos", []) if isinstance(v, dict)] if p else []
    except (OSError, ValueError):
        pass
    for f in sorted(refs_dir().glob("*.json")) if refs_dir().is_dir() else []:
        try:
            vids.append(json.loads(f.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            continue
    return vids


# ----------------------------------------------------------------------------- reading a video
def duration(video: str) -> float:
    import sectionrender
    out = subprocess.run([sectionrender.FFMPEG, "-nostdin", "-hide_banner", "-i", str(video)], capture_output=True, text=True).stderr
    m = re.search(r"Duration: (\d+):(\d+):([\d.]+)", out)
    return int(m[1]) * 3600 + int(m[2]) * 60 + float(m[3]) if m else 0.0


def scene_changes(video: str) -> list:
    import sectionrender
    out = subprocess.run([sectionrender.FFMPEG, "-nostdin", "-hide_banner", "-i", str(video), "-an", "-vf", f"scale=640:-2,select='gt(scene,{SCENE})',showinfo", "-f", "null", "-"],
                         capture_output=True, text=True).stderr
    return [float(x) for x in re.findall(r"pts_time:([\d.]+)", out)]


def faces_in(video: str, step: float = STEP_S) -> list:
    import cv2
    import mpfaces
    import sectionrender
    if not mpfaces.available():                                            # no face model yet: no face numbers rather than "never a face"
        return []
    out = []
    with tempfile.TemporaryDirectory() as td:
        subprocess.run([sectionrender.FFMPEG, "-nostdin", "-v", "error", "-i", str(video), "-vf", f"fps=1/{step},scale=480:-2", "-q:v", "5", str(Path(td) / "f%05d.jpg")], check=True)
        for f in sorted(Path(td).glob("f*.jpg")):
            out.append(bool(mpfaces.faces(cv2.imread(str(f)), min_score=FACE_MIN_SCORE)))
    return out


def measure(video: str, n_words: int | None = None) -> dict:
    dur = duration(video)
    if dur <= 0:
        raise ValueError(f"cannot read the length of {video}")
    cuts = scene_changes(video)
    out = {"dur_s": round(dur), **shot_stats(cuts, dur), **face_stats(faces_in(video), cuts)}
    if n_words:
        out.update(speech_stats(n_words, dur))
    return out


def words_of_transcript(path) -> int:
    try:
        return len(json.loads(Path(path).read_text(encoding="utf-8")).get("words", []))
    except (OSError, ValueError):
        return 0


def words_of_cut(work: str, name: str) -> int:
    """The words the cut plays (the beat map's kept words), for a project's final."""
    import beatmap
    data = clipmap.read_json(beatmap.path_of(work, name), None) or {"beats": []}
    n = 0
    for b in data["beats"]:
        ar = b.get("aroll")
        if ar and not b.get("skip"):
            n += sum(1 for w in ar.get("words", []) if any(a - 0.001 <= (w[1] + w[2]) / 2 <= z + 0.001 for a, z in ar.get("keep") or [[ar.get("in", 0), ar.get("out", 0)]]))
    return n


def path(work: str, name: str) -> Path:
    return config.WORK / work / f"{name}.scorecard.json"


def load(work: str, name: str) -> dict | None:
    """The saved measurement with its comparison, or None."""
    got = clipmap.read_json(path(work, name), None)
    if not got:
        return None
    vids = reference_videos()
    got["rows"] = compare(got["numbers"], ranges(vids))
    got["n_refs"] = len(vids)
    return got


def run(work: str, name: str) -> dict:
    import finalrender
    st = finalrender.state(work, name)
    if not st["finals"]:
        raise ValueError("there is no final video to measure yet")
    latest = st["finals"][0]
    nums = measure(str(config.WORK / work / latest["file"]), words_of_cut(work, name))
    got = {"file": latest["file"], "numbers": nums}
    clipmap.write_json(path(work, name), got)
    return got


def main(argv):
    if len(argv) >= 3 and argv[0] == "run":
        print(json.dumps(run(argv[1], argv[2]), indent=1))
    elif len(argv) >= 2 and argv[0] in ("file", "reference"):
        nums = measure(argv[1], words_of_transcript(argv[2]) if len(argv) > 2 else None)
        if argv[0] == "reference":
            label = argv[3] if len(argv) > 3 else Path(argv[1]).stem
            nums["label"] = label
            refs_dir().mkdir(parents=True, exist_ok=True)
            clipmap.write_json(refs_dir() / (re.sub(r"[^\w-]+", "-", label).strip("-") + ".json"), nums)
        for r in compare(nums, ranges(reference_videos())):
            rng = "" if r["low"] is None else f"   references {r['low']:g}-{r['high']:g}{r['unit']} ({r['where']})"
            print(f"{r['label']:40} {r['value']:g}{r['unit']}{rng}")
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
