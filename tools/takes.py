"""Takes of the same line (the host 2026-10-29): he records a passage several times, often inside one long recording ("the first thing that jumped out at me was screen real
estate" at 1:03 and again at 2:26), and the rough cut played both. This finds the passages said more than once, keeps the best take of each and remembers the others as options.

Claude is given every sentence of the cut in order (cut.json) plus the pairs of passages that share many of the same rare words (`candidates`, a hint, not a verdict) and groups the
takes. `<name>.takes.json` (a plan file): {"v", "groups": [{"topic", "why", "best": index, "takes": [{"ids"?, "texts": [sentence text]}], "keep": [text of a sentence of another take that is
kept anyway, because only that take says it]}]}. A sentence is named by its words, so the file still applies to the next cut of the same recordings. `drops` gives the sentences
of the takes that are not the best; cutreview.apply takes them out.
"""
import json
import math
import re
from collections import Counter
from pathlib import Path

import beatmap
import clipmap
import config
import cutreview
import projectstore
import skillrules

WORK = config.WORK
VERSION = 2                               # 2: use (a splice of takes), left-out sentences are read too
MAX_SHARE_DROPPED = 0.35                      # a cut never loses more than this share of its sentences to other takes
STOP = set("""about above after again also always another been before being both could does doing done each even every from have having here into just kind like made make many more most much
only other over really right same should some something still such than that their them then there these they thing think this those through very want were what when where which while will with would your
you're don't it's that's i'm i've i'll there's""".split())


def path(work: str, name: str) -> Path:
    return WORK / work / f"{name}.takes.json"


def load(work: str, name: str) -> dict:
    return clipmap.read_json(path(work, name), {}) or {}


def content_words(text: str) -> list:
    """The words that say what a sentence is about: 4 letters or more, no filler, a trailing s dropped ("columns" = "column")."""
    out = []
    for w in re.findall(r"[a-z0-9']+", text.lower()):
        if len(w) >= 4 and w not in STOP:
            out.append(w[:-1] if w.endswith("s") and not w.endswith("ss") else w)
    return out


def candidates(sents: list, size: int = 3, min_score: float = 0.3, min_gap: int = 3) -> list:
    """Pairs of passages (windows of `size` sentences) that use many of the same words, rarer words counting more: [{"a": [first id, last id], "b": [...], "score"}], best first, at most one per
    window. A hint for Claude: paraphrased takes share only some words, so the score is low and Claude decides."""
    n = len(sents)
    if n < size + min_gap:
        return []
    docs = [Counter(content_words(s["text"])) for s in sents]
    df = Counter(w for d in docs for w in d)
    idf = {w: math.log((n + 1) / (c + 0.5)) for w, c in df.items()}
    wins = []
    for i in range(n - size + 1):
        c = Counter()
        for d in docs[i:i + size]:
            c.update(d)
        v = {w: (1 + math.log(k)) * idf[w] for w, k in c.items()}
        wins.append((v, math.sqrt(sum(x * x for x in v.values())) or 1.0))
    best = {}
    for i in range(len(wins)):
        for j in range(i + min_gap, len(wins)):
            (a, na), (b, nb) = wins[i], wins[j]
            s = sum(x * b[w] for w, x in a.items() if w in b) / (na * nb)
            if s >= min_score and s > best.get(i, (0, 0))[0]:
                best[i] = (s, j)
    out, used = [], set()
    for i, (s, j) in sorted(best.items(), key=lambda kv: -kv[1][0]):
        if i in used or j in used:
            continue
        used.update(range(i, i + size))
        used.update(range(j, j + size))
        out.append({"a": [sents[i]["id"], sents[i + size - 1]["id"]], "b": [sents[j]["id"], sents[j + size - 1]["id"]], "score": round(s, 2)})
    return out[:12]


def brief(work: str, name: str, fd: Path) -> str:
    fd.mkdir(parents=True, exist_ok=True)
    data = json.loads(beatmap.path_of(work, name).read_text(encoding="utf-8-sig"))
    import locks
    sents = cutreview.sentences(data, with_left_out=True, held=locks.texts(work, name))
    (fd / "cut.json").write_text(json.dumps(sents, indent=1), encoding="utf-8")
    hints = candidates([s for s in sents if not s.get("left_out")])
    got = skillrules.copy_into(fd)
    smin = skillrules.rules()["splice_min_words"]
    return ("You are looking at the rough cut of the host's YouTube video for passages the host says MORE THAN ONCE. The host records a passage several times (often one after another inside one long recording, "
            "after a restart) and the cut then plays the same point twice, in the same or other words. cut.json lists every sentence of the recordings in order: id, recording, `at` (seconds into that recording), "
            "length and words. Sentences marked left_out (ids like B08.L1) are in the recording but the cut does not play them; they can be another take of the same line. " + skillrules.read_first_line(got) +
            "Find the groups: one topic, said in two or more takes. A take is a run of consecutive sentence ids (a few sentences to a whole section), left_out ones included. "
            "Two takes are the same line when they make the same point (the first thing that jumped out at me was screen real estate; four columns instead of three; it clips long text). A topic that comes back "
            "later on purpose (a summary, a callback, the verdict) is not a take: leave it alone.\n"
            "Usually the LAST take is the one the host thought best, the one with the most complete thought (the cut skill says so; follow it if it says otherwise). Choose `best`, the index of the main take: the last one, unless it stops short "
            "(no verdict, no example, a thought left hanging) or is clearly worse (stumbles, the wrong word); then the earlier one. Sometimes the best result takes a portion from each take: list in `use` the "
            f"sentence ids to play, in the order they play, from the best take and, only where it lacks something (a number, the reason, a clean ending, a joke), a run from another take. A run taken from another "
            f"take must be at least {smin} words long, so the video never cuts every word; join runs where both takes say the same words if you can. Leave `use` out to play the whole best take.\n"
            + ("Passages that share many rare words (a hint, not an answer; ids are first and last sentence of each passage): " + json.dumps(hints) + "\n" if hints else "")
            + ("Sentences marked locked are ones the host marked good: they keep playing exactly as they are; never choose another take over a locked sentence and never leave one out.\n" if any(x.get("locked") for x in sents) else "")
            + "Write takes.json here:\n"
            '{"groups": [{"topic": "<a few words>", "takes": [["B03.1", "B03.2", "B04.1"], ["B06.1", "B06.2", "B07.1"]], "best": 1, "use": ["B06.1", "B06.2", "B03.2", "B07.1"], "why": "<one plain sentence>"}]}\n'
            "Use only ids from cut.json; the sentences of one take are consecutive; takes of a group do not overlap. Write nowhere else.")


