"""Audience retention of a published video, lined up with its cut: where viewers left, where they watched again, and what was on screen then.

YouTube records what share of the viewers is still watching at each point of a video (YouTube Studio > Analytics > Engagement > Audience retention;
"See more" has an export). The host imports that export on the Final screen. This module reads it, finds the moments that matter and says what
the video was doing at each, from the final's own transcript, chapters and timeline.

  parse(data)                 the export as bytes or text (a .csv, the .zip Studio downloads, pasted text, or the Analytics API's JSON) -> [(position, share)]
  analyse(points, total)      -> {hook, average, end, drops: [{t, t_end, lost}], spikes: [{t, t_end, gained}]}
  what_at(work, name, t)      -> {said, chapter, picture, unchanged_s}: what the final shows and says at second t
  save / load / view          `<name>.retention.json` and what the Final screen shows
  overview()                  every video with retention, for comparing them

What it does not do: change a rule. Two videos prove nothing (the topic and the title move retention more than the editing does); the numbers of each
video are kept so that patterns can be read once there are enough.
"""
import csv
import io
import json
import re
import statistics
import time
import zipfile
from pathlib import Path

import config
import projectstore

WORK = config.WORK
HOOK_S = 30.0                # the share of viewers still there after this long is the hook's result
DROP_MIN = 0.01              # a drop counts when it loses this share of the viewers more than the usual decline over the same stretch
SPIKE_MIN = 0.003            # a rise of this much is viewers watching a part again
MAX_DROPS, MAX_SPIKES = 5, 3
LONG_SHOT_S = 30.0           # a picture unchanged this long is worth saying


def path(work: str, name: str) -> Path:
    return WORK / work / f"{name}.retention.json"


# ----------------------------------------------------------------------------- reading the export
def _num(s):
    s = str(s).strip().replace("%", "").replace(" ", "").replace(" ", "")
    if re.fullmatch(r"\d+:\d{2}(:\d{2})?(\.\d+)?", s):
        parts = [float(x) for x in s.split(":")]
        return sum(p * 60 ** i for i, p in enumerate(reversed(parts))), True
    if re.fullmatch(r"-?\d+,\d+", s):                       # a decimal comma
        s = s.replace(",", ".")
    try:
        return float(s), False
    except ValueError:
        return None, False


def _table(text: str) -> list:
    text = text.lstrip("﻿")
    first = next((ln for ln in text.splitlines() if ln.strip()), "")
    delim = max(("\t", ";", ","), key=first.count)
    return [r for r in csv.reader(io.StringIO(text), delimiter=delim) if any(c.strip() for c in r)]


def _from_rows(rows: list) -> list:
    """[(position, share)] from a table. The position column is the one named position / elapsed / time / ratio, the retention column the one named
    absolute, else audience retention / watch ratio (never the 'relative' one); without names, the first two columns of numbers."""
    if not rows:
        return []
    head = [c.strip().lower() for c in rows[0]]
    named = any(_num(c)[0] is None for c in rows[0])
    pos = ret = None
    if named:
        pos = next((i for i, c in enumerate(head) if re.search(r"position|elapsed|\btime\b|ratio", c) and "retention" not in c and "watch" not in c), None)
        for want in (r"absolute", r"audience ?watch ?ratio|audiencewatchratio", r"retention"):
            ret = next((i for i, c in enumerate(head) if re.search(want, c) and "relative" not in c and i != pos), None)
            if ret is not None:
                break
        rows = rows[1:]
    if pos is None or ret is None:
        pos, ret = 0, 1
    got, timed = [], False
    for r in rows:
        if len(r) <= max(pos, ret):
            continue
        (p, is_time), (v, _) = _num(r[pos]), _num(r[ret])
        if p is None or v is None:
            continue
        timed = timed or is_time
        got.append((p, v))
    if len(got) < 5:
        return []
    top_p, top_v = max(p for p, _ in got), max(v for _, v in got)
    unit = "seconds" if timed or top_p > 100.5 else "percent" if top_p > 1.5 else "ratio"
    scale_v = 100.0 if top_v > 3.0 else 1.0                   # shares over 3 are per cent (a video is never watched three times over on average)
    out = [((p, unit), v / scale_v) for p, v in got]
    return sorted(out, key=lambda x: x[0][0])


