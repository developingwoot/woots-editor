"""Make preview N+1 from the notes (ADR 0007): the pure parts of the job. The server runs them in order:
  1. brief()        - what Claude is asked, with the notes and a copy of the plan to edit (in a scratch folder)
  2. apply_answer() - read Claude's answer, write the edited beat map through projectstore, report what it did
  3. (server)       - rebuild the changed sections and stitch (a fake copy of the preview in tests)
  4. finish()       - record the new video as the next version, the applied notes become 'done in <version>'
"""
import json
import re
import time
from pathlib import Path

import config
import projectstore
import reviewnotes
import views

WORK = config.WORK


def read_json(p: Path, default=None):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return default


def preview_file(work: str, name: str) -> Path | None:
    import watchnotes
    p = watchnotes.preview_file(work, name)
    return p if p.exists() else None


def clips_of(work: str, name: str) -> list:
    """The clips of the current preview in order: [{start, dur}] (seconds). From the section renders when they exist, else the stitched sections."""
    try:
        import selfreview
        segs = selfreview.timeline(work, name)["segments"]
        if segs:
            return [{"start": round(s["start"], 2), "dur": round(s["dur"], 2)} for s in segs]
    except Exception:                       # noqa: BLE001  (no section renders: fall back to the sections)
        pass
    stitch = read_json(WORK / work / f"{name}.stitch.json", {}) or {}
    return [{"start": s["start"], "dur": s["dur"]} for s in stitch.get("sections", [])]


def clip_times(work: str, name: str, stage: str = "cut") -> dict:
    """Where each clip really plays in the video the host watches: {beat id: (start, dur)} in seconds. The rough cut: the latest cut version's clips;
    the preview: the stitched sections. The beat map's own start times are estimates that are not kept up to date after every change (clips taken out,
    snapped cut points), so a time the host gives (a note, the playhead) is turned into a clip with these. Empty when there is no video yet."""
    out = {}
    if stage == "cut":
        vs = reviewnotes.versions(work, name, "cut")
        for c in (vs[-1]["clips"] if vs else []):
            if c.get("ref"):
                out[c["ref"]] = (float(c["start"]), float(c["dur"]))
        return out
    try:
        import selfreview
        for s in selfreview.timeline(work, name)["segments"]:
            bid = str(s["id"]).split(".")[0]
            if bid in out:                                  # the pieces of a trimmed beat: one clip
                a, _ = out[bid]
                out[bid] = (a, round(float(s["start"]) + float(s["dur"]) - a, 3))
            else:
                out[bid] = (float(s["start"]), float(s["dur"]))
    except Exception:                                       # noqa: BLE001  (no stitched preview yet)
        return {}
    return out


def kept_said(b: dict) -> str:
    """What the host says in the clip as it plays in the cut: the take's words inside the kept stretches (a trimmed beat drops some), else the beat's text."""
    a = b.get("aroll") or {}
    words = a.get("words") or []
    if not words:
        return b.get("said", "")
    keep = a.get("keep") or [[a.get("in", 0.0), a.get("out", 0.0)]]
    got = [w[0] for w in words if any(k0 - 0.001 <= (w[1] + w[2]) / 2 <= k1 + 0.001 for k0, k1 in keep)]
    return " ".join(got) if got else b.get("said", "")


def ensure_baseline(work: str, name: str, stage: str = "preview"):
    """The preview that exists before any version was made becomes version 1, so the first make has something to compare with."""
    src = preview_file(work, name)
    if src and not reviewnotes.versions(work, name, stage):
        reviewnotes.add_version(work, name, stage, src, ["The first version"], clips_of(work, name))


def plain_notes(work: str, name: str, stage: str) -> list:
    """The open free-text notes: the ones Claude applies. Exact choices on a clip (replace, remove, trim) are applied by code."""
    return [n for n in reviewnotes.open_notes(work, name, stage) if n.get("kind", "note") in ("note", "continuity")]


