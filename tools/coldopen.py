"""The cold open (ADR 0009): a few seconds from the best lines of the host's own takes, put before the intro, that make a viewer ask "what happens?".

Claude is given the hook library of the youtube-script skill and the numbered sentences of the cut (with the source seconds of each) and proposes two
options, each a few sentences in the order they should play. The first option is put at the start of the cut; the other is kept to switch to.
`<name>.coldopen.json` (a plan file): {"options": [{"title", "hook_type", "why", "question", "clips": [{"rel", "start", "end", "said"}]}], "chosen": 0, "by": "auto|user"}
The same words are still in the body of the video, as on every channel that opens cold.
"""
import json
import os
import re
from pathlib import Path

import beatmap
import clipmap
import config
import projectstore
import skillrules

WORK = config.WORK
MAX_SENTENCE_S = 10.0
MIN_SENTENCE_S = 1.5
OPEN_MIN_S, OPEN_MAX_S, AFTER_S = 6.0, 25.0, 120.0       # set from the skill (rough-cut.json) by reload_rules()


def reload_rules():
    global OPEN_MIN_S, OPEN_MAX_S, AFTER_S
    r = skillrules.rules()
    OPEN_MIN_S, OPEN_MAX_S = r["cold_open_min_s"], r["cold_open_max_s"]
    AFTER_S = float(os.environ.get("WOOTS_COLD_AFTER", r["cold_open_after_s"]))


reload_rules()
END_RE = re.compile(r"[.?!]$")


def path(work: str, name: str) -> Path:
    return WORK / work / f"{name}.coldopen.json"