def parse(data) -> list:
    """The retention graph in an export: [((position, 'ratio'|'percent'|'seconds'), share of viewers 0..1+)], in order. Raises ValueError when there is none."""
    if isinstance(data, bytes) and data[:2] == b"PK":
        try:
            z = zipfile.ZipFile(io.BytesIO(data))
        except zipfile.BadZipFile:
            raise ValueError("that zip file could not be opened") from None
        best = []
        for n in z.namelist():
            if n.lower().endswith((".csv", ".tsv", ".txt")):
                try:
                    got = parse(z.read(n))
                except ValueError:
                    continue
                best = got if len(got) > len(best) else best
        if not best:
            raise ValueError("none of the files in that zip has a retention graph in it")
        return best
    if isinstance(data, bytes):
        for enc in ("utf-8-sig", "utf-16", "latin-1"):
            try:
                data = data.decode(enc)
                break
            except (UnicodeDecodeError, UnicodeError):
                continue
    text = str(data).strip()
    rows = []
    if text[:1] in "[{":
        try:
            j = json.loads(text)
            raw = j.get("rows") if isinstance(j, dict) else j
            rows = [[str(c) for c in r] for r in raw if isinstance(r, list)]
            if isinstance(j, dict) and j.get("columnHeaders"):
                rows.insert(0, [str(h.get("name", "")) for h in j["columnHeaders"]])
        except (ValueError, TypeError, AttributeError):
            rows = []
    out = _from_rows(rows or _table(text))
    if not out:
        raise ValueError("there is no retention graph in that file: it needs a column with the place in the video and one with the share of viewers still watching")
    return out


def normalise(points: list, total: float) -> list:
    """[(seconds, share)] for a video `total` seconds long."""
    out = []
    for (p, unit), v in points:
        t = p if unit == "seconds" else p / 100.0 * total if unit == "percent" else p * total
        if -0.001 <= t <= total * 1.02 + 1:
            out.append((round(max(0.0, min(total, t)), 2), round(v, 4)))
    return out


# ----------------------------------------------------------------------------- the moments that matter
def _at(curve: list, t: float) -> float:
    if t <= curve[0][0]:
        return curve[0][1]
    for (a, va), (b, vb) in zip(curve, curve[1:]):
        if a <= t <= b:
            return va + (vb - va) * ((t - a) / (b - a) if b > a else 0)
    return curve[-1][1]


def _runs(flags: list) -> list:
    out, start = [], None
    for i, f in enumerate(flags + [False]):
        if f and start is None:
            start = i
        elif not f and start is not None:
            out.append((start, i - 1))
            start = None
    return out


def analyse(curve: list, total: float) -> dict:
    """`curve` = [(seconds, share)]. The hook is the share still watching at HOOK_S. A drop is a stretch that loses viewers faster than the video
    usually does (the usual decline is the median step after the hook): `lost` is what it lost beyond that. A spike is a stretch where the share
    rises: viewers skipped back to it or came straight to it."""
    if len(curve) < 5 or total <= 0:
        raise ValueError("the retention graph has too few points")
    hook_t = min(HOOK_S, total / 4)
    body = [i for i in range(len(curve) - 1) if curve[i][0] >= hook_t]
    steps = [curve[i + 1][1] - curve[i][1] for i in range(len(curve) - 1)]
    usual = statistics.median([steps[i] for i in body]) if body else 0.0
    drops = []
    for a, b in _runs([i in set(body) and steps[i] - usual < -DROP_MIN / 3 for i in range(len(steps))]):
        lost = -(sum(steps[a:b + 1]) - usual * (b - a + 1))
        if lost >= DROP_MIN:
            drops.append({"t": curve[a][0], "t_end": curve[b + 1][0], "lost": round(lost, 4)})
    spikes = []
    for a, b in _runs([i in set(body) and steps[i] > 0 for i in range(len(steps))]):
        gained = sum(steps[a:b + 1])
        if gained >= SPIKE_MIN:
            spikes.append({"t": curve[a][0], "t_end": curve[b + 1][0], "gained": round(gained, 4)})
    return {"hook": round(_at(curve, hook_t), 4), "hook_s": round(hook_t, 1), "average": round(statistics.fmean(v for _, v in curve), 4), "end": curve[-1][1],
            "usual_step": round(usual, 5),
            "drops": sorted(sorted(drops, key=lambda d: -d["lost"])[:MAX_DROPS], key=lambda d: d["t"]),
            "spikes": sorted(sorted(spikes, key=lambda d: -d["gained"])[:MAX_SPIKES], key=lambda d: d["t"])}


