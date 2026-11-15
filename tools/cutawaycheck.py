"""Claude looks at every cutaway next to the words said over it (the host 2026-11-14: a cutaway covered "we need to grease these rods" with
other footage, and nobody but the host saw it).

For each cutaway of the plan the run folder gets two pictures: the middle frame of the cutaway (`C01-cutaway.jpg`) and the frame of the talking
picture it covers at that moment (`C01-talking.jpg`), and `cutaways.json` lists what is said under it. Claude answers in check.json:

  {"cutaways": [{"id": "C01", "verdict": "fits" | "talking" | "wrong", "why": "one plain sentence"}]}

  fits     the cutaway shows what is being said
  talking  the talking picture already shows what is being said (the host's hands on the thing, the screen): the cutaway hides it
  wrong    the cutaway shows something else than what is said

An automatic cutaway that does not fit is taken out. One the host or a note placed stays, and the version's change list says what Claude saw.
"""
import json
import os
import subprocess
from pathlib import Path

import beatmap
import clipmap
import config
import locks
import recut

WORK = config.WORK
MAX_CUTAWAYS = 40            # pictures cost: a plan with more is checked for its first 40
VERDICTS = ("fits", "talking", "wrong")


def _frame(src: str, t: float, out: Path) -> bool:
    from sectionrender import FFMPEG
    subprocess.run([FFMPEG, "-nostdin", "-y", "-v", "error", "-ss", f"{max(0.0, t):.2f}", "-i", src, "-frames:v", "1", "-vf", "scale=640:-2", "-q:v", "4", str(out)], capture_output=True)
    return out.exists() and out.stat().st_size > 0


def said_under(beat: dict, at: float, dur: float) -> str:
    """The words of the beat that play while a cutaway of `dur` s starting `at` s into it is on screen."""
    spans = recut.covered_source(beat, at, dur)
    return " ".join(w[0] for w in beat["aroll"].get("words") or [] if any(a - 0.05 <= w[1] < b for a, b in spans))


def items(work: str, name: str) -> list:
    """Every cutaway that is a recording of the footage folder, in the order it plays: [{id, beat, index, auto, file, t_cutaway, rel, t_talking, said, at}]."""
    data = clipmap.read_json(beatmap.path_of(work, name), None) or {"beats": []}
    out = []
    for b in data["beats"]:
        if not b.get("aroll") or b.get("skip"):
            continue
        for i, x in enumerate((b.get("on_screen") or {}).get("broll") or []):
            if not x.get("file") or x.get("angle"):
                continue
            at, dur = float(x.get("at") or 0), float(x.get("dur") or 0)
            spans = recut.covered_source(b, at, dur)
            if not spans or dur <= 0:
                continue
            mid = spans[len(spans) // 2]
            out.append({"id": f"C{len(out) + 1:02d}", "beat": b["id"], "index": i, "auto": bool(x.get("auto")), "file": x["file"],
                        "t_cutaway": float(x.get("in") or 0) + dur * float(x.get("speed") or 1) / 2, "rel": b["aroll"]["rel"], "t_talking": (mid[0] + mid[1]) / 2,
                        "said": said_under(b, at, dur) or str(b.get("said", ""))[:200], "at": float(b.get("start") or 0) + at})
    return out[:MAX_CUTAWAYS]


def brief(work: str, name: str, fd: Path) -> str:
    """Write the pictures and cutaways.json into fd and return the prompt ('' when there is nothing to look at)."""
    fd.mkdir(parents=True, exist_ok=True)
    for old in fd.glob("C*.jpg"):
        old.unlink()
    folder = (clipmap.read_json(WORK / work / f"{name}.footage.json", {}) or {}).get("folder", "")
    rows = []
    for it in items(work, name):
        cut, talk = os.path.join(folder, it["file"]), os.path.join(folder, it["rel"])
        if not (folder and os.path.isfile(cut) and os.path.isfile(talk)):
            continue
        a, b = fd / f"{it['id']}-cutaway.jpg", fd / f"{it['id']}-talking.jpg"
        if _frame(cut, it["t_cutaway"], a) and _frame(talk, it["t_talking"], b):
            rows.append({"id": it["id"], "said": it["said"], "cutaway": a.name, "talking": b.name})
    (fd / "cutaways.json").write_text(json.dumps(rows, indent=1, ensure_ascii=False), encoding="utf-8")
    if not rows:
        return ""
    return ("The rough cut of the host's video puts cutaways (B-roll) over the talking. cutaways.json lists each one: `said` is what the host says while it is on screen, "
            "`cutaway` is a picture of the cutaway and `talking` is the picture of the host talking that the cutaway covers. Look at both pictures of every cutaway.\n"
            "Give each a verdict:\n"
            ' - "talking": the talking picture already shows what is being said (the host\'s hands on the thing, the thing being pointed at, the screen being talked about), so the cutaway hides the real demonstration. '
            "Words like \"these\", \"this one\", \"right here\" or \"you can see\" mean the host is showing it: check the talking picture.\n"
            ' - "wrong": the cutaway shows something else than what is being said (another part, another step, another program).\n'
            ' - "fits": the cutaway shows what is being said and the talking picture does not show it better (the host just faces the camera, or the cutaway is a closer look at the same thing).\n'
            "When unsure between fits and another verdict, say fits: taking out a good cutaway is worse than leaving an average one.\n"
            'Write check.json in this folder: {"cutaways": [{"id": "C01", "verdict": "fits|talking|wrong", "why": "<one plain sentence about what the pictures show, no ids or file names>"}]}. '
            "Give every id a verdict. Write nowhere else.")


def apply_answer(work: str, name: str, p: Path) -> tuple[bool, str, list]:
    """Take out the automatic cutaways Claude says do not fit. Returns (ok, message, change-list lines)."""
    try:
        raw = json.loads(Path(p).read_text(encoding="utf-8-sig")).get("cutaways", [])
    except (OSError, ValueError, AttributeError):
        return False, "Claude's look at the cutaways could not be read.", []
    seen = {str(r.get("id")): r for r in raw if isinstance(r, dict) and r.get("verdict") in VERDICTS} if isinstance(raw, list) else {}
    if not seen:
        return False, "Claude did not judge any cutaway.", []
    bp = beatmap.path_of(work, name)
    data = clipmap.read_json(bp, None) or {"beats": []}
    locked = locks.beat_ids(work, name, data)
    beats = {b["id"]: b for b in data["beats"]}
    drop, lines = {}, []
    for it in items(work, name):
        r = seen.get(it["id"])
        if not r or r["verdict"] == "fits":
            continue
        why = " ".join(str(r.get("why") or "").split())[:160]
        t = f"{int(it['at'] // 60)}:{int(it['at'] % 60):02d}"
        reason = "you are already showing it yourself" if r["verdict"] == "talking" else "it shows something else than what you say"
        if it["auto"] and it["beat"] not in locked:
            drop.setdefault(it["beat"], set()).add(it["index"])
            lines.append(f"Cutaway at {t} taken out ({reason}): {why}")
        else:
            lines.append(f"Check the cutaway at {t}, which you placed ({reason}): {why}")
    for bid, idx in drop.items():
        on = beats[bid]["on_screen"]
        on["broll"] = [x for i, x in enumerate(on["broll"]) if i not in idx]
    if drop:
        clipmap.write_json(bp, data)
    n = sum(len(v) for v in drop.values())
    return True, f"Claude looked at {len(seen)} cutaway{'' if len(seen) == 1 else 's'} and took out {n}.", lines
