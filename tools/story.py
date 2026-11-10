"""The story in what was filmed (C2): which question the video answers, the strongest opening, the setback and payoff, the good moments nobody planned, and what is weak.

Claude is given every sentence of the cut (ids), the outline and the host's story rules (`youtube-edit/story.md`) and answers `story.json`:
  {"logline", "question", "answer_at": id, "opening": [{"ids", "why"}], "setback": {"ids", "why"}, "keep_moments": [{"ids", "kind", "why"}],
   "weak": [{"ids", "why"}], "order": [{"ids", "before", "why"}]}
`<name>.story.json` (a plan file) keeps the answer by the sentences' words, so it still applies to the next cut of the same recordings:
  {"v", "logline", "question", "answer_at": text, "opening": [{"texts", "why"}], "setback": {...}, "keep_moments": [{"texts", "kind", "why"}], "weak": [...], "order": [...]}
How it is used: the cold open run reads `opening`; the cut review never drops a `keep_moments` sentence; `weak` and `order` are shown as suggestions the host can add as a note (never done on their own).
"""
import json
from pathlib import Path

import beatmap
import clipmap
import config
import cutreview
import projectstore

WORK = config.WORK
VERSION = 1
KINDS = ("joke", "mistake", "reaction", "opinion", "result", "other")
MAX_KEEP, MAX_WEAK, MAX_ORDER = 12, 8, 4


def path(work: str, name: str) -> Path:
    return WORK / work / f"{name}.story.json"


def load(work: str, name: str) -> dict:
    return clipmap.read_json(path(work, name), {}) or {}


def held(work: str, name: str) -> set:
    """The sentences (by their normalised words) the story says to keep: the cut review never drops them."""
    return {t for k in load(work, name).get("keep_moments", []) for t in k.get("texts", [])}


def brief(work: str, name: str, fd: Path) -> str:
    import locks
    import outline
    import skillrules
    fd.mkdir(parents=True, exist_ok=True)
    data = json.loads(beatmap.path_of(work, name).read_text(encoding="utf-8-sig"))
    sents = cutreview.sentences(data, with_left_out=False, held=locks.texts(work, name))
    (fd / "cut.json").write_text(json.dumps(sents, indent=1, ensure_ascii=False), encoding="utf-8")
    model = outline.load(work, name)
    (fd / "outline.txt").write_text("\n".join(f"{s.get('title', '')}" for s in model.get("sections", [])) or "(no outline)", encoding="utf-8")
    got = skillrules.copy_into(fd, "story")
    return ("You are finding the story in what the host actually recorded, for their YouTube video. cut.json lists every sentence of the rough cut in order with an id; outline.txt is the planned order of sections. "
            + skillrules.read_first_line(got) + "story.md holds the rules for this job.\n"
            "Work out: the question the video answers and where it is answered; the strongest opening (a result, a failure or a claim; prefer one that can be SHOWN); the setback; the payoff; what is weak or repeated; "
            f"good unplanned moments (a joke, a mistake the host owns, a reaction, an honest opinion) the outline did not plan, at most {MAX_KEEP}. Change the order only when a first-time viewer would follow it better.\n"
            "Sentences marked locked are ones the host marked good: never list them as weak.\n"
            "Write story.json here:\n"
            '{"logline": "<one sentence>", "question": "<the question the video answers>", "answer_at": "<sentence id where it is answered>", '
            '"opening": [{"ids": ["B01.1"], "why": "<one plain sentence>"}], "setback": {"ids": ["B05.2"], "why": "..."}, '
            '"keep_moments": [{"ids": ["B07.3"], "kind": "joke|mistake|reaction|opinion|result|other", "why": "..."}], '
            '"weak": [{"ids": ["B09.1"], "why": "..."}], "order": [{"ids": ["B12.1", "B12.2"], "before": "B04.1", "why": "..."}]}\n'
            "Use only ids from cut.json. Write nowhere else.")