# ----------------------------------------------------------------------------- what the video was doing
def final_facts(work: str, name: str) -> dict:
    """What is known about the newest final: {dur, chapters: [{t, title}], sentences: [{text, start, end}], changes: [seconds the picture changes]}.
    Each part is empty when its file is gone (an archived video keeps its .final.json and transcript; the timeline needs the sections folder)."""
    wd = WORK / work
    out = {"dur": 0.0, "chapters": [], "sentences": [], "changes": []}
    finals = []
    for p in wd.glob("*.final.json"):
        try:
            j = json.loads(p.read_text(encoding="utf-8-sig"))
            finals.append((float(j.get("version") or 0), p, j))
        except (OSError, ValueError, TypeError):
            continue
    if finals:
        _, p, j = max(finals, key=lambda x: x[0])
        out["dur"] = float(j.get("dur") or 0)
        out["chapters"] = [{"t": float(c["t"]), "title": str(c.get("title", ""))} for c in j.get("chapters") or [] if isinstance(c, dict) and "t" in c]
        tp = p.with_name(p.name[:-len(".final.json")] + ".transcript.json")
        try:
            out["sentences"] = [{"text": s["text"], "start": float(s["start"]), "end": float(s["end"])} for s in json.loads(tp.read_text(encoding="utf-8-sig")).get("segments", [])]
        except (OSError, ValueError, KeyError, TypeError):
            pass
    try:
        import selfreview
        T = selfreview.timeline(work, name)
        out["dur"] = out["dur"] or float(T["stitch"].get("dur") or 0)
        ch, prev = set(), None
        for s in T["segments"]:
            look = (s.get("src"), s.get("zoom"))
            if prev is None or look != prev:                # another recording or another framing: the picture changes (a cut that only removes a silence does not)
                ch.add(round(float(s["start"]), 2))
            prev = look
        for b in T["broll"]:
            si = b.get("seg_info") or {}
            if si:
                a = float(si["start"]) + float(b.get("at") or 0)
                ch.update((round(a, 2), round(a + float(b.get("dur") or 0), 2)))
        for o in T["overlays"]:
            si = o.get("seg_info") or {}
            if si and o.get("at") is not None:
                ch.add(round(float(si["start"]) + float(o["at"]), 2))
        out["changes"] = sorted(ch)
    except Exception:                                       # noqa: BLE001 - no timeline (the sections were cleaned up): said and chapters still work
        pass
    return out


def what_at(facts: dict, t: float, t_end: float | None = None) -> dict:
    """What the final says and shows from t (to t_end): the sentences, the chapter, and how long the picture had gone unchanged when it started."""
    t_end = t if t_end is None else t_end
    said = " ".join(s["text"] for s in facts["sentences"] if s["end"] > t - 2 and s["start"] < t_end + 2)
    chapter = next((c["title"] for c in reversed(facts["chapters"]) if c["t"] <= t + 0.5), "")
    unchanged = None
    if facts["changes"]:
        before = [c for c in facts["changes"] if c <= t + 0.5]
        after = [c for c in facts["changes"] if c > t + 0.5]
        unchanged = round((after[0] if after else facts["dur"]) - (before[-1] if before else 0.0), 1)       # the length of the shot the moment falls in
    picture = "" if unchanged is None else (f"the same picture for {round(unchanged)} seconds" if unchanged >= LONG_SHOT_S else "the picture was changing")
    return {"said": said[:400], "chapter": chapter, "picture": picture, "shot_s": unchanged}