def brief(work: str, name: str, stage: str, fd: Path) -> str:
    """Write the notes and the plan into fd and return the prompt. Claude answers in answer.json (see apply_answer)."""
    fd.mkdir(parents=True, exist_ok=True)
    notes = [({"id": n["id"], "time": "whole video", "until": None, "note": n["text"]} if n.get("whole") else
              {"id": n["id"], "time": views.time_text(n["t"]), "until": views.time_text(n["t_end"]) if n.get("t_end") is not None else None, "note": n["text"]})
             for n in plain_notes(work, name, stage)]
    (fd / "notes.json").write_text(json.dumps(notes, indent=1), encoding="utf-8")
    bm = read_json(WORK / work / f"{name}.beatmap.json")
    if bm is not None:
        (fd / "beatmap.json").write_text(json.dumps(bm, indent=1), encoding="utf-8")
        import locks
        good = locks.beat_ids(work, name, bm)
        times = clip_times(work, name, stage)
        start = lambda b: times[b["id"]][0] if b["id"] in times else float(b.get("start") or 0)     # noqa: E731  (where it plays in the video the host watched)
        rows = [{"id": b["id"], "section": b.get("section", ""), **({} if b.get("skip") else {"starts_at": views.time_text(start(b))}),
                 "seconds": round(float(b.get("dur") or 0), 1), "said": kept_said(b)[:240],
                 "good": b["id"] in good, "skipped": bool(b.get("skip"))} for b in bm.get("beats", [])]
        (fd / "beats.json").write_text(json.dumps(rows, indent=1, ensure_ascii=False), encoding="utf-8")
    import noteactions
    (fd / "sounds.txt").write_text(noteactions.sounds_list() or "(the host has no sound effects yet)", encoding="utf-8")
    (fd / "music.txt").write_text(noteactions.music_list() or "(the host has no music yet)", encoding="utf-8")
    (fd / "recordings.txt").write_text(noteactions.recordings_list(work, name) or "(no recordings found)", encoding="utf-8")
    return (
        f"The host watched the {'rough cut' if stage == 'cut' else 'preview'} of the host's video and left notes (notes.json, times are minutes:seconds into the video).\n"
        "A note whose time is \"whole video\" is about the video as a whole (for example: too long, cut more, be pickier). Apply it across the plan: set `skip` on the weakest beats (never a beat the host marked good), "
        "shorten, or tighten as the note asks, and say in the summary what you did overall.\n"
        "beats.json is a short list of every beat (id, section, where it starts in the video, seconds, what is said, `good` = the host marked it good, `skipped`): read it first. beatmap.json is the whole plan and is large.\n"
        "To take beats out of the video, list their ids in `skip_beats` (never one marked good) and do NOT send `beatmap`. Send `beatmap` only for a change `skip_beats` and `edits` cannot make, and then send the whole file.\n"
        "The app can also do these for you; list them in `edits` (times are minutes:seconds into the video, like the notes; use what is said in beats.json to put the time on the word the note means):\n"
        ' - a web page as B-roll: {"note": <id>, "do": "web", "time": "0:31", "url": "<the public address the note gives>", "find": "<a few words that are on that page to scroll to and highlight, or empty>", "seconds": 5}.'
        " The app captures the page itself; never say it cannot be done because there is no recording of the page.\n"
        ' - a sound effect: {"note": <id>, "do": "sfx", "time": "0:31", "sound": "<one name from sounds.txt that fits what the note asks for>"}.\n'
        ' - on-screen text: {"note": <id>, "do": "text", "time": "0:31", "text": "<the words on screen, at most about 8>", "kind": "correction|detail"}.'
        ' A correction fixes something the host misspoke and starts with an asterisk ("*0.4 mm nozzle, not 0.6"); a detail adds a short fact (a price, a model number).\n'
        ' - another camera angle with the take\'s own sound: {"note": <id>, "do": "angle", "file": "<the recording the note names, exactly as written>"}.'
        " The app lines it up with the take by its sound and shows its picture wherever it covers the cut.\n"
        ' - background music: {"note": <id>, "do": "music", "from": "0:00", "until": "<m:ss, or empty for to the end>", "track": "<one name from music.txt that fits the note and the video>"}.'
        " The app mixes it under the host's voice; music.txt is the host's music library (name | tempo | length).\n"
        ' - take some words out of a clip: {"note": <id>, "do": "cut", "time": "2:05", "words": "<the exact words to take out, as in beats.json>"}.'
        " The rest of the clip stays. This works on a clip marked good too (the host asked for it): never skip the beat or rewrite the beat map for this.\n"
        ' - another recording over the picture (a timelapse, a close-up, a shot from another day): {"note": <id>, "do": "broll", "time": "10:41", "file": "<a path from recordings.txt>", "from": <seconds into the recording, 0 for the start>, "seconds": 5, "speed": <1, or more to speed it up>}.'
        " Its own sound is not used, so it needs no matching sound. recordings.txt lists the footage folder (path | seconds).\n"
        ' - blur a part of the picture (a name, an address, a screen): {"note": <id>, "do": "blur", "time": "0:31", "what": "<what to hide, in a few words>"}.'
        " The app puts a box on that clip for the host to place over it on the frame; the box then follows it through the clip.\n"
        "For each note, decide whether `skip_beats`, `edits` or a change to the beat map makes the video match what the host asked. A note that needs an edit is applied: put it under `applied`.\n"
        "Prefer `edits` to sending the beat map: they are small and safe. Do not skip a note because the beat map is large.\n"
        "Write answer.json in this folder:\n"
        '{"applied": [{"id": <note id>, "summary": "<one plain sentence about what you changed, no ids or file names>"}],\n'
        ' "skipped": [{"id": <note id>, "why": "<one plain sentence>"}],\n'
        ' "skip_beats": ["<beat id to take out>"],\n'
        ' "edits": [<the edits above>],\n'
        ' "lesson": "<optional: ONE general sentence, no times and no video names, only when a note taught something that applies to other videos>",\n'
        ' "beatmap": <the whole edited beat map, only if you changed it>}\n'
        "Change as little as possible. Keep every field you do not need to change exactly as it is. Do not write anywhere else.")