def _runs(positions: list) -> list:
    """Sorted positions split into runs of consecutive numbers."""
    out = []
    for k in positions:
        if out and k == out[-1][-1] + 1:
            out[-1].append(k)
        else:
            out.append([k])
    return out


def apply_review(work: str, name: str, p: Path) -> tuple[bool, str]:
    try:
        raw = json.loads(Path(p).read_text(encoding="utf-8-sig"))
        data = json.loads(beatmap.path_of(work, name).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return False, "Claude's answer could not be read."
    sents = cutreview.sentences(data, with_left_out=True)
    pos = {s["id"]: k for k, s in enumerate(sents)}
    smin = skillrules.rules()["splice_min_words"]
    used, groups = set(), []
    for g in raw.get("groups", []) if isinstance(raw, dict) else []:
        if not isinstance(g, dict) or not isinstance(g.get("takes"), list):
            continue
        takes = []
        for t in g["takes"]:
            ids = [i for i in t if isinstance(t, list) and i in pos] if isinstance(t, list) else []
            ks = sorted(pos[i] for i in ids)
            if ks and ks == list(range(ks[0], ks[0] + len(ks))) and len(ks) <= 40 and not used & set(ks):
                takes.append(ks)
        if len(takes) < 2:
            continue
        for ks in takes:
            used.update(ks)
        best = g.get("best")
        best = best if isinstance(best, int) and 0 <= best < len(g["takes"]) else len(takes) - 1
        best = min(best, len(takes) - 1)
        in_takes = {k for ks in takes for k in ks}
        wanted = sorted({pos[i] for i in g["use"] if i in pos and pos[i] in in_takes}) if isinstance(g.get("use"), list) else []
        wanted = wanted or list(takes[best])
        use = []
        for run in _runs(wanted):
            if set(run) <= set(takes[best]) or sum(len(sents[k]["text"].split()) for k in run) >= smin:         # a run taken from another take is at least splice_min_words long
                use += run
        use = use or list(takes[best])
        groups.append({"topic": str(g.get("topic") or "")[:80], "why": str(g.get("why") or "")[:240], "best": best,
                       "use": [sents[k]["text"] for k in sorted(use)],
                       "takes": [{"texts": [sents[k]["text"] for k in ks], "seconds": round(sum(sents[k]["seconds"] for k in ks), 1)} for ks in takes]})
    n_cut = max(1, len([s for s in sents if not s.get("left_out")]))

    def lost(g):
        u = {cutreview.norm(t) for t in g["use"]}
        return sum(1 for t in g["takes"] for x in t["texts"] if cutreview.norm(x) not in u)
    while groups and sum(lost(g) for g in groups) > MAX_SHARE_DROPPED * n_cut:         # Claude found too much: keep the groups it listed first
        groups.pop()
    projectstore.write_json(path(work, name), {"v": VERSION, "groups": groups})
    n = sum(len(g["takes"]) - 1 for g in groups)
    return True, f"Claude found {len(groups)} passage{'' if len(groups) == 1 else 's'} said more than once ({n} other take{'' if n == 1 else 's'})."


def used_texts(g: dict) -> list:
    return g.get("use") or g["takes"][g["best"]]["texts"] + g.get("keep", [])


def drops(work: str, name: str) -> list:
    """[{text, kind, why}] for every sentence of a take that the group does not use."""
    out = []
    for g in load(work, name).get("groups", []):
        use = {cutreview.norm(t) for t in used_texts(g)}
        for t in g["takes"]:
            for text in t["texts"]:
                if cutreview.norm(text) not in use:
                    out.append({"text": text, "kind": "other-take", "why": f"another take of \"{g['topic']}\" is used" + (f": {g['why']}" if g.get("why") else "")})
    return out


def restores(work: str, name: str) -> list:
    """[{text}] for every sentence the groups use: one the cut does not play yet (a left-out sentence of the recording) is brought back."""
    return [{"text": t} for g in load(work, name).get("groups", []) for t in used_texts(g)]


def options(work: str, name: str) -> list:
    """For the review: [{topic, best, takes: [{text (first words), seconds}]}] of the passages with other takes to choose from."""
    return [{"topic": g["topic"], "best": g["best"], "takes": [{"text": " ".join(t["texts"])[:140], "seconds": t["seconds"]} for t in g["takes"]]} for g in load(work, name).get("groups", [])]


def choose(work: str, name: str, group: int, take: int) -> dict:
    d = load(work, name)
    if not 0 <= group < len(d.get("groups", [])) or not 0 <= take < len(d["groups"][group]["takes"]):
        raise ValueError("that take is not one of the choices")
    d["groups"][group]["best"] = take
    d["groups"][group]["use"] = list(d["groups"][group]["takes"][take]["texts"])
    d["groups"][group]["by"] = "user"
    projectstore.write_json(path(work, name), d)
    return d