# ----------------------------------------------------------------------------- stored and shown
def load(work: str, name: str) -> dict | None:
    try:
        j = json.loads(path(work, name).read_text(encoding="utf-8-sig"))
        return j if isinstance(j, dict) and j.get("curve") else None
    except (OSError, ValueError):
        return None


def save(work: str, name: str, data, source: str = "") -> dict:
    """Read an export and keep it for this video. Raises ValueError (in plain words) when it cannot be used."""
    facts = final_facts(work, name)
    if facts["dur"] <= 0:
        raise ValueError("this video has no final yet, so the graph cannot be lined up with it: render the final first")
    curve = normalise(parse(data), facts["dur"])
    got = analyse(curve, facts["dur"])                      # raises when there are too few points
    j = {"imported": time.strftime("%Y-%m-%d"), "source": str(source)[:120], "dur": facts["dur"], "curve": curve,
         **{k: got[k] for k in ("hook", "hook_s", "average", "end")}}
    projectstore.write_json(path(work, name), j, why="retention imported")
    return j


def _mmss(t: float) -> str:
    return f"{int(t // 60)}:{int(t % 60):02d}"


def view(work: str, name: str) -> dict:
    """For the Final screen. `has` False: nothing imported yet."""
    j = load(work, name)
    if not j:
        return {"has": False, "can": final_facts(work, name)["dur"] > 0}
    facts = final_facts(work, name)
    total = float(j["dur"])
    curve = [(float(a), float(b)) for a, b in j["curve"]]
    got = analyse(curve, total)
    pct = lambda x: f"{round(100 * x)}%"                    # noqa: E731
    moments = []
    for d in got["drops"]:
        w = what_at(facts, d["t"], d["t_end"])
        moments.append({"kind": "drop", "t": d["t"], "when": f"{_mmss(d['t'])}–{_mmss(d['t_end'])}", "size": f"{100 * d['lost']:.1f} points of your viewers left here, beyond the usual", **w})
    for s in got["spikes"]:
        w = what_at(facts, s["t"], s["t_end"])
        moments.append({"kind": "spike", "t": s["t"], "when": f"{_mmss(s['t'])}–{_mmss(s['t_end'])}", "size": f"The graph rises {100 * s['gained']:.1f} points: viewers skipped back to this, or came straight to it", **w})
    others = [o for o in overview() if o["key"] != f"{work}~{name}"]
    return {"has": True, "can": True, "imported": j.get("imported"), "source": j.get("source", ""), "dur": total, "curve": curve,
            "hook": {"share": pct(got["hook"]), "at": f"{round(got['hook_s'])} seconds"}, "average": pct(got["average"]), "end": pct(got["end"]),
            "moments": sorted(moments, key=lambda m: m["t"]), "others": others,
            "note": ("One video shows where this video lost people, not what works in general: the topic and the title move these numbers more than the editing does. "
                     + (f"You have {len(others) + 1} videos imported to compare; " if others else "This is the only video imported so far; ") + "with five or more, patterns start to mean something.")}


def overview() -> list:
    """Every video with retention imported: [{key, title, hook, average, end, dur}], newest import first."""
    out = []
    for p in WORK.glob("*/*.retention.json"):
        work, name = p.parent.name, p.name[:-len(".retention.json")]
        j = load(work, name)
        if not j:
            continue
        title = name
        try:
            title = json.loads((p.parent / f"{name}.publish.json").read_text(encoding="utf-8-sig")).get("title") or name
        except (OSError, ValueError, AttributeError):
            pass
        out.append({"key": f"{work}~{name}", "title": title, "hook": f"{round(100 * j['hook'])}%", "average": f"{round(100 * j['average'])}%",
                    "end": f"{round(100 * j['end'])}%", "length": _mmss(float(j["dur"])), "imported": j.get("imported", "")})
    return sorted(out, key=lambda o: o["imported"], reverse=True)
