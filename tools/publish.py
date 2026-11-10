"""Publishing details for the Final step (ADR 0007): title options with one chosen, the description, tags, thumbnail prompts and text.

`<name>.publish.json` (a plan file, written through projectstore):
  {"titles": [..], "title": "the chosen one", "description": "...", "tags": [..], "thumbnail_prompts": [..], "thumbnail_text": [..],
   "thumb": {"t": 12.0, "text": "THE WORST DESIGN"}}
Claude writes the titles, the hook and summary, the credits it can find in the script, the tags and the thumbnail prompts (it does not generate
images). The chapters are never Claude's: they come from the final render's cuts (finalrender.chapters) and are put into the description by code.
"""
import json
import time
from pathlib import Path

import channel
import config
import projectstore
import skillrules

WORK = config.WORK
MAX_TITLE, MAX_TAG, MAX_TAGS_TOTAL = 100, 30, 450
FIELDS = ("description", "tags", "thumbnail_prompts", "thumbnail_text", "thumb")


def path(work: str, name: str) -> Path:
    return WORK / work / f"{name}.publish.json"


def load(work: str, name: str) -> dict:
    base = {"titles": [], "title": "", "description": "", "tags": [], "thumbnail_prompts": [], "thumbnail_text": [], "thumb": {}, "title_why": {}, "pinned_comment": ""}
    try:
        base.update(json.loads(path(work, name).read_text(encoding="utf-8-sig")))
    except (OSError, ValueError):
        pass
    return base


