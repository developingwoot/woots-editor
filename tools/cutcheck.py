"""Check a rough cut against the numbers of the youtube-edit skill (rough-cut.json), the same way for any video.

`check(data)` reads a beat map and says, rule by rule, whether the cut keeps it and where it does not (timestamps as m:ss in the cut). `measure_video(path)`
adds what only the picture and sound can say (the longest silence, the loudness). It judges nothing by feel: every limit is a number in the skill, so a rule
changed there changes what is checked. Run it on any cut: `python tools/cutcheck.py <work> <name> [video.mp4]`.
"""
import json
import re
import subprocess
import sys
from pathlib import Path

import beatmap
import clipmap
import config
import footage_cfg
import skillrules

WORK = config.WORK


def stamp(t: float) -> str:
    return f"{int(t // 60)}:{int(t % 60):02d}"


def timeline(data: dict) -> dict:
    """{events: [(time, what)], flat: [(start, end)], pieces: [...], cold_open_s, content_at, cutaway_s, total_s}: the visible changes of the cut in order.
    A change is a cut to or from a cutaway, a change of framing that is not hidden under a cutaway, or a new recording."""
    events, pieces, cold, content_at, cut_s = [], [], 0.0, None, 0.0
    last_state, last_rel = 1.0, None
    total = 0.0
    for b in data["beats"]:
        if b.get("skip"):
            continue
        ar = b.get("aroll")
        t0 = float(b.get("start", total))
        total = max(total, t0 + float(b.get("dur", 0)))
        if str(b.get("id", "")).startswith("H"):
            cold += float(b["dur"])
            continue
        if not ar:
            continue
        if content_at is None and footage_cfg.auto_role(ar["rel"]) not in ("intro", "outro"):
            content_at = t0
        brolls = [(t0 + float(x.get("at", 0)), t0 + float(x.get("at", 0)) + float(x["dur"])) for x in (b.get("on_screen") or {}).get("broll", []) if x.get("file")]
        cut_s += sum(min(z, t0 + b["dur"]) - a for a, z in brolls)
        if ar["rel"] != last_rel and last_rel is not None:
            events.append((t0, "new recording"))
        last_rel = ar["rel"]
        zooms = ((b.get("on_screen") or {}).get("punch") or {}).get("zooms") or []
        t = t0
        for k, (a, z) in enumerate(ar.get("keep") or [[ar["in"], ar["out"]]]):
            zoom = float(zooms[k]) if k < len(zooms) else 1.0
            hidden = any(s <= t < e for s, e in brolls)
            if zoom != last_state and not hidden:
                events.append((t, "framing"))
            if zoom != last_state:
                last_state = zoom
            t += z - a
        for s, e in brolls:
            events.append((s, "cutaway in"))
            events.append((min(e, t0 + float(b["dur"])), "cutaway out"))
        pieces.append((t0, t0 + float(b["dur"])))
    events.sort()
    merged = []
    for e in events:                                                       # a framing change, a new recording and a cutaway at the same moment are one change
        if not merged or e[0] - merged[-1][0] > 0.3:
            merged.append(e)
    events = merged
    return {"events": events, "cold_open_s": cold, "content_at": content_at, "cutaway_s": cut_s, "total_s": total}


