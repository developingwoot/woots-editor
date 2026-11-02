"""Shorts planning: how many shorts a video deserves, where its best visual moments are, and whether Claude's picks follow the rules (ADR 0006).

The host's rules: a short is 10 s to 3 min (favour under a minute), made of clips of the MAIN video that may come from several sections,
fast and visual, and each one is a complete thought. A 10-minute video does not get ten shorts: the count follows how many strong
moments the video really has, capped by its length.

Everything here is plain Python on the beat map (no Claude, no tokens): the page reports a recommendation before anything is asked of Claude.
Times are main-video (output) seconds, the same clock as the beat map's start/end.
"""
import json
import re
from pathlib import Path

import config
import skillrules

# The numbers (lengths, one short per N minutes, the cap, how strong a moment must be) are in the youtube-shorts skill: skillrules.shorts().
POPUPS = ("counter", "stamp", "burst", "kinetic")
CARDS = ("title", "end")


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
    r = skillrules.shorts()
    out = []
    for i, b in enumerate(live):
        if beat_score(b) < r["strong"]:
            continue
        lo = hi = i
        sec = b.get("section")
        t = 0.0
        while lo > 0 and live[lo - 1].get("section") == sec and t + live[lo - 1]["dur"] <= r["setup_s"]:      # the setup: what leads into it
            lo -= 1
            t += live[lo]["dur"]
        t = 0.0
        while hi < len(live) - 1 and live[hi + 1].get("section") == sec and t + live[hi + 1]["dur"] <= r["payoff_s"]:   # the payoff: what it leads to
            hi += 1
            t += live[hi]["dur"]
        out.append((lo, hi, i))
    merged = []
    for lo, hi, seed in sorted(out):
        if merged and lo <= merged[-1][1] + 1 and live[hi]["end"] - live[merged[-1][0]]["start"] <= r["max_moment_s"]:
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


CONTRAST = ("but", "instead", "however", "actually", "turns out", "the fix", "the problem", "the trick", "the secret", "the reason", "finally", "mistake", "wrong", "surprising")
PAYOFF = ("so ", "that's why", "which means", "and that's", "that is why", "this is why", "and it worked", "it works", "that fixed")


def window_score(text: str, dur: float, last: str = "") -> tuple[float, str]:
    """How much a stretch of speech looks like a complete little story, from what is said alone: questions, numbers, a turn ("but", "the fix") and a payoff at the end.
    Returns (score, the reason in a few words)."""
    low = text.lower()
    why = []
    score = 0.0
    q = min(2, low.count("?"))
    if q:
        score += q
        why.append("asks a question")
    nums = min(3, len(re.findall(r"\b\d+(?:\.\d+)?\b", low)))
    if nums:
        score += 0.5 * nums
        why.append("has numbers")
    turns = sum(1 for c in CONTRAST if re.search(r"\b" + re.escape(c) + r"\b", low))
    if turns:
        score += min(2.0, turns * 0.75)
        why.append("has a turn")
    if any(p in (last.lower() + " ") for p in PAYOFF):
        score += 1.0
        why.append("ends on a payoff")
    words = len(low.split())
    if dur and words / dur < 1.2:
        score -= 1.0                                   # slow talk with long pauses is not a tight short
    return round(score, 2), ", ".join(why)


def spoken_moments(segments: list[dict]) -> list[dict]:
    """Where in a video with no beat map the best little stories are, from the transcript alone: windows of whole segments that fit the skill's length, scored by
    window_score, the best first, none overlapping. Each is {start, end, dur, score, why, beats: [], sections: []}, the same shape as moments()."""
    r = skillrules.shorts()
    lo, hi, need = r["moment_min_s"], r["moment_max_s"], r["moment_min_score"]
    segs = [s for s in segments if s.get("text", "").strip()]
    found = []
    for i, first in enumerate(segs):
        for j in range(i, len(segs)):
            dur = segs[j]["end"] - first["start"]
            if dur > hi:
                break
            if dur < lo:
                continue
            text = " ".join(s["text"] for s in segs[i:j + 1])
            score, why = window_score(text, dur, segs[j]["text"])
            if score >= need:
                found.append({"start": round(first["start"], 2), "end": round(segs[j]["end"], 2), "dur": round(dur, 2), "score": score, "why": why[:1].upper() + why[1:],
                              "beats": [], "sections": []})
    found.sort(key=lambda m: -m["score"])
    out = []
    for m in found:
        if all(m["end"] <= k["start"] or m["start"] >= k["end"] for k in out):
            out.append(m)
    return out


def runtime_of(beats: list[dict]) -> float:
    return round(sum(b["dur"] for b in beats if not b.get("skip")), 2)