def save(work: str, name: str, d: dict):
    d["updated"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    projectstore.write_json(path(work, name), d)


def _clean(s, limit: int) -> str:
    return " ".join(str(s or "").split())[:limit]


def set_title(work: str, name: str, title: str) -> dict:
    title = _clean(title, MAX_TITLE)
    if len(title) < 3:
        raise ValueError("give the video a title of at least 3 letters")
    d = load(work, name)
    d["title"] = title
    if title not in d["titles"]:
        d["titles"].append(title)
    save(work, name, d)
    return d


def set_field(work: str, name: str, field: str, value) -> dict:
    if field not in FIELDS:
        raise ValueError("unknown field")
    d = load(work, name)
    if field == "description":
        d[field] = str(value or "").strip()[:5000]
    elif field == "tags":
        d[field] = clean_tags(value if isinstance(value, list) else str(value or "").split(","))
    elif field == "thumb":
        t = value or {}
        d[field] = {"t": round(max(0.0, float(t.get("t", 0))), 1), "text": _clean(t.get("text"), 60)}
    else:
        d[field] = [_clean(x, 300) for x in (value if isinstance(value, list) else str(value or "").split("\n")) if _clean(x, 300)][:5]
    save(work, name, d)
    return d


def clean_tags(tags: list, limit: int | None = None) -> list:
    out, total = [], 0
    for t in tags:
        t = _clean(t, MAX_TAG).strip("#")
        if t and t.lower() not in (x.lower() for x in out) and total + len(t) + 1 <= MAX_TAGS_TOTAL:
            out.append(t)
            total += len(t) + 1
    return out[:limit or 15]


def chapter_lines(work: str, name: str) -> list:
    """['0:00 Intro', ...] from the final render's cuts; empty when there are fewer than 3 chapters or no stitched video yet."""
    try:
        import finalrender
        import views
        return [f"{views.time_text(t)} {title}" for t, title in finalrender.chapters(work, name)]
    except Exception:                       # noqa: BLE001  (no stitched preview yet: the description simply has no chapters)
        return []


def build_description(hook: str, summary: str, chapters: list, credits: list) -> str:
    parts = [_clean(hook, 300), _clean(summary, 1200)]
    if chapters:
        parts.append("Chapters\n" + "\n".join(chapters))
    cs = [_clean(c, 200) for c in credits if _clean(c, 200)]
    if cs:
        parts.append("Credits\n" + "\n".join(cs))
    return "\n\n".join(p for p in parts if p)


def said_lines(work: str, name: str) -> list:
    """What is said in the newest cut or final, sentence by sentence with its time, from the beat map."""
    try:
        bm = json.loads((WORK / work / f"{name}.beatmap.json").read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return []
    return [{"t": round(float(b.get("start", 0)), 1), "said": _clean(b.get("said"), 400)} for b in bm.get("beats", []) if not b.get("skip") and _clean(b.get("said"), 400)]


def brief(work: str, name: str, fd: Path, note: str = "") -> str:
    """Write what Claude needs into fd and return the prompt. Claude answers in publish.json (its own name: the notes job answers in answer.json)."""
    fd.mkdir(parents=True, exist_ok=True)
    try:
        script = (WORK / work / f"{name}.script.md").read_text(encoding="utf-8-sig")
    except OSError:
        script = ""
    (fd / "script.md").write_text(script[:20000], encoding="utf-8")
    (fd / "said.json").write_text(json.dumps(said_lines(work, name), indent=1, ensure_ascii=False), encoding="utf-8")
    (fd / "current.json").write_text(json.dumps(load(work, name), indent=1), encoding="utf-8")
    skillrules.copy_into(fd, "publish")
    n = skillrules.publish()
    redo = f"\nThe host asks for this change: {_clean(note, 600)}\n" if _clean(note, 600) else ""
    return (
        "script.md is the outline of the host's YouTube video. said.json is what is actually said in the finished video, with times: the title, the hook and the tags must be true of THIS video, not only of the outline. "
        "SKILL.md, metadata.md and hook-library.md hold the host's rules: read them first. current.json is what has been written so far (may be empty).\n"
        f"{redo}"
        "Write publish.json in this folder:\n"
        '{"titles": [{"title": "under ' + str(n["title_max_chars"]) + ' characters, plain words a viewer would search for, no clickbait lies", '
        '"why": "the promise this title makes, in one sentence: the first 30 seconds must keep it", '
        '"thumb_text": "1 to ' + str(n["thumb_words_max"]) + ' words for the thumbnail that ADD to the title instead of repeating it, all caps"}, "... ' + str(n["titles"]) + ' options"],\n'
        ' "hook": "the first line of the description: the viewer-first line, with the keywords, under ' + str(n["hook_max_chars"]) + ' characters",\n'
        ' "summary": "two or three plain sentences about what the video shows",\n'
        ' "credits": ["Name - video title - link, ONLY for creators the script names; never invent a person or a link"],\n'
        ' "tags": ["up to ' + str(n["tags_max"]) + ' specific search phrases, not single generic words"],\n'
        ' "pinned_comment": "one question for the viewers that invites a real answer",\n'
        ' "thumbnail_prompts": ["2 or 3 prompts for an image tool: real photos of the host' + channel.thumbnail_style() + ', legible at 168x94"]}\n'
        "No placeholders such as @YourChannel or [FILL]. Do not write chapters (the app adds them). Write nowhere else.")


def apply_answer(work: str, name: str, p: Path) -> tuple[bool, str]:
    try:
        a = json.loads(Path(p).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return False, "Claude's answer could not be read."
    if not isinstance(a, dict):
        return False, "Claude's answer could not be read."
    n = skillrules.publish()
    titles, why, thumbs = [], {}, []
    for x in a.get("titles") or []:                                    # a plain string or {title, why, thumb_text}
        t = _clean(x.get("title") if isinstance(x, dict) else x, MAX_TITLE)
        if len(t) < 3 or len(t) > n["title_max_chars"] or t.lower() in (y.lower() for y in titles):
            continue                                                   # over the skill's limit: dropped, never cut in the middle of a word
        titles.append(t)
        if isinstance(x, dict):
            if _clean(x.get("why"), 300):
                why[t] = _clean(x.get("why"), 300)
            tt = " ".join(_clean(x.get("thumb_text"), 60).upper().split()[:n["thumb_words_max"]])
            if tt and tt not in thumbs:
                thumbs.append(tt)
    titles = titles[:n["titles"]]
    if not titles:
        return False, f"Claude gave no title options that fit the {n['title_max_chars']}-character limit."
    d = load(work, name)
    d["titles"] = titles
    if d["title"] and d["title"] not in titles:
        d["titles"].append(d["title"])                     # a title the creator chose or typed is never thrown away
    d["title_why"] = {t: w for t, w in why.items() if t in titles}
    d["description"] = build_description(_clean(a.get("hook"), n["hook_max_chars"]), a.get("summary"), chapter_lines(work, name), [str(c) for c in a.get("credits") or []])
    d["tags"] = clean_tags([str(t) for t in a.get("tags") or []], n["tags_max"])
    d["pinned_comment"] = _clean(a.get("pinned_comment"), 300)
    d["thumbnail_prompts"] = [x for x in (_clean(x, 400) for x in a.get("thumbnail_prompts") or []) if x][:3]
    more = [" ".join(_clean(x, 40).upper().split()[:n["thumb_words_max"]]) for x in a.get("thumbnail_text") or []]
    d["thumbnail_text"] = [x for x in dict.fromkeys(thumbs + [m for m in more if m])][:3]
    save(work, name, d)
    return True, f"Claude wrote {len(titles)} title options, the description, {len(d['tags'])} tags and {len(d['thumbnail_prompts'])} thumbnail prompts."