def check(data: dict, rules: dict | None = None, known_programs: set | None = None, video: dict | None = None, silences: list | None = None, tag_list: list | None = None) -> list:
    """[{rule, ok, value, limit, where}] for every rule the cut data can show. `video` = measure_video() when the cut was rendered."""
    r = rules or skillrules.rules()
    tl = timeline(data)
    out = []

    def add(rule, ok, value, limit, where=None):
        out.append({"rule": rule, "ok": bool(ok), "value": value, "limit": limit, "where": where or []})

    ev = tl["events"]
    short = [stamp(a) for (a, _), (b, _) in zip(ev, ev[1:]) if b - a < r["min_piece_s"] - 0.05]
    add("no shot under min_piece_s", not short, len(short), f">= {r['min_piece_s']} s", short[:12])
    gaps = [(stamp(a), round(b - a)) for (a, _), (b, _) in zip(ev, ev[1:]) if b - a > r["beat_max_s"] + 5]
    add("a visible change at least every beat_max_s", not gaps, len(gaps), f"<= {r['beat_max_s'] + 5:.0f} s", [f"{s} ({d} s)" for s, d in gaps[:12]])
    fr = [t for t, w in ev if w == "framing"]
    close = [stamp(b) for a, b in zip(fr, fr[1:]) if b - a < r["punch_hold_s"] - 0.05]
    add("framing changes at least punch_hold_s apart", not close, len(close), f">= {r['punch_hold_s']} s", close[:12])
    add("cold open at most cold_open_max_s", tl["cold_open_s"] <= r["cold_open_max_s"] + 0.5, round(tl["cold_open_s"], 1), f"<= {r['cold_open_max_s']} s")
    if tl["content_at"] is not None:
        add("content starts by hook_total_s", tl["content_at"] <= r["hook_total_s"] + 1.0, round(tl["content_at"], 1), f"<= {r['hook_total_s']} s")
    flat = tl["total_s"] - tl["cutaway_s"]
    add("cutaways cover part of the video", tl["cutaway_s"] >= 0.15 * tl["total_s"], f"{100 * tl['cutaway_s'] / max(1.0, tl['total_s']):.0f}%", ">= 15%")
    # words: repeats and cut-off thoughts in what the cut says
    import cutreview
    import recut
    words = []
    for b in data["beats"]:
        if b.get("aroll") and not b.get("skip"):
            words += [[w[0], w[1], w[2]] for w in b["aroll"].get("words", []) if any(a - 0.001 <= (w[1] + w[2]) / 2 <= z + 0.001 for a, z in b["aroll"]["keep"])]
    toks = [re.sub(r"[^a-z0-9']", "", w[0].lower()) for w in words]
    seen, rep = {}, []
    for i in range(len(toks) - r["repeat_phrase_words"] + 1):
        g = tuple(toks[i:i + r["repeat_phrase_words"]])
        if all(g) and sum(1 for x in g if x not in clipmap.STOP) >= 2 and g in seen and i - seen[g] <= r["repeat_phrase_within_words"] and words[i][1] - words[seen[g]][1] <= r["repeat_phrase_within_s"] + 5:
            rep.append(" ".join(g))
        seen[g] = i
    add("no phrase said twice in a row", not rep, len(rep), "0", rep[:8])
    twice = [toks[i] for i in range(1, len(toks)) if toks[i] and toks[i] == toks[i - 1] and toks[i] not in recut.STAMMER_OK and words[i][1] - words[i - 1][2] < 0.6]
    add("no word said twice in a row", not twice, len(twice), "0", twice[:8])
    cut = [d["text"][:50] for d in cutreview.dangling(data)]
    add("no sentence stops mid-thought", not cut, len(cut), "0", cut[:8])
    if known_programs:
        beats = [b for b in data["beats"] if b.get("aroll") and not b.get("skip") and not b.get("vo") and not str(b.get("id", "")).startswith("H")]
        prog = recut.beat_programs(beats, known_programs)
        import shotmatch
        bad = [f"{stamp(b['start'])} {x['file'].split('/')[0]} over {prog[b['id']]}" for b in beats for x in (b.get("on_screen") or {}).get("broll", [])
               if prog.get(b["id"]) and shotmatch.programs([x["file"]]) and not shotmatch.of_program(x["file"], {prog[b["id"]]}, shotmatch.label_at(tag_list, x["file"], x.get("in", 0))) and "tierlist" not in shotmatch._norm(x["file"])]
        add("cutaways show the program being discussed", not bad, len(bad), "0", bad[:8])
    if silences is not None:
        left = sorted([(t, d) for t, d in silences if d > r["max_pause_s"] + 0.2], key=lambda x: -x[1])
        add("no silence over max_pause_s", not left, left[0][1] if left else 0.0, f"<= {r['max_pause_s'] + 0.2:.1f} s", [f"{stamp(t)} ({d} s)" for t, d in left[:8]])
    if video:
        if video.get("lufs") is not None:
            add("loudness near the target", abs(video["lufs"] - skillrules_target()) <= 1.5, video["lufs"], f"{skillrules_target()} +-1.5 LUFS")
        if video.get("lra") is not None:
            add("loudness steady (LRA)", video["lra"] <= 9.0, video["lra"], "<= 9 LU")
    return out


