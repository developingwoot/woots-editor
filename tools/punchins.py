"""Plan speaker punch-ins: zoom onto whoever is talking to add a visual change.

Usage:
    python punchins.py <edit.json> <speakers.json> <shots.json> [--graphics graphics.json]
                       [--pacing preview.pacing.json] [--target 15] [--max-zoom 25]

Guideline from the user: a visual change roughly every 15-30 s, motivated by the content,
never forced. Rules:
  * only punch in on someone who keeps talking for a while (turn >= --min-turn seconds);
  * follow the speaker: while close on one person, if the other says a real line, show them
    (close-up if >= 3 s, otherwise the wide shot), then cut back when the first person resumes;
  * backchannels ("Yeah.", "Okay.", <= 1.5 s or <= 3 words) don't move the camera;
  * never cut again within --min-shot seconds (no ping-pong);
  * after --max-zoom seconds on one person, return to the wide shot at a sentence start;
  * never zoom during a graphic or across a camera-angle change.
Writes <name>.zooms.json (source time) with a reason for every zoom.
"""
import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import channel  # noqa: E402


def to_output(src_t, keeps):
    elapsed = 0.0
    for s, e in keeps:
        if s <= src_t <= e:
            return elapsed + src_t - s
        elapsed += e - s
    return None


def crop_box(face, zoom):
    """Frame-relative crop (x, y, w, h) that keeps the face in the upper third of the crop."""
    w = h = 1 / zoom
    x = min(max(face[0] - w / 2, 0), 1 - w)
    y = min(max(face[1] - h * 0.32, 0), 1 - h)
    return [round(x, 4), round(y, 4), round(w, 4), round(h, 4)]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("plan", type=Path)
    ap.add_argument("speakers", type=Path)
    ap.add_argument("shots", type=Path)
    ap.add_argument("--graphics", type=Path)
    ap.add_argument("--broll", type=Path, help="B-roll plan; inserts count as visual changes, no zooms under them")
    ap.add_argument("--target", type=float, default=15.0, help="look for a change after this long (s)")
    ap.add_argument("--max-zoom", type=float, default=25.0, help="return to wide after this long (s)")
    ap.add_argument("--min-turn", type=float, default=8.0, help="only zoom on turns at least this long (s)")
    ap.add_argument("--min-shot", type=float, default=2.0, help="never cut again sooner than this (s)")
    args = ap.parse_args()

    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    keeps = plan["keeps"]
    sections = plan.get("sections") or [{"id": "all", "src": [0, 1e9]}]

    def sec_of(t):
        return next((i for i, x in enumerate(sections) if x["src"][0] <= t < x["src"][1]), -1)

    # Work in OUTPUT order (the edit may be re-ordered into question blocks).
    segs = [s for s in json.loads(args.speakers.read_text(encoding="utf-8"))
            if to_output(s["start"], keeps) is not None]
    segs.sort(key=lambda s: to_output(s["start"], keeps))
    shots_cfg = json.loads(args.shots.read_text(encoding="utf-8"))
    shots = shots_cfg["shots"]

    # Graphic windows in source time (no zooms there; they count as visual changes).
    gfx = []
    if args.graphics:
        from subprocess import run
        for g in json.loads(args.graphics.read_text(encoding="utf-8")):
            dur = float(run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of",
                             "default=nw=1:nk=1", g["file"]], capture_output=True, text=True).stdout)
            for a, b in g.get("show") or [[0, dur]]:
                gfx.append((g["src_start"] + a, g["src_start"] + b))
    for b in (json.loads(args.broll.read_text(encoding="utf-8")) if args.broll else []):
        gfx.append((b["src_start"], b["src_start"] + b["dur"]))   # B-roll covers the speakers too
    gfx.sort()

    # Speaker turns: merge consecutive segments by the same person. Backchannels ("Yeah.",
    # "Okay.") from the other person don't start a turn, but any real line does: being off
    # screen while you talk feels like being ignored (user feedback).
    # A short reply to a direct question is NOT a backchannel: when the creator asks "how many times did
    # we have something misconfigured?" and the co-host says "A few times.", show the co-host (user feedback).
    def backchannel(i):
        s = segs[i]
        short = s["end"] - s["start"] <= 1.5 or len(s["text"].split()) <= 3
        answers_question = i > 0 and segs[i - 1]["speaker"] != s["speaker"] \
            and segs[i - 1]["text"].rstrip().endswith("?")
        return short and not answers_question

    turns = []
    for i, s in enumerate(segs):
        same_block = turns and sec_of(turns[-1]["start"]) == sec_of(s["start"])
        if same_block and (s["speaker"] == turns[-1]["speaker"] or backchannel(i)):
            turns[-1]["end"] = max(turns[-1]["end"], s["end"])
            turns[-1]["starts"].append(s["start"])
        else:
            turns.append({"speaker": s["speaker"], "start": s["start"], "end": s["end"], "starts": [s["start"]]})

    def shot_at(t):
        return max((i for i, sh in enumerate(shots) if sh["start"] <= t), default=0)

    def in_gfx(t):
        return any(a - 0.5 <= t <= b + 0.5 for a, b in gfx)

    zooms, cur = [], None          # cur = open close-up (None = wide shot)
    last_cut = 0.0                 # output time of the last visual change
    left_closeup = None            # (who, output time) of the last close-up we left for someone else
    last_shot = 0
    last_sec = None

    def close(at_src, why):
        nonlocal cur, last_cut
        if cur:
            cur["src_end"] = at_src
            cur["end_reason"] = why
            zooms.append(cur)
            cur = None
            last_cut = to_output(at_src, keeps)

    def open_(at_src, who, sh, why):
        nonlocal cur, last_cut
        cur = {"src_start": at_src, "who": who, "shot": sh,
               "crop": crop_box(shots[sh]["faces"][who], shots[sh]["zoom"]), "reason": why}
        last_cut = to_output(at_src, keeps)

    for turn in turns:
        who, tlen = turn["speaker"], turn["end"] - turn["start"]
        for st in turn["starts"]:
            o = to_output(st, keeps)
            sh = shot_at(st)
            sec = sec_of(st)
            contiguous = last_sec is not None and sec != last_sec and                 abs(sections[sec]["src"][0] - sections[last_sec]["src"][1]) < 0.05
            if last_sec is not None and sec != last_sec and not contiguous:
                # Joining two question blocks. Make the join a visible framing change so two blocks
                # from the same camera angle don't meet as a jump cut: close-up -> wide, or
                # wide -> close-up on whoever opens the new block.
                was_close = cur is not None
                close(sections[last_sec]["src"][1], "end of question block")
                last_cut, left_closeup = o, None
                if not was_close and sh == last_shot and not in_gfx(st) and turn["end"] - st >= 3.0:
                    open_(sections[sec]["src"][0], who, sh,
                          "new question block on the same camera angle: punch in to avoid a jump cut")
                last_shot, last_sec = sh, sec
                continue
            last_sec = sec
            if contiguous:
                pass                                  # same source flow: nothing visible happens here
            if sh != last_shot:                       # camera-angle change is itself a visual change
                close(st, "camera angle changes")
                last_shot, last_cut, left_closeup = sh, o, None
            if in_gfx(st):
                close(st, "graphic on screen")
                last_cut, left_closeup = o, None
                continue
            for a, b in gfx:                          # leaving a graphic counts as a change
                bo = to_output(b, keeps)
                if bo and last_cut < bo <= o:
                    last_cut = bo
            since = o - last_cut
            first = st == turn["start"]
            remaining = turn["end"] - st

            if first and cur and cur["who"] != who:
                # Someone else starts a real line while we're close on the other person.
                if since < args.min_shot:
                    continue                          # too soon after the last cut: no ping-pong
                prev = cur["who"]
                if tlen >= 3.0:
                    close(st, f"follow the speaker: {who} talks")
                    open_(st, who, sh, f"follow the speaker: {who} says {tlen:.0f}s")
                else:
                    close(st, f"{who} says a short line: wide to show both")
                left_closeup = (prev, o)
            elif first and cur is None and left_closeup and left_closeup[0] == who \
                    and o - left_closeup[1] < 12 and since >= args.min_shot and tlen >= 3.0:
                open_(st, who, sh, f"back to {who} after the other person's line")
                left_closeup = None
            elif cur is None:
                if since >= args.target and remaining >= args.min_turn:
                    open_(st, who, sh, f"{who} talking for {remaining:.0f}s; {since:.0f}s since last visual change")
            elif cur["who"] == who and o - to_output(cur["src_start"], keeps) >= args.max_zoom:
                close(st, f"{args.max_zoom:.0f}s+ on {who}: back to wide")
                left_closeup = None
    if cur:
        close(segs[-1]["end"], "end of video")

    # Snap: a punch-in ending < 1.5 s before a full-frame overlay starts runs on until the overlay
    # (its end cut is then hidden); one starting < 1.5 s after an overlay ends starts with it.
    ov = [(to_output(a, keeps), to_output(b, keeps), a, b) for a, b in gfx]
    for z in zooms:
        zo_s, zo_e = to_output(z["src_start"], keeps), to_output(z["src_end"], keeps)
        for oa, ob, sa, sb in ov:
            if oa is not None and zo_e is not None and 0 < oa - zo_e < 1.5 and sec_of(sa) == sec_of(z["src_end"]):
                z["src_end"], z["end_reason"] = sa, z["end_reason"] + " (snapped to overlay start)"
            if ob is not None and zo_s is not None and 0 < zo_s - ob < 1.5 and sec_of(sb) == sec_of(z["src_start"]):
                z["src_start"], z["reason"] = sb, z["reason"] + " (snapped to overlay end)"
    zooms = [z for z in zooms if z["src_end"] - z["src_start"] >= args.min_shot]
    out = args.plan.with_name(args.plan.name.replace(".edit.json", ".zooms.json"))
    out.write_text(json.dumps({"zooms": zooms}, indent=2), encoding="utf-8")
    on = sum(z["src_end"] - z["src_start"] for z in zooms)
    print(f"{len(zooms)} punch-ins, {on/60:.1f} min zoomed "
          f"({', '.join(w + ' ' + str(sum(z['who'] == w for z in zooms)) for w in channel.people())})")
    for z in zooms[:12]:
        print(f"  {z['src_start']:7.1f}-{z['src_end']:7.1f} {z['who']:5} {z['reason']}  | ends: {z['end_reason']}")
    print(f"-> {out}")


if __name__ == "__main__":
    sys.exit(main())
