"""Build plan: split the beat map into sections and write each section's baseline cut list (stage 5).

Usage:
    python sections.py plan <work> <name>        # writes <name>.buildplan.json (NOT <name>.sections.json: the old pipeline owns that name)

A section = consecutive beats that share a topic (the beat map's `section` heading), about 45-120 s, so one
background run (or one local render) can build it on its own. Per section the plan says whether Claude is needed:

    needs_agent = the section has a live graphic that is not built yet (a graphic is DESIGN work: HTML, timing, snapshots)

Everything else (cutting the takes together, punch-ins, B-roll cutaways, finished graphics) is mechanical:
`baseline_edit()` turns the beat rows into a section.edit.json that tools\\sectionrender.py renders at half size
with no tokens spent.

<name>.buildplan.json:
  {"generated", "beatmap_version", "beatmap_sha", "sections": [{"id": "S01", "title", "beats": ["B01", ...],
    "dur": seconds, "graphics": n, "unbuilt_graphics": n, "needs_agent": bool, "why": "...", "sig": "..."}]}
`sig` changes when a beat in the section changes: the Build board then shows the section as outdated.
Python stdlib only.
"""
import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path

HERE = Path(os.path.abspath(__file__)).parent
import config
WORK = config.WORK
sys.path.insert(0, str(HERE))

MIN_SEC, MAX_SEC, TARGET = 45.0, 120.0, 90.0
if os.environ.get("WOOT_PLAN_SMALL"):            # tests only: tiny clips, so let every heading be its own section
    MIN_SEC, MAX_SEC, TARGET = 1.0, 60.0, 30.0


def _replace(tmp, p):
    """os.replace that survives a reader holding the destination open (Windows: 'Access is denied' while the board polls)."""
    for i in range(8):
        try:
            os.replace(tmp, p)
            return
        except PermissionError:
            if i == 7:
                raise
            time.sleep(0.05 * (i + 1))


def read_json(p: Path, default=None):
    if not p.exists():
        return default
    return json.loads(p.read_text(encoding="utf-8-sig"))


import projectstore  # noqa: E402  (plan-file writes are recorded: ADR 0005)


def write_json(p: Path, data):
    projectstore.write_json(p, data)


def plan_path(work: str, name: str) -> Path:
    return WORK / work / f"{name}.buildplan.json"


def live_graphic(b: dict):
    g = b.get("graphic")
    return g if g and not g.get("struck") and not b.get("skip") else None


def built_path(work: str, name: str) -> Path:
    """<name>.graphics.built.json: {beat id: {"file": rendered .mov, "sig": design signature, "built": time}}.
    Kept OUT of the beat map so building a graphic never touches the plan."""
    return WORK / work / f"{name}.graphics.built.json"


def load_built(work: str, name: str) -> dict:
    return read_json(built_path(work, name), {}) or {}


