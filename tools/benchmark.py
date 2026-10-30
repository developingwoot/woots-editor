"""The answer key for a rough cut (the host 2026-10-29): when he has already published a video from the same recordings, that video shows what he kept.
Its sentences are read once (Parakeet, cached in `<name>.published.json`) and compared with the sentences of our cut:
 - `missing`: lines of the published video our cut does not say (usually the lines that make a point understandable: the reason, the example, the setup);
 - `extra`: lines our cut says that the published video does not (takes he did not use, tangents).
    python tools/benchmark.py <work> <name> [published.mp4]
"""
import json
import re
import subprocess
import sys
from pathlib import Path

import beatmap
import clipmap
import config
import cutreview

WORK = config.WORK
SHARE = 0.6                                                  # a line is "found" when this share of its word triples is in the other side
PY = sys.executable


def grams(text: str, n: int = 3) -> set:
    w = re.findall(r"[a-z0-9']+", text.lower())
    return {tuple(w[i:i + n]) for i in range(max(0, len(w) - n + 1))}


def compare(published: list, cut: list, share: float = SHARE) -> dict:
    """published, cut = lists of sentences (text). Lines of fewer than 3 words are ignored."""
    pg, cg = set().union(*[grams(t) for t in cut]) if cut else set(), set().union(*[grams(t) for t in published]) if published else set()
    miss = [t for t in published if grams(t) and len(grams(t) & pg) / len(grams(t)) < share]
    extra = [t for t in cut if grams(t) and len(grams(t) & cg) / len(grams(t)) < share]
    n = len([t for t in published if grams(t)])
    return {"missing": miss, "extra": extra, "published_lines": n, "found_share": round(1 - len(miss) / n, 2) if n else 1.0}


def published_lines(work: str, name: str, video: str) -> list:
    cache = WORK / work / f"{name}.published.json"
    data = clipmap.read_json(cache, None)
    if not data:
        out = WORK / work / f"{name}.published.transcript.json"
        man = WORK / work / f"{name}.published.manifest.json"
        man.write_text(json.dumps([{"src": video, "out": str(out)}]), encoding="utf-8")
        r = subprocess.run([PY, str(Path(__file__).parent / "analyze_takes.py"), str(man)], cwd=Path(__file__).parent, capture_output=True, text=True)
        if r.returncode != 0 or not out.exists():
            raise RuntimeError("could not read the published video: " + (r.stdout + r.stderr)[-300:])
        data = {"video": video, "lines": [s["text"].strip() for s in json.loads(out.read_text(encoding="utf-8"))["segments"] if s.get("text", "").strip()]}
        clipmap.write_json(cache, data)
    return data["lines"]


def run(work: str, name: str, video: str) -> dict:
    cut = json.loads(beatmap.path_of(work, name).read_text(encoding="utf-8-sig"))
    mine = [s["text"] for s in cutreview.sentences(cut)]
    return compare(published_lines(work, name, video), mine)


if __name__ == "__main__":
    if len(sys.argv) < 4:
        sys.exit(__doc__)
    r = run(sys.argv[1], sys.argv[2], sys.argv[3])
    print(f"Published lines our cut says: {r['found_share']:.0%} of {r['published_lines']}")
    print("Missing from our cut:")
    for t in r["missing"]:
        print("  -", t[:140])
    print("Extra in our cut (not in the published video):")
    for t in r["extra"]:
        print("  -", t[:140])
