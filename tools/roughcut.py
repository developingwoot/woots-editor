"""Build a rough-cut edit plan from a Parakeet transcript.

Two kinds of cuts:
  * automatic: pauses longer than --max-pause are shortened (each side keeps a
    little padding so speech never sounds clipped);
  * editorial: time ranges listed in a drops file, each with a reason. These are
    the judgment calls (weak answers, tangents, retakes) and are easy to undo by
    deleting the entry and re-running.

Usage:
    python roughcut.py <transcript.json> [--drops drops.json] [--out edit.json]

drops.json:  [{"start": 453.1, "end": 521.2, "reason": "..."}, ...]
"""
import argparse
import difflib
import json
import re
import sys
from pathlib import Path


def norm(text: str) -> list[str]:
    return re.sub(r"[^a-z0-9' ]", "", text.lower()).split()


def speech_spans(words, max_pause):
    """Group words into spans separated by pauses longer than max_pause."""
    spans = []
    for w in words:
        if spans and w["start"] - spans[-1][1] <= max_pause:
            spans[-1][1] = w["end"]
        else:
            spans.append([w["start"], w["end"]])
    return spans


def subtract(keeps, drops):
    out = []
    for s, e in keeps:
        pieces = [(s, e)]
        for d in drops:
            nxt = []
            for ps, pe in pieces:
                if d["end"] <= ps or d["start"] >= pe:
                    nxt.append((ps, pe))
                    continue
                if d["start"] > ps:
                    nxt.append((ps, d["start"]))
                if d["end"] < pe:
                    nxt.append((d["end"], pe))
            pieces = nxt
        out.extend(pieces)
    return out


def find_retakes(segments, window=12.0, prefix=4, threshold=0.8):
    """Flag a segment that restarts with the same words as the one just before it."""
    flags = []
    for a, b in zip(segments, segments[1:]):
        if b["start"] - a["end"] > window:
            continue
        wa, wb = norm(a["text"])[:prefix], norm(b["text"])[:prefix]
        if len(wa) >= 2 and difflib.SequenceMatcher(None, wa, wb).ratio() >= threshold:
            flags.append({"start": a["start"], "end": a["end"],
                          "note": f"possible retake of: {b['text'][:60]}"})
    return flags


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("transcript", type=Path)
    ap.add_argument("--drops", type=Path, help="editorial cuts (JSON list of start/end/reason)")
    ap.add_argument("--out", type=Path, help="edit plan path (default: <name>.edit.json)")
    ap.add_argument("--sections", type=Path,
                    help='{"sections": [{"id", "src": [a, b], "chapter"}...]} in OUTPUT order (re-orders the edit)')
    ap.add_argument("--shots", type=Path, help="camera angles (shots.json) to snap block edges to")
    ap.add_argument("--protect", type=Path, nargs="*",
                    help="graphics/B-roll plans whose windows keep their pauses untouched")
    # Defaults tuned on the co-host Interview2: 0.5s/0.12/0.22 felt "jump, jump, jump"
    # with no breath, so only real pauses are cut and ~0.55s of breath remains.
    ap.add_argument("--max-pause", type=float, default=1.0, help="pauses longer than this get cut (s)")
    ap.add_argument("--pad-before", type=float, default=0.2, help="lead-in kept before speech (s)")
    ap.add_argument("--pad-after", type=float, default=0.35, help="tail kept after speech (s)")
    ap.add_argument("--min-saving", type=float, default=0.5, help="skip cuts that remove less than this (s)")
    ap.add_argument("--min-keep", type=float, default=0.3, help="drop keep slivers shorter than this (s)")
    args = ap.parse_args()

    t = json.loads(args.transcript.read_text(encoding="utf-8"))
    duration = t["duration"]

    keeps = []
    for s, e in speech_spans(t["words"], args.max_pause):
        s, e = max(0.0, s - args.pad_before), min(duration, e + args.pad_after)
        # A cut that saves only a fraction of a second isn't worth the jump.
        if keeps and s - keeps[-1][1] < args.min_saving:
            keeps[-1][1] = e
        else:
            keeps.append([s, e])

    # Never shorten pauses inside a graphic or B-roll window: animations are timed to the
    # original speech (e.g. a drumroll fills the pause before the co-host's rating).
    protect = []
    for p in args.protect or []:
        for o in json.loads(p.read_text(encoding="utf-8")):
            if "dur" in o:
                protect.append((o["src_start"], o["src_start"] + o["dur"]))
            else:
                import subprocess
                dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of",
                                            "default=nw=1:nk=1", o["file"]], capture_output=True, text=True).stdout)
                end = max(b for _, b in o.get("show") or [[0, dur]])
                protect.append((o["src_start"], o["src_start"] + end))
    merged = []
    for s, e in keeps:
        if merged and any(a < s and merged[-1][1] < b for a, b in protect):
            merged[-1][1] = e
        else:
            merged.append([s, e])
    keeps = merged

    drops = json.loads(args.drops.read_text(encoding="utf-8")) if args.drops else []
    keeps = [(round(s, 3), round(e, 3)) for s, e in subtract(keeps, drops) if e - s >= args.min_keep]

    # Optional re-ordering: split keeps at block boundaries and emit them block by block.
    sections_out = []
    if args.sections:
        order = json.loads(args.sections.read_text(encoding="utf-8"))["sections"]
        cams = [s["start"] for s in json.loads(args.shots.read_text(encoding="utf-8"))["shots"]] if args.shots else []
        snap = lambda t: next((c for c in cams if abs(c - t) <= 0.5), t)
        reordered, t_out = [], 0.0
        for sec in order:
            # Snap block edges onto camera-angle changes within 0.5 s, or the block carries a few
            # frames of the neighbouring angle across the join (a flash of a third shot).
            a, b = snap(sec["src"][0]), snap(sec["src"][1])
            pieces = [(max(s, a), min(e, b)) for s, e in keeps if e > a and s < b]
            pieces = [(round(s, 3), round(e, 3)) for s, e in pieces if e - s >= args.min_keep]
            sections_out.append({"id": sec["id"], "chapter": sec.get("chapter", sec["id"]),
                                 "src": [a, b], "out_start": round(t_out, 2)})
            reordered += pieces
            t_out += sum(e - s for s, e in pieces)
        keeps = reordered

    kept = sum(e - s for s, e in keeps)
    dropped = sum(d["end"] - d["start"] for d in drops)
    plan = {
        "source": t["source"],
        "duration": duration,
        "params": {k: getattr(args, k) for k in ("max_pause", "pad_before", "pad_after", "min_saving", "min_keep")},
        "drops": drops,
        "flags": find_retakes(t["segments"]),
        "keeps": keeps,
        "sections": sections_out,
        "stats": {"kept": round(kept, 1), "editorial_cut": round(dropped, 1),
                  "pause_cut": round(duration - kept - dropped, 1), "pieces": len(keeps)},
    }
    out = args.out or args.transcript.with_name(args.transcript.name.replace(".transcript.json", ".edit.json"))
    out.write_text(json.dumps(plan, indent=2), encoding="utf-8")

    st = plan["stats"]
    print(f"{duration/60:.1f} min -> {kept/60:.1f} min  "
          f"(pauses -{st['pause_cut']:.0f}s, editorial -{st['editorial_cut']:.0f}s, {st['pieces']} pieces)")
    for f in plan["flags"]:
        print(f"  flag {f['start']:.1f}s: {f['note']}")
    print(f"-> {out}")


if __name__ == "__main__":
    sys.exit(main())