def apply_answer(work: str, name: str, p: Path) -> tuple[bool, str]:
    try:
        raw = json.loads(Path(p).read_text(encoding="utf-8-sig"))
        data = json.loads(beatmap.path_of(work, name).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return False, "Claude's answer could not be read."
    if not isinstance(raw, dict):
        return False, "Claude's answer could not be read."
    import locks
    locked = locks.texts(work, name)
    by_id = {s["id"]: s for s in cutreview.sentences(data, with_left_out=False)}

    def texts(ids):
        return [cutreview.norm(by_id[i]["text"]) for i in (ids if isinstance(ids, list) else []) if i in by_id]

    def words(ids):
        return " ".join(by_id[i]["text"] for i in (ids if isinstance(ids, list) else []) if i in by_id)[:300]

    def why(x):
        return str(x.get("why") or "")[:240] if isinstance(x, dict) else ""
    opening = [{"texts": texts(o.get("ids")), "said": words(o.get("ids")), "why": why(o)} for o in raw.get("opening") or [] if isinstance(o, dict) and texts(o.get("ids"))][:3]
    sb = raw.get("setback") if isinstance(raw.get("setback"), dict) else {}
    setback = {"texts": texts(sb.get("ids")), "said": words(sb.get("ids")), "why": why(sb)} if texts(sb.get("ids")) else {}
    keep = [{"texts": texts(k.get("ids")), "said": words(k.get("ids")), "kind": k.get("kind") if k.get("kind") in KINDS else "other", "why": why(k)}
            for k in raw.get("keep_moments") or [] if isinstance(k, dict) and texts(k.get("ids"))][:MAX_KEEP]
    keeping = {t for k in keep for t in k["texts"]}
    weak = [{"texts": texts(w.get("ids")), "said": words(w.get("ids")), "why": why(w)} for w in raw.get("weak") or []
            if isinstance(w, dict) and texts(w.get("ids")) and not (set(texts(w.get("ids"))) & (locked | keeping))][:MAX_WEAK]       # a locked or kept sentence is never weak
    order = [{"texts": texts(o.get("ids")), "said": words(o.get("ids")), "before": words([o.get("before")])[:120], "why": why(o)}
             for o in raw.get("order") or [] if isinstance(o, dict) and texts(o.get("ids")) and o.get("before") in by_id][:MAX_ORDER]
    ans = by_id.get(raw.get("answer_at"))
    out = {"v": VERSION, "logline": str(raw.get("logline") or "")[:300], "question": str(raw.get("question") or "")[:300], "answer_at": ans["text"][:200] if ans else "",
           "opening": opening, "setback": setback, "keep_moments": keep, "weak": weak, "order": order}
    projectstore.write_json(path(work, name), out)
    return True, f"Claude found the story: {len(keep)} moment{'' if len(keep) == 1 else 's'} to keep, {len(weak)} weak, {len(order)} to move."


def suggestions(work: str, name: str) -> list:
    """What the story says could be better, as notes the host can add in one click: [{"kind": "weak|order", "text": the note, "said": the words}]. Never done on their own."""
    s = load(work, name)
    out = [{"kind": "weak", "said": w["said"], "text": f"Take out or shorten: \"{w['said'][:120]}\" - {w['why']}"} for w in s.get("weak", [])]
    out += [{"kind": "order", "said": o["said"], "text": f"Move \"{o['said'][:100]}\" before \"{o['before'][:80]}\" - {o['why']}"} for o in s.get("order", [])]
    return out


def time_of(work: str, name: str, said: str) -> float:
    """Seconds into the cut where a sentence is said (the start of the beat that holds it); 0 when it is not found."""
    data = clipmap.read_json(beatmap.path_of(work, name), {"beats": []}) or {"beats": []}
    want = cutreview.norm(said)[:60]
    for b in data["beats"]:
        if want and want in cutreview.norm(b.get("said") or ""):
            return round(float(b.get("start", 0)), 1)
    return 0.0


def note_suggestions(work: str, name: str) -> list:
    """Everything the cut read and the story read think could be better, as notes the host can add in one click: [{"text", "t"}]. Nothing is done until the host adds one and asks for the next cut."""
    import cutreview as cr
    out = [{"text": s["text"], "t": time_of(work, name, s["said"])} for s in suggestions(work, name)]
    out += [{"text": f"Move \"{x['text'][:100]}\" before \"{x['before'][:80]}\" - {x['why']}", "t": time_of(work, name, x["text"])} for x in cr.load(work, name).get("suggestions", [])]
    return out


def opening_hint(work: str, name: str) -> str:
    """For the cold open run: the story's best opening, in words."""
    o = load(work, name).get("opening") or []
    return " | ".join(f"\"{x['said'][:200]}\" ({x['why']})" for x in o)


def outline_from_recordings(work: str, name: str, fd: Path) -> str:
    """The brief for an outline written from what was recorded, when the host has not written one: recordings.json holds the words of each recording."""
    import footage_cfg
    import outline
    cfg = clipmap.read_json(WORK / work / f"{name}.footage.json", {}) or {}
    rows = []
    for rel, an in sorted((cfg.get("analysis") or {}).items()):
        if footage_cfg.is_ignored(cfg, rel):
            continue
        text = " ".join(w[0] for w in an.get("list", []))
        if len(text.split()) >= 8:
            rows.append({"recording": rel, "words": len(text.split()), "text": text[:6000]})
    fd.mkdir(parents=True, exist_ok=True)
    (fd / "recordings.json").write_text(json.dumps(rows, indent=1, ensure_ascii=False), encoding="utf-8")
    note = ("There is no outline yet. recordings.json holds the words the host said in each recording. Write the outline of the video the host actually recorded: one section per recording "
            "or per natural part of one, in the order that tells the story best, each with its shot ideas and the host's own words as the suggested wording. Do not invent anything the host did not say.")
    return outline.brief(work, name, fd, note)