def apply_answer(work: str, name: str, stage: str, path: Path) -> tuple[bool, str, dict]:
    """Returns (ok, message, result) with result = {applied_ids, changes}. The beat map is only replaced by a well-formed one."""
    ans = read_json(path)
    if not isinstance(ans, dict):
        return False, "Claude's answer could not be read.", {}
    open_ids = {n["id"] for n in plain_notes(work, name, stage)}
    applied = [a for a in ans.get("applied") or [] if isinstance(a, dict) and a.get("id") in open_ids and str(a.get("summary", "")).strip()]
    if not applied:
        whys = [" ".join(str(s.get("why", "")).split())[:300] for s in ans.get("skipped") or [] if isinstance(s, dict) and str(s.get("why", "")).strip()]
        return False, "Claude could not apply any of the notes." + "".join(f" {w}" for w in whys), {}
    bm = ans.get("beatmap")
    if bm is not None and (not isinstance(bm, dict) or not isinstance(bm.get("beats"), list)):
        return False, "Claude's edited plan was not usable, so nothing was changed.", {}
    skip = [str(x) for x in ans.get("skip_beats") or [] if isinstance(x, (str, int))]
    if skip:
        base = bm if bm is not None else read_json(WORK / work / f"{name}.beatmap.json")
        if not isinstance(base, dict):
            return False, "There is no plan to take beats out of.", {}
        import locks
        good = locks.beat_ids(work, name, base)
        taken = 0
        for b in base["beats"]:
            if b.get("id") in skip and b["id"] not in good and not b.get("skip"):
                b["skip"] = True
                taken += 1
        bm = base if taken or bm is not None else None
    if bm is not None:
        import beatmap
        if all("dur" in b for b in bm["beats"]):
            beatmap.retime(bm["beats"])         # the times after a beat that was taken out move up
        projectstore.write_json(WORK / work / f"{name}.beatmap.json", bm, why="notes applied")
    changes = [" ".join(str(a["summary"]).split())[:200] for a in applied]
    n_skipped = len([s for s in ans.get("skipped") or [] if isinstance(s, dict)])
    msg = f"Applied {len(applied)} note{'s' if len(applied) != 1 else ''}" + (f"; {n_skipped} could not be applied." if n_skipped else ".")
    import noteactions
    return True, msg, {"applied_ids": [a["id"] for a in applied], "changes": changes, "lesson": clean_lesson(ans.get("lesson")),
                       "summaries": {a["id"]: changes[i] for i, a in enumerate(applied)}, "actions": noteactions.parse(ans, {a["id"] for a in applied})}