def recommend(beats: list[dict] | None, runtime_s: float | None = None, spoken: list[dict] | None = None) -> dict:
    """{runtime_s, by_length, strong, recommended, max, moments, reasons, confidence}. `beats` may be None (no beat map yet); `spoken` are the moments
    found from the transcript alone (spoken_moments) and are used only when there is no beat map."""
    runtime = runtime_s if runtime_s is not None else (runtime_of(beats) if beats else 0.0)
    minutes = runtime / 60.0
    r = skillrules.shorts()
    cap, per = r["hard_cap"], r["minutes_per_short"]
    by_length = max(1, min(cap, round(minutes / per))) if runtime else 0
    mo = moments(beats) if beats else []
    reasons = []
    if not runtime:
        return {"runtime_s": 0, "by_length": 0, "strong": 0, "recommended": 0, "max": 0, "moments": [], "confidence": "none",
                "reasons": ["There is no stitched or final video yet, so there is nothing to cut shorts from."]}
    mm = f"{int(runtime // 60)}:{int(runtime % 60):02d}"
    reasons.append(f"The video is {mm} long: about one short per {per:g} minutes keeps them from covering the same ground, so room for about {by_length}.")
    if beats is None and spoken:
        mo = spoken
        rec, conf = by_length, "medium"
        reasons.append(f"There is no beat map, so I read what is said: {len(mo)} stretch{'es' if len(mo) != 1 else ''} look like complete little stories.")
    elif beats is None:
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
    return {"runtime_s": round(runtime, 1), "by_length": by_length, "strong": len(mo), "recommended": rec, "max": min(cap, max(rec, by_length) + 2),
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


def hard_cap() -> int:
    return skillrules.shorts()["hard_cap"]


def validate(shorts: list[dict], runtime_s: float, count: int | None = None) -> list[str]:
    """Problems with a set of proposed shorts ([] = fine). Each short: {title, hook, ranges: [[a, b], ...], thought: {setup, point, payoff}}."""
    problems = []
    r = skillrules.shorts()
    min_s, max_s = r["min_s"], r["max_s"]
    for i, s in enumerate(shorts, 1):
        tag = f"short {i} ({s.get('title', '?')})"
        rs = s.get("ranges") or []
        if not rs or any(len(r) != 2 or not (r[1] > r[0] >= 0) for r in rs):
            problems.append(f"{tag}: ranges are not valid [start, end] pairs")
            continue
        if runtime_s and max(r[1] for r in rs) > runtime_s + 0.5:
            problems.append(f"{tag}: a range runs past the end of the video ({runtime_s:.0f} s)")
        d = total_s(rs)
        if d < min_s:
            problems.append(f"{tag}: {d:.0f} s is under the {min_s:.0f} s minimum")
        if d > max_s:
            problems.append(f"{tag}: {d:.0f} s is over the {max_s:.0f} s maximum")
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
    return [s.get("title", "?") for s in shorts if total_s(s.get("ranges") or []) > skillrules.shorts()["favour_s"]]


FIND_RULES = """You are choosing YouTube Shorts from the finished MAIN video of the channel. The goal: views, from fast, visual, complete little stories.

How many: make exactly {count} short{plural}{fewer}. Do not make more.

Rules (the host's):
{rules}

Write the result to candidates.json in the current folder (use the Write tool), exactly this shape and nothing else, best first:
[{{"title": "Never use a cold iron", "hook": "NEVER USE|A COLD IRON", "ranges": [[20.6, 40.7], [182.2, 195.9]], "thought": {{"setup": "...", "point": "...", "payoff": "..."}}, "visual": "what is on screen that makes it work", "why": "one sentence"}}]
"""


def find_rules(count: int, strong: int | None = None) -> str:
    fewer = ""
    if strong is not None and strong < count:
        fewer = f" (only {strong} strong visual moment{'s' if strong != 1 else ''} were found, so some of these will be weaker: still make {count} if the host asked for it, but put the best first)"
    return FIND_RULES.format(count=count, plural="" if count == 1 else "s", fewer=fewer, rules=skillrules.shorts_notes())


def moments_text(mo: list[dict]) -> str:
    if not mo:
        return "VISUAL MOMENTS: none were found in the beat map.\n"
    return "VISUAL MOMENTS found in the beat map (video seconds, best first):\n" + "\n".join(
        f"- {m['start']:.1f}-{m['end']:.1f} ({m['dur']:.0f} s, sections: {', '.join(s for s in m['sections'] if s) or '-'}): {m['why'] or 'a motion graphic or teaching point'}" for m in mo) + "\n"