def gsig(g: dict) -> str:
    """The design of a graphic: change any of this and an already-built graphic is out of date."""
    key = {k: g.get(k) for k in ("kind", "style", "idea", "words", "text", "dur", "draft", "plan_note", "review_note")}
    return hashlib.sha1(json.dumps(key, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:12]


def graphic_built(g: dict, bid: str, built: dict) -> bool:
    """Built = a rendered file exists for this beat AND it was made from the graphic's current design."""
    e = built.get(bid)
    return bool(e) and Path(e["file"]).exists() and e.get("sig") == gsig(g)


def beat_sig(b: dict) -> str:
    key = {k: b.get(k) for k in ("aroll", "on_screen", "graphic", "audio", "skip", "missing", "said")}
    if key["aroll"]:
        key["aroll"] = {k: v for k, v in key["aroll"].items() if k != "words"}                 # the shown words are a view of the take, not a decision
    return hashlib.sha1(json.dumps(key, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:12]


def group(beats: list[dict]) -> list[list[dict]]:
    """Consecutive beats with the same `section` heading; long groups are cut at beat boundaries (about TARGET s),
    short ones are merged into a neighbour until they reach MIN_SEC."""
    groups, cur, head = [], [], object()
    for b in beats:
        if b.get("skip"):
            continue
        if b.get("section") != head and cur:
            groups.append(cur)
            cur = []
        head = b.get("section")
        cur.append(b)
    if cur:
        groups.append(cur)
    out = []
    for g in groups:                                   # split long groups
        if sum(b["dur"] for b in g) <= MAX_SEC:
            out.append(g)
            continue
        part, t = [], 0.0
        for b in g:
            if part and t + b["dur"] > TARGET:
                out.append(part)
                part, t = [], 0.0
            part.append(b)
            t += b["dur"]
        if part:
            out.append(part)
    merged = []                                        # merge short ones forward, then the last backward
    for g in out:
        if merged and sum(b["dur"] for b in merged[-1]) < MIN_SEC and sum(b["dur"] for b in merged[-1] + g) <= MAX_SEC:
            merged[-1] = merged[-1] + g
        else:
            merged.append(g)
    if len(merged) > 1 and sum(b["dur"] for b in merged[-1]) < MIN_SEC and sum(b["dur"] for b in merged[-2] + merged[-1]) <= MAX_SEC:
        last = merged.pop()                            # (not `merged[-2] = merged[-2] + merged.pop()`: the index is resolved after the pop and overwrote the wrong section)
        merged[-1] = merged[-1] + last
    return merged


def notes_path(work: str, name: str) -> Path:
    return WORK / work / f"{name}.sectionnotes.json"


def read_notes(work: str, name: str) -> list[dict]:
    """The host's change requests on built sections (Build & review tab): {id, sid, kind: graphic|plan, text, t, beat, status: open|applied|done, created}."""
    return [n for n in (read_json(notes_path(work, name), None) or {}).get("notes", [])]


def _cutaways(b: dict) -> list:
    """The B-roll inserts that lie over the beat's picture (a voice-over beat's first one IS its picture)."""
    xs = [x for x in (b.get("on_screen") or {}).get("broll") or [] if x.get("file")]
    return [] if b.get("skip") else xs[1:] if b.get("vo") else xs


def plan(work: str, name: str, write: bool = True) -> dict:
    """The build plan. write=False computes it without touching the file (used by runs that only need the numbers)."""
    bmp = WORK / work / f"{name}.beatmap.json"
    bm = read_json(bmp)
    if not bm:
        raise ValueError("no beat map yet")
    import gfxplan
    gfxplan.apply(work, name, bm)                     # The creator's look, notes and cuts from the Graphics tab, laid on the beat map in memory only
    secs = []
    built = load_built(work, name)
    notes = [n for n in read_notes(work, name) if n.get("kind") == "graphic"]
    import transitions
    lib, dflt = transitions.library(), transitions.defaults()

    def tsig(beats) -> str:                           # the transitions the section's cutaways get: changing one in the library or in Settings makes the section out of date
        got = [transitions.pick(x, lib, dflt) for b in beats for x in _cutaways(b)]
        return json.dumps(got, sort_keys=True) if any(p["kind"] != "cut" for p in got) else ""
    for i, g in enumerate(group(bm["beats"]), 1):
        gfx = [live_graphic(b) for b in g if live_graphic(b)]
        unbuilt = [b for b in g if live_graphic(b) and not graphic_built(live_graphic(b), b["id"], built)]
        titles = [b.get("section") for b in g if b.get("section")]
        mine = [n for n in notes if n["sid"] == f"S{i:02d}"]
        asked = [n for n in mine if n.get("status") == "open"]
        why = (f"{len(asked)} change request{'s' if len(asked) != 1 else ''} from you: Claude redesigns the graphics" if asked else
               f"{len(unbuilt)} graphic{'s' if len(unbuilt) != 1 else ''} to design and render" if unbuilt
               else "only takes, punch-ins and B-roll: built locally, no Claude needed")
        secs.append({"id": f"S{i:02d}", "title": titles[0] if titles else f"Part {i}", "beats": [b["id"] for b in g],
                     "dur": round(sum(b["dur"] for b in g), 1), "graphics": len(gfx), "unbuilt_graphics": len(unbuilt),
                     "needs_agent": bool(unbuilt) or bool(asked), "why": why, "asked": [{"beat": n.get("beat"), "t": n.get("t"), "text": n["text"]} for n in asked],
                     "sig": hashlib.sha1(("".join(beat_sig(b) for b in g) + "".join(f"{n['id']}:{n['text']}" for n in mine)
                                          + tsig(g)).encode()).hexdigest()[:12]})
    data = {"generated": time.strftime("%Y-%m-%dT%H:%M:%S"), "beatmap_version": bm.get("version", 1),
            "beatmap_sha": hashlib.sha256(bmp.read_bytes()).hexdigest()[:16], "sections": secs}
    if write:
        write_json(plan_path(work, name), data)
    return data


# ----------------------------------------------------------------------------- baseline cut list
def _sfx_for(b: dict, g, built: dict, notes: list) -> list:
    """The beat's sound effects as cues inside its segment: 'name @ 1.2' = 1.2 s in, 'name @graphic' = when its graphic starts, 'name' = the start."""
    out = []
    for line in (b.get("audio") or {}).get("sfx") or []:
        nm, _, at = line.partition("@")
        nm, at = nm.strip(), at.strip()
        if not nm:
            continue
        if at.lower() == "end":                                      # the effect ENDS where the beat ends (a riser into the next line): it goes on the beat's last piece
            import finalrender
            import sectionrender
            f, why = finalrender.resolve_sfx(nm)
            if not f:
                notes.append(f"{b['id']}: sound effect '{nm}' not found ({why})")
                continue
            keep = (b.get("aroll") or {}).get("keep") or []
            last = (keep[-1][1] - keep[-1][0]) if keep else b["dur"]
            out.append({"seg": b["id"] if len(keep) <= 1 else f"{b['id']}.{len(keep)}", "file": str(f), "at": max(0.0, last - sectionrender.probe_duration(f))})
            continue
        if at.lower().startswith("graphic"):
            off = float(built[b["id"]].get("at", 0.0)) if g and graphic_built(g, b["id"], built) else float((g or {}).get("at", 0.0))
            import re
            m = re.match(r"graphic\s*\+\s*([\d.]+)", at.lower())                  # "@graphic+4.0": 4 s after the graphic starts (the moment a number lands)
            off += float(m.group(1)) if m else 0.0
        else:
            try:
                off = float(at) if at else 0.0
            except ValueError:
                off = 0.0
        import finalrender
        f, why = finalrender.resolve_sfx(nm)
        if f:
            seg_id, local = _piece_at(b, off)                     # a sound that falls after a cut goes on the piece it falls in
            out.append({"seg": seg_id, "file": str(f), "at": local})
        else:
            notes.append(f"{b['id']}: sound effect '{nm}' not found ({why})")
    return out


def _pieces(b: dict) -> list:
    """[(segment id, start in the beat's own time, length)] of a trimmed beat: its kept runs of words are separate segments (B07, B07.2, ...), laid end to end."""
    a = b.get("aroll") or {}
    keep = a.get("keep") or []
    if len(keep) < 2:
        return []
    out, t = [], 0.0
    for k, (k0, k1) in enumerate(keep):
        out.append((b["id"] if k == 0 else f"{b['id']}.{k + 1}", t, k1 - k0))
        t += k1 - k0
    return out


def _piece_at(b: dict, t: float) -> tuple:
    """(segment id, time inside that segment) for a moment t of the beat: a sound effect or a graphic that starts after a cut belongs to the piece it falls in."""
    ps = _pieces(b)
    for sid, s0, ln in ps:
        if t < s0 + ln - 0.05 or (sid, s0, ln) == ps[-1]:
            return sid, max(0.0, t - s0)
    return b["id"], t


def _spread_overlay(b: dict, file: str, at: float, dur: float) -> list:
    """The overlay entries for a graphic: one on a single-piece beat; on a trimmed beat one per piece it overlaps, each carrying on where the last stopped."""
    ps = _pieces(b)
    if not ps:
        return [{"seg": b["id"], "file": file, "at": at, "dur": dur}]
    out = []
    for sid, s0, ln in ps:
        a0, a1 = max(at, s0), min(at + dur, s0 + ln)
        if a1 - a0 > 0.05:
            out.append({"seg": sid, "file": file, "at": round(a0 - s0, 3), "in": round(max(0.0, s0 - at), 3), "dur": round(a1 - a0, 3)})
    return out or [{"seg": b["id"], "file": file, "at": at, "dur": dur}]


def _text_overlays(b: dict, notes: list) -> list:
    """The beat's on-screen text (on_screen.text, textcards.py) as still overlays that fade in on their first piece and out on their last."""
    rows = (b.get("on_screen") or {}).get("text") or []
    if not rows:
        return []
    import skillrules
    import textcards
    dflt, out = skillrules.rules()["text_card_s"], []
    for x in rows:
        e = textcards.entry(x, float(b.get("dur") or 0), dflt) if isinstance(x, dict) else None
        if not e:
            continue
        try:
            f = str(textcards.card(e["text"], e["kind"]))
        except Exception as ex:                                        # noqa: BLE001  (a card that cannot be drawn is left out and reported)
            notes.append(f"{b['id']}: the on-screen text '{e['text'][:30]}' could not be drawn ({ex})")
            continue
        parts = [{**p, "still": True, "card": True} for p in _spread_overlay(b, f, e["at"], e["dur"])]
        parts[0]["fade_in"], parts[-1]["fade_out"] = True, True
        out += parts
    return out


def _punch(beat: dict, k: int) -> tuple:
    """(zoom, eye line) of piece k of a beat: the alternating punch-in of framing.py, whose zoom keeps the eyes on one line of the screen."""
    p = (beat.get("on_screen") or {}).get("punch") or {}
    z = p.get("zooms") or []
    return (float(z[k]) if k < len(z) else 1.0, float(p.get("cy", 0.4)))


def _broll_pieces(beat_id: str, keep: list, at: float, dur: float, src_in: float, speed: float = 1.0) -> list:
    """A cutaway runs on over the jump cuts inside a beat (the pieces of its kept stretches play one after the other): [(piece id, at in the piece,
    seconds in the piece, source second to start at)]. The picture of the cutaway carries on from piece to piece, so a cut that takes out a silence is covered."""
    out, t0 = [], 0.0
    for k, (k_in, k_out) in enumerate(keep):
        t1 = t0 + (k_out - k_in)
        a, z = max(at, t0), min(at + dur, t1)
        if z - a > 0.05:
            out.append((beat_id if k == 0 else f"{beat_id}.{k + 1}", round(a - t0, 3), round(z - a, 3), round(src_in + (a - at) * speed, 3)))
        t0 = t1
    return out or [(beat_id, at, dur, src_in)]


class _Transitions:
    """Puts each cutaway's transition (transitions.py) on its pieces and its sound into the edit's sound effects. The library, the defaults and the
    sound kit are read once per edit; sounds of a role take turns."""

    def __init__(self, sfx: list):
        import transitions
        self.t, self.sfx, self.lib, self.dflt, self.kit, self.n = transitions, sfx, transitions.library(), transitions.defaults(), None, {}

    def add(self, pieces: list, insert: dict) -> list:
        self.t.stamp(pieces, self.t.pick(insert, self.lib, self.dflt))
        for pc in pieces:
            for at, role in self.t.sound_times(pc):
                if self.kit is None:
                    import sfxkit
                    self.kit = sfxkit.kit()
                f = self.t.sound_file(role, self.n.get(role, 0), self.kit)
                if f:
                    self.n[role] = self.n.get(role, 0) + 1
                    self.sfx.append({"seg": pc["seg"], "file": f, "at": at, "transition": True})
        return pieces


def baseline_edit(beats: list[dict], folder: str, built: dict | None = None, size=(960, 540), fps=30) -> dict:
    """The mechanical section.edit.json for these beats (see sectionrender.py for the format). Graphics that are
    built (see built_path) become overlays; the rest are listed in `notes` for the agent."""
    import blur
    built = built or {}
    segs, broll, overlays, notes, sfx, blurs = [], [], [], [], [], []
    trans = _Transitions(sfx)
    for b in beats:
        if b.get("skip"):
            continue
        a = b.get("aroll")
        vo = b.get("vo")
        if vo:                                              # a voice-over beat: B-roll picture, the voice-over take as the sound
            brs = [x for x in b["on_screen"].get("broll", []) if x.get("file")]
            if not brs:
                notes.append(f"{b['id']}: voice-over beat has no picture, left out")
                continue
            p = Path(brs[0]["file"])
            p = p if p.is_absolute() else Path(folder) / brs[0]["file"]
            segs.append({"id": b["id"], "src": str(p), "in": float(brs[0].get("in") or 0), "out": float(brs[0].get("in") or 0) + float(vo["end"]) - float(vo["start"]),
                         "zoom": 1.0, "audio_src": str(Path(folder) / vo["file"]), "audio_in": float(vo["start"])})
            for br in brs[1:]:                              # more pictures on a voice-over beat lie over the first one
                q = Path(br["file"])
                q = q if q.is_absolute() else Path(folder) / br["file"]
                broll.extend(trans.add([{"seg": b["id"], "file": str(q), "in": float(br.get("in") or 0), "dur": float(br.get("dur") or 2), "at": float(br.get("at", 0.0)),
                                         **({"zoom": float(br["zoom"]), "pan": br.get("pan", "")} if br.get("zoom") else {})}], br))
            g = live_graphic(b)
            if g and graphic_built(g, b["id"], built):
                overlays.append({"seg": b["id"], "file": built[b["id"]]["file"], "at": float(built[b["id"]].get("at", g.get("at", 0.0))), "dur": float(g.get("dur") or 3)})
            elif g:
                notes.append(f"{b['id']}: graphic '{g.get('idea', '')[:40]}' is not built yet")
            overlays.extend(_text_overlays(b, notes))
            blurs.extend(blur.edit_rows(b, []))
            sfx.extend(_sfx_for(b, g, built, notes))
            continue
        if not a:
            notes.append(f"{b['id']}: no footage, left out")
            continue
        shot = b["on_screen"].get("shot", "a-roll")
        for k, (k_in, k_out) in enumerate(a.get("keep") or [[a["in"], a["out"]]]):      # a trimmed beat plays only the words it keeps; B-roll and graphics hang on its first piece
            segs.append({"id": b["id"] if k == 0 else f"{b['id']}.{k + 1}", "src": str(Path(folder) / a["rel"]), "in": k_in, "out": k_out,
                         "zoom": float(b["on_screen"].get("zoom") or 1.6) if shot == "punch-in" else _punch(b, k)[0],
                         **({} if shot == "punch-in" or _punch(b, k)[0] == 1.0 else {"cx": float(((b.get("on_screen") or {}).get("punch") or {}).get("cx", 0.5)), "cy": _punch(b, k)[1]}),
                         **({"mute": True} if b["on_screen"].get("mute") else {})})
        for i, br in enumerate(b["on_screen"].get("broll", [])):
            if not br.get("file"):
                notes.append(f"{b['id']}: B-roll insert {i + 1} has no file")
                continue
            p = Path(br["file"])
            p = p if p.is_absolute() else Path(folder) / br["file"]
            extra = {**({"stabilize": True} if br.get("stabilize") else {}), **({"zoom": float(br["zoom"]), "pan": br.get("pan", "")} if br.get("zoom") else {}),
                     **({"speed": float(br["speed"])} if br.get("speed") else {}), **({"rotate": int(br["rotate"])} if br.get("rotate") else {})}
            pieces = [{"seg": seg_id, "file": str(p), "in": src_in, "dur": dur, "at": at, **extra}
                      for seg_id, at, dur, src_in in _broll_pieces(b["id"], a.get("keep") or [[a["in"], a["out"]]], float(br.get("at", 0.5)), float(br.get("dur") or 2),
                                                                   float(br.get("in") or 0), float(br.get("speed") or 1.0))]
            broll.extend(trans.add(pieces, br))
        g = live_graphic(b)
        if g and graphic_built(g, b["id"], built):
            overlays.extend(_spread_overlay(b, built[b["id"]]["file"], float(built[b["id"]].get("at", g.get("at", 0.0))), float(g.get("dur") or 3)))
        elif g:
            notes.append(f"{b['id']}: graphic '{g.get('idea', '')[:40]}' is not built yet")
        overlays.extend(_text_overlays(b, notes))
        blurs.extend(blur.edit_rows(b, _pieces(b)))
        sfx.extend(_sfx_for(b, g, built, notes))
    return {"size": list(size), "fps": fps, "snap": True, "segments": segs, "broll": broll, "overlays": overlays, "blurs": blurs, "sfx": sfx, "notes": notes}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["plan"])
    ap.add_argument("work")
    ap.add_argument("name")
    a = ap.parse_args()
    try:
        d = plan(a.work, a.name)
    except ValueError as e:
        sys.exit(f"sections: {e}")
    for s in d["sections"]:
        print(f"{s['id']} {s['dur']:6.1f}s {len(s['beats']):2d} beats  {'AGENT' if s['needs_agent'] else 'local'}  {s['title']}: {s['why']}")


if __name__ == "__main__":
    main()
