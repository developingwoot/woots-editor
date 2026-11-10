"""A read of the rough cut as a viewer hears it (the host, 2026-10-29): Claude gets the words of the cut in order and finds what no cut of one recording can see.

 - two statements that contradict ("The app gets B tier. The app gets A tier."): the one the host corrected goes, the later stays;
 - a general line right before the specific one ("it took me a little longer. It took me 22 minutes"): the general one goes;
 - the same idea said twice in other words, or a line that does not make sense where it now stands;
 - passages that belong somewhere else (said as a suggestion; the cut does not move them yet).
`<name>.cutreview.json` (a plan file): {"drops": [{"text", "kind", "why"}], "emphasis": [text], "checks": [{"text", "why"}], "suggestions": [{"text", "before", "why"}]}. A drop names the sentence by its
words, so the file still applies to the next cut of the same recordings. `apply` takes the drops out and trims the beats again.
"""
import json
import re
from pathlib import Path

import beatmap
import clipmap
import config
import footage_cfg
import locks
import projectstore
import silence
import skillrules

WORK = config.WORK
END_RE = re.compile(r"[.?!]$")
LOCKED_SKIPPED: list = []         # what the last `apply` left alone because the creator marked it good: [{text, kind, why}]
KINDS = ("contradiction", "general-then-specific", "repeat", "does-not-fit", "cut-off", "unclear")
VERSION = 3                      # 2: emphasis, checks, the hook budget; 3: unclear sentences, restores


def path(work: str, name: str) -> Path:
    return WORK / work / f"{name}.cutreview.json"


def load(work: str, name: str) -> dict:
    return clipmap.read_json(path(work, name), {}) or {}