def silences_in_cut(data: dict, cache: dict) -> list:
    """[(time in the cut, seconds)] of the silences that are left in the cut, from the sound of each source recording (the silence cache): inside a piece, and at a join
    (the quiet at the end of one piece plus the quiet at the start of the next). A level measured over the whole finished cut cannot say this, because every recording has its own."""
    out, t, prev_tail = [], 0.0, 0.0
    for b in data["beats"]:
        ar = b.get("aroll")
        if b.get("skip") or not ar:
            continue
        t = float(b.get("start", t))
        sil = [(s, e) for s, e in (cache.get(ar["rel"]) or {}).get("silences", [])]
        for a, z in ar.get("keep") or [[ar["in"], ar["out"]]]:
            lead = trail = 0.0
            for s, e in sil:
                lo, hi = max(s, a), min(e, z)
                if hi <= lo:
                    continue
                if lo <= a + 0.001:
                    lead = hi - lo
                elif hi >= z - 0.001:
                    trail = hi - lo
                else:
                    out.append((t + lo - a, round(hi - lo, 2)))
            if prev_tail + lead > 0:
                out.append((t, round(prev_tail + lead, 2)))
            prev_tail = trail
            t += z - a
    return out


def skillrules_target() -> float:
    import sectionrender
    return sectionrender.LEVEL_TARGET


def measure_video(path: str, max_pause: float = 0.5) -> dict:
    """What the finished picture and sound say: the silences of max_pause + 0.2 s or more (read against the file's own floor), the integrated loudness and its range."""
    import silence
    import sectionrender
    floor = silence.floor_db(path)
    a = subprocess.run([sectionrender.FFMPEG, "-nostdin", "-hide_banner", "-i", str(path), "-vn", "-af", f"silencedetect=noise={floor:.1f}dB:d={max_pause + 0.2}", "-f", "null", "-"],
                       capture_output=True, text=True).stderr
    starts = [float(x) for x in re.findall(r"silence_start: (-?[\d.]+)", a)]
    durs = [float(x) for x in re.findall(r"silence_duration: ([\d.]+)", a)]
    sil = [(s, round(d, 1)) for s, d in zip(starts, durs)]
    e = subprocess.run([sectionrender.FFMPEG, "-nostdin", "-hide_banner", "-i", str(path), "-vn", "-af", "ebur128=peak=true", "-f", "null", "-"], capture_output=True, text=True).stderr
    i = re.findall(r"I:\s+(-?[\d.]+) LUFS", e)
    lra = re.findall(r"LRA:\s+([\d.]+) LU", e)
    return {"longest_silence_s": max([d for _, d in sil], default=0.0), "silences": sorted(sil, key=lambda x: -x[1]), "lufs": float(i[-1]) if i else None, "lra": float(lra[-1]) if lra else None}


def report(rows: list) -> str:
    lines = [f"{'ok  ' if r['ok'] else 'FAIL'} {r['rule']}: {r['value']} (limit {r['limit']})" + (f" at {', '.join(map(str, r['where']))}" if r['where'] and not r['ok'] else "") for r in rows]
    bad = sum(1 for r in rows if not r["ok"])
    return f"{len(rows) - bad} of {len(rows)} rules kept\n" + "\n".join(lines)


def run(work: str, name: str, video: str | None = None) -> list:
    data = clipmap.read_json(beatmap.path_of(work, name), None)
    if not data:
        raise ValueError("there is no cut to check")
    import brolllib
    import shotmatch
    jp = brolllib.paths(work, name)[1]
    known = shotmatch.programs(json.loads(jp.read_text(encoding="utf-8")).get("clips", {})) if jp.exists() else set()
    import silence
    import tags
    cache = clipmap.read_json(silence.path(work, name), None) or {}
    rows = check(data, known_programs=known, video=measure_video(video, skillrules.rules()["max_pause_s"]) if video else None,
                 silences=silences_in_cut(data, cache) if cache else None, tag_list=tags.load(work, name))
    clipmap.write_json(WORK / work / f"{name}.cutcheck.json", {"rows": rows})
    return rows


if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit("usage: cutcheck.py <work> <name> [video.mp4]")
    print(report(run(sys.argv[1], sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None)))
