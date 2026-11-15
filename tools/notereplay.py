"""The host's notes outlive a re-made rough cut (the host 2026-11-14: re-making the cut dropped three rounds of notes).

Making the rough cut again builds the plan from the recordings, so what earlier notes changed is gone. The notes themselves are kept, and each one
remembers the words that were being said where it was written (`said`): a time means nothing in a new cut, the words do.

  anchor(work, name, stage, t)   the words playing around time t of the video the host is watching (saved on the note when it is written)
  reopen(work, name)             before the plan is built again: every note an earlier cut applied is open again (`again`), with its anchor
  place(work, name)              after the new cut is rendered: each open note moves to where its words play now; one whose words are no longer
                                 in the cut is marked `lost` and the version says so
Claude applies the open notes when the host makes the next version (the notes are applied by Claude, not by buttons); the brief gives it `said`.
"""
import clipmap
import config
import makeversion
import recut
import reviewnotes

WORK = config.WORK
AROUND_S = 4.0               # the anchor is what is said this long before and after the note's time
MIN_SHARE = 0.5              # share of the anchor's words a clip of the new cut must say to be the note's place
PLAIN = ("note", "continuity")


def _beats(work: str, name: str) -> list:
    return (clipmap.read_json(WORK / work / f"{name}.beatmap.json", None) or {}).get("beats", [])


def _words_around(beat: dict, off: float) -> str:
    lo = max(0.0, off - AROUND_S)
    spans = recut.covered_source(beat, lo, off + AROUND_S - lo) if beat.get("aroll") else []
    got = " ".join(w[0] for w in (beat.get("aroll") or {}).get("words") or [] if any(a - 0.05 <= w[1] < b for a, b in spans))
    return got or makeversion.kept_said(beat)[:200]


def anchor(work: str, name: str, stage: str, t: float) -> str:
    """What is said around time t of the latest video of this stage ('' when there is no video or nothing is said there)."""
    times = makeversion.clip_times(work, name, stage)
    for b in _beats(work, name):
        start, dur = times.get(b.get("id"), (None, 0))
        if start is not None and start <= t < start + dur:
            return _words_around(b, t - start)[:300]
    return ""


def reopen(work: str, name: str) -> dict:
    """Call before the plan is built again. Returns {again: notes open again, choices: exact clip choices of earlier cuts that cannot be carried over}."""
    if not reviewnotes.versions(work, name, "cut"):
        return {"again": 0, "choices": 0}
    j = reviewnotes.load(work, name)
    again = choices = 0
    for n in j["cut"]:
        if n.get("kind", "note") not in PLAIN:
            choices += n.get("status") == "done"
            continue
        if not n.get("said") and not n.get("whole"):
            n["said"] = anchor(work, name, "cut", float(n.get("t") or 0))
        if n.get("status") == "done":
            n.update(status="open", was_in=n.get("applied_in"), applied_in=None, again=True)
            again += 1
    if again:
        reviewnotes.save(work, name, j)
    return {"again": again, "choices": choices}


def find(said: str, beats: list):
    """The beat of the new cut that says the anchor's words (the largest share of them, at least MIN_SHARE), or None."""
    want = set(clipmap.tokens_of(said))
    if not want:
        return None
    best, top = None, 0.0
    for b in beats:
        if b.get("skip"):
            continue
        share = len(want & set(clipmap.tokens_of(makeversion.kept_said(b)))) / len(want)
        if share > top:
            best, top = b, share
    return best if top >= MIN_SHARE else None


def place(work: str, name: str) -> dict:
    """Call after the new cut is a version. Returns {placed: n, lost: [the text of each note whose words are no longer in the cut]}."""
    j = reviewnotes.load(work, name)
    times = makeversion.clip_times(work, name, "cut")
    beats = _beats(work, name)
    placed, lost = 0, []
    for n in j["cut"]:
        if n.get("status") == "done" or n.get("whole") or n.get("kind", "note") not in PLAIN or not (n.get("again") or n.get("said")):
            continue
        b = find(n.get("said") or "", beats)
        if b and b["id"] in times:
            n["t"], n["t_end"] = round(times[b["id"]][0], 1), None
            n.pop("lost", None)
            placed += 1
        else:
            n["lost"] = True
            lost.append(n["text"])
    again = sum(1 for n in j["cut"] if n.get("again") and n.get("status") != "done")
    if again and j["versions"]["cut"]:                      # the new cut says so, first in its list of changes
        lines = [f"{again} note{'' if again == 1 else 's'} from earlier cuts {'is' if again == 1 else 'are'} open again: make a new version and Claude applies {'it' if again == 1 else 'them'} to this cut"]
        lines += [f"The words this note was about are no longer in the cut: \"{t[:90]}\"" for t in lost]
        j["versions"]["cut"][-1]["changes"] = lines + list(j["versions"]["cut"][-1]["changes"])
    if placed or lost or again:
        reviewnotes.save(work, name, j)
    return {"placed": placed, "lost": lost}