def norm(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", text.lower()).strip()


def _kept(ar: dict, w) -> bool:
    return any(a - 0.001 <= (w[1] + w[2]) / 2 <= z + 0.001 for a, z in ar["keep"])


def sentence_runs(beat: dict) -> list:
    """[(text, [word positions in aroll.words])] for each sentence the beat keeps."""
    ar = beat["aroll"]
    out, cur = [], []
    for i, w in enumerate(ar.get("words", [])):
        if not _kept(ar, w):
            continue
        cur.append(i)
        if END_RE.search(w[0]) or len(cur) >= 40:
            out.append((" ".join(ar["words"][j][0] for j in cur), cur))
            cur = []
    if cur:
        out.append((" ".join(ar["words"][j][0] for j in cur), cur))
    return out


def _talking(b: dict) -> bool:
    return bool(b.get("aroll")) and not b.get("skip") and not b.get("vo") and not str(b.get("id", "")).startswith("H")


def left_out_runs(beat: dict) -> list:
    """[(text, [word positions])] for the sentences of a beat's span that the cut does not play (five words or more, a full stop at the end)."""
    ar = beat["aroll"]
    out, cur = [], []
    for i, w in enumerate(ar.get("words", [])):
        if _kept(ar, w):
            cur = []
            continue
        cur.append(i)
        if END_RE.search(w[0]):
            if len(cur) >= 5:
                out.append((" ".join(ar["words"][j][0] for j in cur), cur))
            cur = []
    return out


def sentences(data: dict, with_left_out: bool = False, held: set = frozenset()) -> list:
    """Every sentence of the cut in order. With `with_left_out`, the sentences of the beats' spans that were taken out (marked left_out, ids like B08.L1) are in between, in the order the host said them."""
    out = []
    for b in data["beats"]:
        if not _talking(b):
            continue
        intro = footage_cfg.auto_role(b["aroll"]["rel"]) == "intro"
        ws = b["aroll"]["words"]
        rows = [(idx[0], text, idx, False) for text, idx in sentence_runs(b)]
        if with_left_out:
            rows += [(idx[0], text, idx, True) for text, idx in left_out_runs(b)]
        n = m = 0
        for _, text, idx, left in sorted(rows):
            if left:
                m += 1
            else:
                n += 1
            out.append({"id": f"{b['id']}.L{m}" if left else f"{b['id']}.{n}", "recording": b["aroll"]["rel"], "at": round(ws[idx[0]][1], 1),
                        "seconds": round(ws[idx[-1]][2] - ws[idx[0]][1], 1), "text": text, **({"left_out": True} if left else {}), **({"part": "intro"} if intro else {}),
                        **({"locked": True} if not left and norm(text) in held else {})})
    return out


FUNCTION_END = {"a", "an", "the", "of", "to", "and", "or", "but", "so", "that", "with", "for", "in", "on", "at", "is", "was", "are", "i", "you", "we", "it", "my", "your", "our", "their", "this", "if", "because"}


def dangling(data: dict) -> list:
    """Sentences that stop in the middle ('I had to use AI to even get it to'): the last word is one no sentence ends on, or one or two words with no end (a stumbled start). A thought a viewer cannot finish goes."""
    out = []
    for b in data["beats"]:
        if not _talking(b):
            continue
        for text, idx in sentence_runs(b):
            last = re.sub(r"[^a-z']", "", text.split()[-1].lower())
            n = len(text.split())
            if not END_RE.search(text.split()[-1]) and ((n >= 3 and last in FUNCTION_END) or n <= 2):
                out.append({"text": text, "kind": "cut-off", "why": "stops in the middle of the thought"})
    return out


def hook_budget(data: dict, hook_total: float) -> dict:
    """What the opening may take: the cold open (the H beats) plus the intro recordings must fit hook_total seconds (the host: the meat starts by 30 s)."""
    cold = sum(b["dur"] for b in data["beats"] if str(b.get("id", "")).startswith("H"))
    intro = sum(b["dur"] for b in data["beats"] if _talking(b) and footage_cfg.auto_role(b["aroll"]["rel"]) == "intro")
    return {"cold_open_s": round(cold, 1), "intro_s": round(intro, 1), "intro_allowed_s": round(max(8.0, hook_total - cold), 1)}


def brief(work: str, name: str, fd: Path) -> str:
    fd.mkdir(parents=True, exist_ok=True)
    data = json.loads(beatmap.path_of(work, name).read_text(encoding="utf-8-sig"))
    (fd / "cut.json").write_text(json.dumps(sentences(data, with_left_out=True, held=locks.texts(work, name)), indent=1), encoding="utf-8")
    got = skillrules.copy_into(fd, "cutreview")
    hb = hook_budget(data, skillrules.rules()["hook_total_s"])
    over = hb["intro_s"] - hb["intro_allowed_s"]
    return ("You are reading the rough cut of the host's YouTube video the way a viewer will hear it. cut.json lists every sentence of the cut in order: its id, the recording it "
            "comes from and its words; sentences marked locked are ones the host marked good: never drop, restore a replacement for, move or flag them. Sentences marked left_out (ids like B08.L1) are in the recording between the others but the cut does not play them. " + skillrules.read_first_line(got) +
            "Find what makes a viewer stop following. Only these kinds:\n"
            "- contradiction: two statements that disagree (the host said 'the app gets B tier' and right after 'the app gets A tier'). The host corrected the line: drop the earlier one.\n"
            "- general-then-specific: a vague line and then the specific one saying the same ('it took me a little bit longer' then 'it took me 22 minutes'). Drop the vague one.\n"
            "- repeat: the same idea said twice in other words, or a phrase said twice. Drop the weaker copy.\n"
            "- does-not-fit: a sentence that makes no sense where it stands (refers to something not yet said, or is left over from a stumble).\n"
            "- cut-off: a sentence that stops before its thought is finished ('it's only a couple.' with nothing after it). Drop it.\n"
            + "- unclear: a sentence a first-time viewer cannot follow because the cut left out what it refers to ('Not a big game changer, but...' with no earlier mention of what; 'stuff that you don't need "
              "to click on' with no mention of what is clickable; 'highlight and comment it out' before saying the host edits config). Read the cut as someone who has never seen the video. Fix it by `restore`: list the "
              "left_out sentence ids just before it that set it up (the reason, the example, the missing subject), at most three; only when none of them does, drop the unclear sentence. "
              "Never restore a sentence that repeats one already in the cut.\n"
            + (f"- intro-too-long: the opening is the cold open ({hb['cold_open_s']} s) plus the sentences marked part=intro ({hb['intro_s']} s). The viewer must reach the content by "
               f"{skillrules.rules()['hook_total_s']:.0f} s, so the intro may take {hb['intro_allowed_s']} s: drop the least important intro sentences (about {over:.0f} s) and keep the ones that "
               "set up the promise of the video, in an order that still makes sense. Use kind does-not-fit for them.\n" if over > 1 else "")
            + "Also check the facts you can check (a price, a count, a claim about how a program works) and say any you doubt in `checks`, without dropping the sentence. "
            "List in `emphasis` the sentences that are intense or carry a point (a verdict, a surprise, a number that matters, a strong opinion): about 1 in 15, never more. "
            "The picture punches in on them.\n"
            "A call to the viewer (comment, subscribe, 'which one do you use?') stays when it fits the end of the video. "
            "Be careful: keep jokes, transitions ('next up...'), and anything that is new information. Do not drop more than about 1 sentence in 20 (the intro-too-long ones do not count). "
            "Separately list `suggestions`: a passage that would work better somewhere else (say which sentence ids and before which sentence, and why), such as an "
            "explanation of the test that belongs at the start. Write review.json here:\n"
            '{"drops": [{"id": "B05.2", "kind": "contradiction|general-then-specific|repeat|does-not-fit|cut-off|unclear", "why": "<one plain sentence>"}], '
            '"restore": [{"ids": ["B08.L1", "B08.L2"], "for": "B09.1", "why": "<what they explain>"}], "emphasis": ["B07.2"], '
            '"checks": [{"id": "B09.1", "why": "<what you doubt>"}], '
            '"suggestions": [{"ids": ["B20.1"], "before": "B04.1", "why": "<one plain sentence>"}]}\n'
            "Use only ids from cut.json. Write nowhere else.")


def apply_review(work: str, name: str, p: Path) -> tuple[bool, str]:
    try:
        raw = json.loads(Path(p).read_text(encoding="utf-8-sig"))
        data = json.loads(beatmap.path_of(work, name).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return False, "Claude's answer could not be read."
    import takes
    chosen = {norm(r["text"]) for r in takes.restores(work, name)}                  # the take the takes read chose to play: this read does not drop it as a repeat
    by_id = {s["id"]: s for s in sentences(data, with_left_out=True)}
    held = locks.texts(work, name)
    drops = [{"text": by_id[d["id"]]["text"], "kind": d.get("kind") if d.get("kind") in KINDS else "repeat", "why": str(d.get("why") or "")[:200]}
             for d in raw.get("drops", []) if isinstance(d, dict) and d.get("id") in by_id and not by_id[d["id"]].get("left_out") and norm(by_id[d["id"]]["text"]) not in chosen and norm(by_id[d["id"]]["text"]) not in held]
    restores = []
    for r in raw.get("restore", []) if isinstance(raw.get("restore"), list) else []:
        if isinstance(r, dict):
            restores += [{"text": by_id[i]["text"], "for": by_id.get(r.get("for"), {}).get("text", "")[:80], "why": str(r.get("why") or "")[:200]}
                         for i in (r.get("ids") or [])[:3] if i in by_id and by_id[i].get("left_out")]
    locked_beats = locks.beat_ids(work, name, data)
    restores = [r for r in restores if not any(norm(s["text"]) == norm(r["text"]) and s["id"].split(".")[0] in locked_beats for s in by_id.values())]
    restores = restores[:max(2, len(by_id) // 12)]
    intro_n = sum(1 for s in by_id.values() if s.get("part") == "intro")
    drops = drops[:max(1, len(by_id) // 20) + intro_n // 2]
    emphasis = [by_id[i]["text"] for i in raw.get("emphasis", []) if i in by_id][:max(1, len(by_id) // 12)]
    checks = [{"text": by_id[c["id"]]["text"][:200], "why": str(c.get("why") or "")[:200]} for c in raw.get("checks", []) if isinstance(c, dict) and c.get("id") in by_id]
    sugg = [{"text": " ".join(by_id[i]["text"] for i in s.get("ids", []) if i in by_id)[:300], "before": by_id.get(s.get("before"), {}).get("text", "")[:120],
             "why": str(s.get("why") or "")[:240]} for s in raw.get("suggestions", []) if isinstance(s, dict)]
    projectstore.write_json(path(work, name), {"v": VERSION, "drops": drops, "restores": restores, "emphasis": emphasis, "checks": checks, "suggestions": [s for s in sugg if s["text"]]})
    return True, f"Claude read the cut: {len(drops)} sentence{'' if len(drops) == 1 else 's'} to take out, {len(restores)} to bring back, {len(sugg)} suggestion{'' if len(sugg) == 1 else 's'}."


def apply(work: str, name: str, max_pause: float, pad: float, lead: float, extra: list = (), restore: list = ()) -> list:
    """Take the saved drops (and `extra`, e.g. the other takes of takes.py) out of the beat map (each sentence is found by its words). Returns [{text, kind, why}] of what went."""
    saved = (load(work, name).get("drops") or []) + list(extra)
    bp = beatmap.path_of(work, name)
    data = clipmap.read_json(bp, None)
    if not data:
        return []
    held = locks.texts(work, name)                                                     # sentences the creator marked good: nothing here is dropped
    LOCKED_SKIPPED.clear()
    want = {}
    for d in saved + dangling(data):
        if norm(d["text"]) in held:
            LOCKED_SKIPPED.append(d)
        else:
            want[norm(d["text"])] = d
    locked_beats = locks.beat_ids(work, name, data)
    back = {norm(r["text"]) for r in (load(work, name).get("restores") or []) + list(restore)}
    if not want and not back:
        return []
    cfg = clipmap.read_json(WORK / work / f"{name}.footage.json", {}) or {}
    cache = clipmap.read_json(silence.path(work, name), None) or {}
    done, kept_beats = [], []
    for b in data["beats"]:
        if not _talking(b):
            kept_beats.append(b)
            continue
        gone = set()
        for text, idx in sentence_runs(b):
            d = want.get(norm(text))
            if d:
                gone.update(idx)
                done.append(d)
        returned = set()
        for text, idx in left_out_runs(b) if back and b["id"] not in locked_beats else []:
            if norm(text) in back and norm(text) not in want:
                returned.update(idx)
        if not gone and not returned:
            kept_beats.append(b)
            continue
        ar = b["aroll"]
        words = ar["words"]
        left = [i for i, w in enumerate(words) if (_kept(ar, w) and i not in gone) or i in returned]
        if not left:
            continue                                                           # the whole beat was a repeat
        keep = beatmap.keep_from_idx(words, left, dead=max_pause)
        quiet = silence.of_recording(work, name, cfg.get("folder", ""), ar["rel"], cache)
        tight = silence.cut_silences(keep, quiet, max_pause, pad, lead, words)
        if tight and sum(y - x for x, y in tight) >= 0.5 * sum(y - x for x, y in keep):
            keep = tight
        ar.update({"keep": keep, "in": keep[0][0], "out": keep[-1][1], "dur": round(sum(y - x for x, y in keep), 2), "span_in": keep[0][0], "span_out": keep[-1][1]})
        b["said"] = beatmap.kept_text(words, keep)
        b["dur"] = ar["dur"]
        kept_beats.append(b)
    data["beats"] = kept_beats
    beatmap.retime(data["beats"])
    clipmap.write_json(bp, data)
    clipmap.write_json(silence.path(work, name), cache)
    return done