def after_actions(result: dict, done: dict, note_times: dict) -> dict:
    """The applied notes after the app did their edits (noteactions.run's {changes, failed, by_note}): a note whose edit failed is not done (it stays open),
    and What changed says why; for a note the app did, What changed shows what the app did instead of Claude's summary."""
    failed, by_note = done.get("failed") or {}, done.get("by_note") or {}
    keep = [i for i in result["applied_ids"] if i not in failed]
    swap = {result["summaries"].get(i): i for i in list(failed) + list(by_note)}
    changes = []
    for c in result["changes"]:
        i = swap.get(c)
        if i is None:
            changes.append(c)
        elif i not in failed:
            changes += by_note[i]
    changes += [f"Not done, the note at {views.time_text(float(note_times.get(i) or 0))}: {why}" for i, why in failed.items()]
    return {**result, "applied_ids": keep, "changes": changes}


def clean_lesson(x) -> str:
    """One general sentence: no times, no ids, not long. Anything else is not offered."""
    t = " ".join(str(x or "").split())
    if not 12 <= len(t) <= 240 or re.search(r"\d+:\d\d|\b[SBG]\d{2}\b", t):
        return ""
    return t


def finish_cut(work: str, name: str, video: Path, rows: list, result: dict) -> dict:
    """The rendered rough cut becomes the next version. `result` = {applied_ids, changes}; the first cut has none."""
    changes = result.get("changes") or (["The first cut"] if not reviewnotes.versions(work, name, "cut") else ["Made again, nothing changed"])
    clips = [{"start": r["start"], "dur": r["dur"], "ref": r["ref"]} for r in rows]
    return reviewnotes.add_version(work, name, "cut", video, changes, clips, result.get("applied_ids"), result.get("suggestions"), result.get("lesson", ""))


def finish(work: str, name: str, stage: str, result: dict) -> dict:
    src = preview_file(work, name)
    if not src:
        raise ValueError("there is no new video to keep")
    return reviewnotes.add_version(work, name, stage, src, result["changes"], clips_of(work, name), result["applied_ids"], lesson=result.get("lesson", ""))


def fake_stitch(work: str, name: str):
    """Tests (WOOTS_FAKE_CLAUDE set): no section builds, a copy of the current preview under a new name becomes the stitched preview."""
    import shutil
    import watchnotes
    src = watchnotes.preview_file(work, name)
    if not src.exists():
        raise ValueError("there is no preview to start from")
    dst = src.with_name(f"{name}.preview-half.fake{int(time.time() * 1000)}.mp4")
    shutil.copyfile(src, dst)
    st = read_json(WORK / work / f"{name}.stitch.json", {}) or {}
    st["file"] = dst.name
    projectstore.atomic_write(WORK / work / f"{name}.stitch.json", json.dumps(st, indent=1).encode("utf-8"))
