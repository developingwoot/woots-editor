"""Shorts planning: how many shorts a video deserves, where its best visual moments are, and whether Claude's picks follow the rules (ADR 0006).

The host's rules: a short is 10 s to 3 min (favour under a minute), made of clips of the MAIN video that may come from several sections,
fast and visual, and each one is a complete thought. A 10-minute video does not get ten shorts: the count follows how many strong
moments the video really has, capped by its length.

Everything here is plain Python on the beat map (no Claude, no tokens): the page reports a recommendation before anything is asked of Claude.
Times are main-video (output) seconds, the same clock as the beat map's start/end.
"""
import json
from pathlib import Path

import config

MIN_S, FAVOUR_S, MAX_S = 10.0, 60.0, 180.0
MINUTES_PER_SHORT = 3.5                  # the length cap: about one short per 3.5 minutes of video, never one per minute
HARD_CAP = 8                             # more than this is spam for one video, whatever its length
STRONG = 3.0                             # a moment needs a motion explainer or a teaching point to count as strong
POPUPS = ("counter", "stamp", "burst", "kinetic")
CARDS = ("title", "end")
SETUP_S, PAYOFF_S = 8.0, 8.0             # how much context to take before and after the seed beat, inside the same section
MAX_MOMENT_S = 90.0


def _read(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None


def beat_score(b: dict) -> float:
    """How visually interesting a beat is on screen, 0 to about 5. Title/end cards and skipped beats score 0."""
    if b.get("skip"):
        return 0.0
    g = b.get("graphic")
    s = 0.0
    if g and not g.get("struck"):
        kind = g.get("kind")
        if kind in CARDS:
            return 0.0
        if kind in POPUPS:
            s += 0.5
        else:
            s += 3.0 + 0.5 * ((g.get("strength") or 3) - 3)        # a motion explainer: strength 1..5 moves it 2..4
    if b.get("vo"):
        s += 1.5                                                    # a teaching point: a self-contained explanation
    if (b.get("on_screen") or {}).get("broll"):
        s += 1.0
    return round(s, 2)


def moments(beats: list[dict]) -> list[dict]:
    """Strong moments: each seed beat (score >= STRONG) widened with setup and payoff beats of the same section, then overlapping ones merged.
    [{start, end, dur, score, beats: [ids], sections: [...], why}] best first."""
    live = [b for b in beats if not b.get("skip")]
    out = []
    for i, b in enumerate(live):
        if beat_score(b) < STRONG:
            continue
        lo = hi = i
        sec = b.get("section")
        t = 0.0
        while lo > 0 and live[lo - 1].get("section") == sec and t + live[lo - 1]["dur"] <= SETUP_S:      # the setup: what leads into it
            lo -= 1
            t += live[lo]["dur"]
        t = 0.0
        while hi < len(live) - 1 and live[hi + 1].get("section") == sec and t + live[hi + 1]["dur"] <= PAYOFF_S:   # the payoff: what it leads to
            hi += 1
            t += live[hi]["dur"]
        out.append((lo, hi, i))
    merged = []
    for lo, hi, seed in sorted(out):
        if merged and lo <= merged[-1][1] + 1 and live[hi]["end"] - live[merged[-1][0]]["start"] <= MAX_MOMENT_S:
            merged[-1] = (merged[-1][0], max(merged[-1][1], hi), merged[-1][2] + [seed])
        else:
            merged.append((lo, hi, [seed]))
    res = []
    for lo, hi, seeds in merged:
        run = live[lo:hi + 1]
        scores = sorted((beat_score(live[s]) for s in seeds), reverse=True)
        res.append({"start": round(run[0]["start"], 2), "end": round(run[-1]["end"], 2), "dur": round(run[-1]["end"] - run[0]["start"], 2),
                    "score": round(scores[0] + 0.25 * sum(scores[1:]), 2), "beats": [b["id"] for b in run],
                    "sections": sorted({str(b.get("section") or "") for b in run}),
                    "why": next((live[s].get("why") for s in seeds if live[s].get("why")), "") or ""})
    return sorted(res, key=lambda m: -m["score"])


def runtime_of(beats: list[dict]) -> float:
    return round(sum(b["dur"] for b in beats if not b.get("skip")), 2)


def recommend(beats: list[dict] | None, runtime_s: float | None = None) -> dict:
    """{runtime_s, by_length, strong, recommended, max, moments, reasons, confidence}. `beats` may be None (no beat map yet)."""
    runtime = runtime_s if runtime_s is not None else (runtime_of(beats) if beats else 0.0)
    minutes = runtime / 60.0
    by_length = max(1, min(HARD_CAP, round(minutes / MINUTES_PER_SHORT))) if runtime else 0
    mo = moments(beats) if beats else []
    reasons = []
    if not runtime:
        return {"runtime_s": 0, "by_length": 0, "strong": 0, "recommended": 0, "max": 0, "moments": [], "confidence": "none",
                "reasons": ["There is no stitched or final video yet, so there is nothing to cut shorts from."]}
    mm = f"{int(runtime // 60)}:{int(runtime % 60):02d}"
    reasons.append(f"The video is {mm} long: about one short per {MINUTES_PER_SHORT:g} minutes keeps them from covering the same ground, so room for about {by_length}.")
    if beats is None:
        rec, conf = by_length, "low"
        reasons.append("There is no beat map to look at, so this is an estimate from the length alone.")
    elif not mo:
        rec, conf = 1, "low"
        reasons.append("The beat map has no strong visual moment (no motion graphic or teaching point), so I would make at most one short, from the best explanation.")
    else:
        rec, conf = min(len(mo), by_length), "high"
        reasons.append(f"I found {len(mo)} strong visual moment{'s' if len(mo) != 1 else ''} (a motion graphic or teaching point with its setup and payoff).")
        if len(mo) > by_length:
            reasons.append(f"That is more than the length allows, so I would keep the best {by_length}.")
        elif len(mo) < by_length:
            reasons.append("That is fewer than the length would allow, and a weak short is worse than none, so I would stop at the strong ones.")
    return {"runtime_s": round(runtime, 1), "by_length": by_length, "strong": len(mo), "recommended": rec, "max": min(HARD_CAP, max(rec, by_length) + 2),
            "moments": mo, "confidence": conf, "reasons": reasons}


def for_video(work: str, name: str) -> dict:
    wd = config.WORK / work
    bm = _read(wd / f"{name}.beatmap.json")
    beats = bm.get("beats") if isinstance(bm, dict) else None
    out = recommend(beats)
    out["has_beatmap"] = beats is not None
    return out


# ----------------------------------------------------------------------------- checking Claude's picks
def total_s(ranges) -> float:
    return sum(b - a for a, b in ranges)


def validate(shorts: list[dict], runtime_s: float, count: int | None = None) -> list[str]:
    """Problems with a set of proposed shorts ([] = fine). Each short: {title, hook, ranges: [[a, b], ...], thought: {setup, point, payoff}}."""
    problems = []
    for i, s in enumerate(shorts, 1):
        tag = f"short {i} ({s.get('title', '?')})"
        rs = s.get("ranges") or []
        if not rs or any(len(r) != 2 or not (r[1] > r[0] >= 0) for r in rs):
            problems.append(f"{tag}: ranges are not valid [start, end] pairs")
            continue
        if runtime_s and max(r[1] for r in rs) > runtime_s + 0.5:
            problems.append(f"{tag}: a range runs past the end of the video ({runtime_s:.0f} s)")
        d = total_s(rs)
        if d < MIN_S:
            problems.append(f"{tag}: {d:.0f} s is under the {MIN_S:.0f} s minimum")
        if d > MAX_S:
            problems.append(f"{tag}: {d:.0f} s is over the {MAX_S:.0f} s maximum")
        th = s.get("thought") or {}
        if not all(str(th.get(k, "")).strip() for k in ("setup", "point", "payoff")):
            problems.append(f"{tag}: it must state its setup, point and payoff (a complete thought)")
    for i in range(len(shorts)):
        for j in range(i + 1, len(shorts)):
            a, b = shorts[i].get("ranges") or [], shorts[j].get("ranges") or []
            shared = sum(max(0.0, min(x1, y1) - max(x0, y0)) for x0, x1 in a for y0, y1 in b)
            small = min(total_s(a) or 1e9, total_s(b) or 1e9)
            if shared / small > 0.25:
                problems.append(f"short {i + 1} and short {j + 1} cover the same part of the video")
    if count is not None and len(shorts) > count:
        problems.append(f"{len(shorts)} shorts were proposed but {count} were asked for")
    return problems


def long_ones(shorts: list[dict]) -> list[str]:
    """Not errors: shorts over a minute are allowed when the story needs it, but worth a second look."""
    return [s.get("title", "?") for s in shorts if total_s(s.get("ranges") or []) > FAVOUR_S]


FIND_RULES = """You are choosing YouTube Shorts from the finished MAIN video of the channel. The goal: views, from fast, visual, complete little stories.

How many: make exactly {count} short{plural}{fewer}. Do not make more.

Hard rules (the host's):
- Length: {min_s} seconds to {max_s} seconds in total. Favour under a minute: 15 to 45 seconds is ideal. A short may be as brief as 15 seconds IF it holds a complete thought.
- A COMPLETE THOUGHT: a viewer who never saw the long video must get a beginning, a point and a payoff (setup: what the question or problem is; point: the idea or action; payoff: the answer, result or punchline). State all three in "thought".
- A short is made of clips of the main video. The clips may come from DIFFERENT sections, in any order that makes the story work, joined by cuts. Never change what the host said.
- Fast and visual: prefer the most visually interesting parts of the video, the places with a motion graphic or animation, a teaching point, B-roll or a physical demonstration. The VISUAL MOMENTS list below is a starting point, not a limit.
- Choose by BEST part, not by position: do not spread the shorts evenly through the video and never cover the same point twice. No intro, outro, subscribe ask or sponsor-like lines.
- Start on the hook (the interesting claim or question), never on "so", "and" or an unfinished thought. End on the payoff, after a sentence ends.
- A later "tighten" pass cuts filler and tangents inside each short, so pick a slightly wider range than the final length.
- hook = the title shown over the first 2.8 s: 2 to 5 words, uppercase, max 3 lines separated with |, a promise or a question, no clickbait lies.
- Times are MAIN-VIDEO seconds taken from the transcript lines below: the start of the first word you keep and the end of the last word you keep.

Write the result to candidates.json in the current folder (use the Write tool), exactly this shape and nothing else, best first:
[{{"title": "Never use a cold iron", "hook": "NEVER USE|A COLD IRON", "ranges": [[20.6, 40.7], [182.2, 195.9]], "thought": {{"setup": "...", "point": "...", "payoff": "..."}}, "visual": "what is on screen that makes it work", "why": "one sentence"}}]
"""


def find_rules(count: int, strong: int | None = None) -> str:
    fewer = ""
    if strong is not None and strong < count:
        fewer = f" (only {strong} strong visual moment{'s' if strong != 1 else ''} were found, so some of these will be weaker: still make {count} if the host asked for it, but put the best first)"
    return FIND_RULES.format(count=count, plural="" if count == 1 else "s", fewer=fewer, min_s=int(MIN_S), max_s=int(MAX_S))


def moments_text(mo: list[dict]) -> str:
    if not mo:
        return "VISUAL MOMENTS: none were found in the beat map.\n"
    return "VISUAL MOMENTS found in the beat map (video seconds, best first):\n" + "\n".join(
        f"- {m['start']:.1f}-{m['end']:.1f} ({m['dur']:.0f} s, sections: {', '.join(s for s in m['sections'] if s) or '-'}): {m['why'] or 'a motion graphic or teaching point'}" for m in mo) + "\n"