def load(work: str, name: str) -> dict:
    try:
        return json.loads(path(work, name).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {}


def sentences(data: dict) -> list:
    """[{id 'B05.2', rel, start, end, text}] for every sentence the cut says from AFTER_S seconds into the body on (a kept sentence between MIN and MAX
    seconds long): a line from the first minutes would be heard twice in a row."""
    out = []
    for b in data["beats"]:
        ar = b.get("aroll")
        if not ar or b.get("skip") or b.get("vo") or not ar.get("keep") or str(b.get("id", "")).startswith("H") or b.get("start", 0) < AFTER_S:
            continue
        words = [w for w in ar.get("words", []) if any(a - 0.001 <= (w[1] + w[2]) / 2 <= z + 0.001 for a, z in ar["keep"])]
        cur, n = [], 0
        for w in words:
            cur.append(w)
            if END_RE.search(w[0]) or len(cur) >= 40:
                n += 1
                d = cur[-1][2] - cur[0][1]
                if MIN_SENTENCE_S <= d <= MAX_SENTENCE_S:
                    out.append({"id": f"{b['id']}.{n}", "rel": ar["rel"], "start": cur[0][1], "end": cur[-1][2], "text": " ".join(x[0] for x in cur)})
                cur = []
        if cur:                                                  # a beat that ends without a full stop
            n += 1
            d = cur[-1][2] - cur[0][1]
            if MIN_SENTENCE_S <= d <= MAX_SENTENCE_S:
                out.append({"id": f"{b['id']}.{n}", "rel": ar["rel"], "start": cur[0][1], "end": cur[-1][2], "text": " ".join(x[0] for x in cur)})
    return out


def opening(data: dict, seconds: float = 25.0) -> str:
    """The words the cut opens with, until `seconds` of it have played."""
    said, t = [], 0.0
    for b in data["beats"]:
        if t >= seconds:
            break
        if b.get("aroll") and not b.get("skip") and not b.get("vo") and b.get("said"):
            said.append(b["said"])
        t += b.get("dur", 0)
    return " ".join(said)[:900]


def opening_seconds(data: dict, seconds: float = 25.0) -> float:
    return min(seconds, sum(b.get("dur", 0) for b in data["beats"]))


def brief(work: str, name: str, fd: Path) -> str:
    import outline
    fd.mkdir(parents=True, exist_ok=True)
    data = json.loads(beatmap.path_of(work, name).read_text(encoding="utf-8-sig"))
    sents = sentences(data)
    (fd / "sentences.json").write_text(json.dumps([{"id": s["id"], "seconds": round(s["end"] - s["start"], 1), "text": s["text"]} for s in sents], indent=1),
                                       encoding="utf-8")
    import story
    got = skillrules.copy_into(fd, "coldopen")
    model = outline.load(work, name)
    title = model.get("title") or name
    hook = next((ln["said"] for ln in outline.speech_lines(model)[:3]), "")
    return (f"You are choosing the cold open for the host's YouTube video '{title}'. sentences.json lists every sentence the host says in the rough cut, with an id and its length. "
            + skillrules.read_first_line(got) + "hook-library.md holds the host's hook patterns and the Hook QA checklist. "
            f"The host's outline opens with: \"{hook[:300]}\".\n"
            + (f"The story read of the recordings found these strong openings (prefer them, or something better): {story.opening_hint(work, name)}.\n" if story.opening_hint(work, name) else "") +
            f"First decide whether a cold open is needed at all. The cut already opens with these words (the first {opening_seconds(data):.0f} seconds): \"{opening(data)}\" "
            "If that opening is already a strong hook (a clear question or stake in the first 15 seconds, a result, a surprise, a promise a viewer wants kept), a cold open only delays it: "
            'write {"options": [], "skip": true, "why": "<one plain sentence>"} and stop. Otherwise:\n'
            f"Choose two different cold opens. Each is 2 to 4 sentences from sentences.json (they all come from later than {AFTER_S:.0f} seconds into the cut, so they are not heard twice in a row), played in the order you list them, {OPEN_MIN_S:.0f} to {OPEN_MAX_S:.0f} seconds in all. "
            "The goal: the most captivating opening, one that makes a viewer ask 'what happens?' or 'I need to know more'. Prefer a concrete result, a surprise, "
            "a stake or an honest failure over a greeting or a list of what the video covers. The sentences must make sense when heard first, with no intro before them. "
            "Write hooks.json here:\n"
            '{"options": [{"title": "<a few words>", "hook_type": "<H-number and name from the library>", "question": "<the question a viewer is left asking>", '
            '"why": "<one plain sentence>", "sentences": ["B05.2", "B13.1"]}]}\n'
            "Use only ids from sentences.json. Write nowhere else.")


def apply_options(work: str, name: str, p: Path) -> tuple[bool, str]:
    try:
        answer = json.loads(Path(p).read_text(encoding="utf-8-sig"))
        raw = answer.get("options", [])
        data = json.loads(beatmap.path_of(work, name).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, AttributeError):
        return False, "Claude's answer could not be read."
    if answer.get("skip") and not raw:                           # the opening is a hook already: no cold open (the creator 2026-10-29)
        why = str(answer.get("why") or "")[:240]
        projectstore.write_json(path(work, name), {"options": [], "skip": True, "why": why, "chosen": 0, "by": "auto"})
        return True, "Claude: the opening already hooks, no cold open."
    by_id = {s["id"]: s for s in sentences(data)}
    options = []
    for o in raw if isinstance(raw, list) else []:
        ids = [i for i in (o.get("sentences") or []) if i in by_id]
        clips = [{k: by_id[i][k] for k in ("rel", "start", "end")} | {"said": by_id[i]["text"]} for i in ids]
        total = sum(c["end"] - c["start"] for c in clips)
        if len(clips) >= 1 and OPEN_MIN_S - 2 <= total <= OPEN_MAX_S + 2:
            options.append({"title": str(o.get("title") or "")[:60], "hook_type": str(o.get("hook_type") or "")[:60],
                            "why": str(o.get("why") or "")[:240], "question": str(o.get("question") or "")[:200], "clips": clips})
    if not options:
        return False, "Claude did not give a usable cold open."
    old = load(work, name)
    keep_choice = old.get("by") == "user"
    projectstore.write_json(path(work, name), {"options": options[:2], "chosen": 0 if not keep_choice else min(old.get("chosen", 0), len(options) - 1),
                                               "by": "user" if keep_choice else "auto"})
    return True, f"Claude suggested {len(options[:2])} cold open{'s' if len(options) > 1 else ''}."


def choose(work: str, name: str, index: int) -> dict:
    d = load(work, name)
    if not d.get("options") or not 0 <= index < len(d["options"]):
        raise ValueError("that cold open is not one of the choices")
    d["chosen"], d["by"] = index, "user"
    projectstore.write_json(path(work, name), d)
    return d


def insert(work: str, name: str) -> int:
    """Put the chosen cold open at the start of the beat map (replacing the one there). Returns how many beats it added."""
    d = load(work, name)
    bp = beatmap.path_of(work, name)
    try:
        data = json.loads(bp.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return 0
    data["beats"] = [b for b in data["beats"] if not str(b.get("id", "")).startswith("H")]
    opts = d.get("options") or []
    n = 0
    if opts:
        analysis = (clipmap.read_json(WORK / work / f"{name}.footage.json", None) or {}).get("analysis") or {}
        head = []
        for i, c in enumerate(opts[min(d.get("chosen", 0), len(opts) - 1)]["clips"], start=1):
            words = [w for w in (analysis.get(c["rel"]) or {}).get("list", []) if w[1] >= c["start"] - 0.01 and w[2] <= c["end"] + 0.01]
            if not words:
                continue
            keep = beatmap.keep_from_idx(words, range(len(words)))
            ar = {"rel": c["rel"], "in": keep[0][0], "out": keep[-1][1], "dur": round(sum(b - a for a, b in keep), 2),
                  "span": clipmap.span_id(c["rel"], words[0][1]), "span_in": keep[0][0], "span_out": keep[-1][1], "keep": keep, "trim_by": "hook", "words": words}
            head.append(beatmap.blank_beat(f"H{i:02d}", "Cold open", [], c["said"], ar, ar["dur"], False, []))
        data["beats"] = head + data["beats"]
        n = len(head)
    beatmap.retime(data["beats"])
    clipmap.write_json(bp, data)
    return n
