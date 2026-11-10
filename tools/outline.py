"""The outline: read the host's outline format AND the old script format into one model, edit it line by line, and brief Claude for a draft.

Both live in `<name>.script.md` and are told apart by their shape.

The outline format (a sample is docs/outline-example.md):
    YouTube Video Script: ...                    (a document title, ignored)
    Packaging Lock-In / Title: ... / Thumbnail Concept: ...     the header
    🎬 Intro: The Benchmark Challenge            a section: an icon (any symbol) and a title
    1. Tinkercad                                 an entry inside a section (optional)
    Onscreen Data: Time: 20 Mins | Price: ...    data shown on screen
    [VISUAL: ...]                                a shot idea
    HOST (A-ROLL):  /  HOST:                       a talking point; the next line is the suggested wording
    HOST (VO):                                    a voice-over; the next line is the wording
    [GRAPHIC ON SCREEN: ...]                     a graphic
Old script format: `## SECTION (0:00 - 0:45)`, `S01 spoken line`, `[VISUAL: ...]`, `[NOTE: TP01 | ... VO (the host): "..."]`, header lines Logline/Thesis/Promise.

parse() returns {"format", "header": {field: {"text", "line"}}, "sections": [{"key", "title", "icon", "time", "line", "items": [item]}]}
with item = {"key", "type": visual|aroll|vo|teaching|graphic|data|entry|note, "text", "line", "end", "raw"}. `line` / `end` are 0-based rows of the
file (the wording of a talking point is rows line+1..end); `raw` is the first row as it was when parsed, so an edit can tell the file changed.
Line ids of the old format (S01) stay inside the file: the screen never shows them.
"""
import os
import re
import unicodedata
from pathlib import Path

import channel
import scriptedit
import skillrules

WPM = 170.0


def speaker_labels() -> str:
    """The names a speech line may start with when it has no (A-ROLL) / (VO) mark: HOST and the profile's host and co-host."""
    names = {"HOST", "THE HOST", *(n.upper() for n in channel.people())}
    return "|".join(re.escape(n) for n in sorted(names, key=len, reverse=True))


# `NAME (A-ROLL):` / `NAME (VO):` with any capitalised name, or a bare `HOST:` / the profile's name
SPEECH_RE = re.compile(rf"^(?:[A-Z][A-Z .'-]{{0,24}}\s*\((A-ROLL|VO)\)|(?:{speaker_labels()}))\s*:\s*$", re.I)
VISUAL_RE = re.compile(r"^\[(VISUAL)\s*:\s*(.*)$", re.I)
GRAPHIC_RE = re.compile(r"^\[(GRAPHIC(?: ON SCREEN)?)\s*:\s*(.*)$", re.I)
DATA_RE = re.compile(r"^(Onscreen Data)\s*:\s*(.*)$", re.I)
ENTRY_RE = re.compile(r"^(\d+)\.\s+(\S.*)$")
OLD_HEAD_RE = re.compile(r"^##\s+(.*?)\s*(?:\((\d+:\d{2}\s*[-–]\s*\d+:\d{2})\))?\s*$")
HEADER_RE = re.compile(r"^(Title|Thumbnail Concept|Logline|Thesis|Promise)(?: to the viewer)?(?:\s*\([^)]*\))?\s*:\s*(.*)$", re.I)
FIELD = {"title": "Title", "thumbnail concept": "Thumbnail Concept", "logline": "Logline", "thesis": "Thesis", "promise": "Promise"}
FIELD_KEY = {"title": "title", "thumbnail concept": "thumbnail", "logline": "logline", "thesis": "thesis", "promise": "promise"}
TP_RE = re.compile(r'^\[NOTE:\s*(TP\d{2})\s*\|(.*)\]\s*$')
TP_VO_RE = re.compile(r'VO \([^)]*\):\s*"(.*?)"\s*(?:\||$)', re.S)
QUOTES = "\"“”'"


def _is_section_heading(s: str) -> bool:
    """A new-format heading: an icon (a symbol character) then words, e.g. '🎬 Intro: The Benchmark Challenge'."""
    if len(s) < 3 or s[0].isascii() or not unicodedata.category(s[0]).startswith("S"):
        return False
    return " " in s and bool(s.split(None, 1)[1].strip())


def _split_icon(s: str) -> tuple[str, str]:
    icon, _, title = s.partition(" ")
    return icon.strip(), title.strip()


def detect(lines: list) -> str:
    for ln in lines:
        if OLD_HEAD_RE.match(ln.strip()) and ln.lstrip().startswith("##") or scriptedit.ID_RE.match(ln):
            return "script"
    return "outline"


def _bracket_end(lines: list, i: int) -> int:
    """Row where the [ ... ] that starts on row i ends (a shot idea may wrap)."""
    j = i
    while j < len(lines) and "]" not in lines[j]:
        j += 1
    return min(j, len(lines) - 1)


def _bracket_text(lines: list, i: int, j: int) -> str:
    s = " ".join(x.strip() for x in lines[i:j + 1])
    s = s.split(":", 1)[1] if ":" in s else s
    return s.rsplit("]", 1)[0].strip()


def unquote(s: str) -> str:
    s = s.strip()
    return s[1:-1].strip() if len(s) >= 2 and s[0] in QUOTES and s[-1] in QUOTES else s


def parse(text: str) -> dict:
    lines = text.splitlines()
    fmt = detect(lines)
    out = {"format": fmt, "header": {}, "sections": []}
    sec = None
    n = 0

    def add(kind, txt, a, b):
        nonlocal n
        n += 1
        sec["items"].append({"key": f"i{n}", "type": kind, "text": txt, "line": a, "end": b, "raw": lines[a]})

    i = 0
    while i < len(lines):
        raw = lines[i]
        s = raw.strip()
        if not s:
            i += 1
            continue
        if fmt == "script":
            m = OLD_HEAD_RE.match(s) if s.startswith("##") else None
            if m:
                sec = {"key": f"s{len(out['sections']) + 1}", "title": m.group(1).strip(), "icon": "", "time": m.group(2), "line": i, "items": []}
                out["sections"].append(sec)
                i += 1
                continue
        elif _is_section_heading(s):
            icon, title = _split_icon(s)
            sec = {"key": f"s{len(out['sections']) + 1}", "title": title, "icon": icon, "time": None, "line": i, "items": []}
            out["sections"].append(sec)
            i += 1
            continue
        if sec is None:                                             # the header: before the first section
            hm = HEADER_RE.match(s)
            if hm:
                key = FIELD_KEY[hm.group(1).lower()]
                out["header"].setdefault(key, {"text": hm.group(2).strip(), "line": i})
            elif fmt == "script" and s.startswith("# ") and "doc" not in out["header"]:
                out["header"]["doc"] = {"text": s[2:].strip(), "line": i}
            i += 1
            continue
        m = VISUAL_RE.match(s) or GRAPHIC_RE.match(s)
        if m:
            j = _bracket_end(lines, i)
            add("visual" if m.group(1).upper() == "VISUAL" else "graphic", _bracket_text(lines, i, j), i, j)
            i = j + 1
            continue
        m = DATA_RE.match(s)
        if m:
            add("data", m.group(2).strip(), i, i)
        elif ENTRY_RE.match(s) and fmt == "outline":
            add("entry", ENTRY_RE.match(s).group(2).strip(), i, i)
        elif fmt == "outline" and SPEECH_RE.match(s):
            kind = "vo" if (SPEECH_RE.match(s).group(1) or "").upper() == "VO" else "aroll"
            j = i
            while j + 1 < len(lines) and lines[j + 1].strip():
                j += 1
            add(kind, unquote(" ".join(x.strip() for x in lines[i + 1:j + 1])), i, j)
            i = j + 1
            continue
        elif scriptedit.ID_RE.match(raw):
            add("aroll", scriptedit.ID_RE.match(raw).group(4).strip(), i, i)
        elif TP_RE.match(s):
            vo = TP_VO_RE.search(TP_RE.match(s).group(2))
            add("teaching", (vo.group(1) if vo else TP_RE.match(s).group(2)).strip(), i, i)
        elif s.startswith("[NOTE"):
            add("note", s.strip("[]").split(":", 1)[-1].strip(), i, i)
        i += 1
    return out


def seconds(sec: dict) -> float:
    """Estimated spoken time of a section, from its talking points and voice-overs at 170 words a minute."""
    words = sum(len(re.sub(r"\[[^\]]*\]", " ", it["text"]).split()) for it in sec["items"] if it["type"] in ("aroll", "vo", "teaching"))
    return words / WPM * 60


def gaps(model: dict) -> int:
    """Sections that have words but no shot idea yet."""
    return sum(1 for s in model["sections"] if not any(it["type"] == "visual" for it in s["items"]))


CAMERA_RE = re.compile(r"\b(a-?roll|on camera|to camera|(?:user|the host) (?:appears|talking|on screen)|talking head|picture-in-picture)\b", re.I)


def is_camera(visual: str) -> bool:
    """A shot idea that is the host on camera ('Cut to A-Roll', 'close-up on camera'): the take of his words is the picture, nothing else is needed."""
    return bool(CAMERA_RE.search(visual))


def speech_lines(model: dict) -> list:
    """The spoken lines of the outline in order, each with the shot ideas that come before it: [{id, text, said, heading, kind, section, visuals}].
    A spoken line is a talking point or a voice-over (the host records both). The old script format keeps its own ids (S01); the outline format gets
    S01, S02... by order, which the clip matching (clipmap) and the beat map use. A shot idea belongs to the NEXT spoken line."""
    out, n = [], 0
    for sec in model["sections"]:
        pending = []
        for it in sec["items"]:
            if it["type"] == "visual":
                pending.append(it["text"])
            elif it["type"] in ("aroll", "vo", "teaching") and not (model["format"] == "script" and it["type"] == "teaching"):
                n += 1
                m = scriptedit.ID_RE.match(it["raw"]) if model["format"] == "script" else None
                said = re.sub(r"\[[^\]]*\]", " ", it["text"]).replace("*", "").replace(">", " ").strip()
                out.append({"id": m.group(2) if m else f"S{n:02d}", "text": it["text"], "said": said, "heading": sec["title"],
                            "kind": "vo" if it["type"] == "vo" else "aroll", "section": sec["key"], "visuals": pending})
                pending = []
        if pending and out and out[-1]["section"] == sec["key"]:           # shot ideas after the last line of a section (an outro card): they go with that line
            out[-1]["after"] = pending
    return out


def shot_key(section_title: str, visual: str) -> str:
    import hashlib
    return hashlib.sha1(f"{section_title}|{' '.join(visual.split()).lower()}".encode()).hexdigest()[:8]


def load(work: str, name: str) -> dict:
    p = scriptedit.script_path(work, name)
    return parse(p.read_text(encoding="utf-8-sig")) if p.exists() else {"format": "outline", "header": {}, "sections": []}


# ----------------------------------------------------------------------------- edits (every write is a saved version: scriptedit._write)
def _find(model: dict, line: int, raw: str | None):
    for s in model["sections"]:
        if s["line"] == line:
            return s, None
        for it in s["items"]:
            if it["line"] == line:
                if raw is not None and it["raw"] != raw:
                    raise ValueError("that line changed since you loaded the page: refresh and try again")
                return s, it
    raise ValueError("that line is not in the outline any more: refresh")


def _one_line(text: str) -> str:
    t = " ".join(str(text or "").split())
    if not t:
        raise ValueError("write something first")
    return t


def apply_op(work: str, name: str, op: str, b: dict) -> dict:
    p = scriptedit.script_path(work, name)
    if not p.exists():
        raise ValueError("there is no outline yet")
    lines = scriptedit._read_lines(p)
    model = parse("\n".join(lines))
    what = op
    if op == "set_header":
        field, text = b.get("field"), _one_line(b.get("text"))
        if field not in FIELD_KEY.values():
            raise ValueError("unknown field")
        label = next(k for k, v in FIELD_KEY.items() if v == field)
        cur = model["header"].get(field)
        if cur:
            if lines[cur["line"]] != b.get("raw", lines[cur["line"]]):
                raise ValueError("that line changed since you loaded the page: refresh and try again")
            head = lines[cur["line"]].split(":", 1)[0]
            lines[cur["line"]] = f"{head}: {text}"
        else:                                                         # a new header line goes just above the first section
            first = model["sections"][0]["line"] if model["sections"] else len(lines)
            at = first
            while at > 0 and not lines[at - 1].strip():
                at -= 1
            lines.insert(at, f"{FIELD[label]}: {text}")
        what = f"set {field}"
    elif op == "set_section":
        s, _ = _find(model, int(b["line"]), None)
        text = _one_line(b.get("text"))
        lines[s["line"]] = (f"{s['icon']} " if s["icon"] else "") + text if model["format"] == "outline" else f"## {text}" + (f" ({s['time']})" if s["time"] else "")
        what = "renamed a section"
    elif op == "set_item":
        s, it = _find(model, int(b["line"]), b.get("raw"))
        if not it:
            raise ValueError("that line is not in the outline any more: refresh")
        text = _one_line(b.get("text"))
        lines[it["line"]:it["end"] + 1] = _rewrite(model["format"], it, lines, text)
        what = f"edited {it['type']}"
    elif op == "delete_item":
        s, it = _find(model, int(b["line"]), b.get("raw"))
        if not it:
            raise ValueError("that line is not in the outline any more: refresh")
        del lines[it["line"]:it["end"] + 1]
        if it["line"] < len(lines) and not lines[it["line"]].strip() and it["line"] > 0 and not lines[it["line"] - 1].strip():
            del lines[it["line"]]
        what = f"removed {it['type']}"
    elif op == "add_visual":
        sec = next((x for x in model["sections"] if x["key"] == b.get("section")), None)
        if not sec:
            raise ValueError("that section is not in the outline any more: refresh")
        text = _one_line(b.get("text"))
        end = max([sec["line"]] + [it["end"] for it in sec["items"]])
        lines[end + 1:end + 1] = ["", f"[VISUAL: {text}]"]
        what = "added a shot idea"
    else:
        raise ValueError(f"unknown operation {op!r}")
    scriptedit._write(work, name, lines, what)
    return load(work, name)


def _rewrite(fmt: str, it: dict, lines: list, text: str) -> list:
    """The rows that replace item `it` when its text becomes `text`: the label and layout of the original are kept."""
    first = lines[it["line"]]
    kind = it["type"]
    if kind in ("visual", "graphic"):
        label = first.strip().split(":", 1)[0].lstrip("[")
        return [f"[{label}: {text}]"]
    if kind == "data":
        return [f"{first.split(':', 1)[0]}: {text}"]
    if kind == "entry":
        return [f"{ENTRY_RE.match(first.strip()).group(1)}. {text}"]
    if kind == "aroll" and fmt == "script":
        m = scriptedit.ID_RE.match(first)
        return [f"{m.group(1)}{m.group(2)}{m.group(3)}{text}"]
    if kind in ("aroll", "vo"):
        body = lines[it["line"] + 1] if it["end"] > it["line"] else ""
        quoted = body.strip()[:1] in QUOTES
        return [first, f'"{text}"' if quoted or not body else text]
    if kind == "teaching":
        m = TP_RE.match(first.strip())
        return [first.replace(TP_VO_RE.search(m.group(2)).group(1), text)] if m and TP_VO_RE.search(m.group(2)) else [first]
    return [f"[NOTE: {text}]"]


# ----------------------------------------------------------------------------- Claude: draft and revise
FORMAT = """Write the outline in the host's format, exactly like example.md:
- A first line "YouTube Video Script: <topic>", then a header block with "Title: ..." and "Thumbnail Concept: ...", then "Logline: ...", "Thesis: ..." and "Promise: ..." (one line each).
- Each section starts with {icon_rule} and a short title, e.g. "{example_heading}". Sections can hold numbered entries ("1. Item name") with an "Onscreen Data: ..." line.
- Each part of a section is: "[VISUAL: what is on screen]" then "HOST (A-ROLL):" (the host talking to camera) or "HOST (VO):" (voice-over) and, on the next line, the suggested wording in quotes. It is a loose guide: the host speaks in the host's own words.
- "[GRAPHIC ON SCREEN: ...]" where a graphic helps. Every section needs at least one [VISUAL] line. Explain a term a first-time viewer would not know once, in a voice-over.
- Put blank lines between parts. Write only the outline."""


def brief(work: str, name: str, fd: Path, note: str = "", icons: bool = True) -> str:
    """Write what Claude needs into fd and return the prompt; Claude answers in outline.md. With no outline yet this is a draft, otherwise a revision."""
    import shutil
    fd.mkdir(parents=True, exist_ok=True)
    example = Path(os.path.abspath(__file__)).parent.parent / "docs" / "outline-example.md"
    if example.exists():
        shutil.copyfile(example, fd / "example.md")
    found = skillrules.files("youtube-script")
    if found:                                                     # the channel's script knowledge: hooks, story shape, teaching points
        (fd / "skill").mkdir(exist_ok=True)
        for f in found[:8]:
            if f.stat().st_size < 60000:
                shutil.copyfile(f, fd / "skill" / f.name)
    cur = scriptedit.script_path(work, name)
    have = cur.exists() and cur.read_text(encoding="utf-8-sig").strip()
    if have:
        (fd / "current.md").write_text(cur.read_text(encoding="utf-8-sig"), encoding="utf-8")
    fmt = FORMAT.format(icon_rule="an emoji icon" if icons else "a plain title (no emoji)",
                        example_heading="🎬 Intro: The Benchmark Challenge" if icons else "Intro: The Benchmark Challenge")
    note = " ".join(str(note or "").split())[:800]
    task = (f"Revise the host's outline (current.md) for this change: {note or 'tighten it and fill any section that has no [VISUAL] line'}. Keep what the host did not ask to change."
            if have else f"Draft the outline for the host's next video: {note or 'a video idea the host has not written down yet; use the title of the video folder as the idea'}.")
    return (f"{task}\nThe folder skill/ has the host's script rules (read SKILL.md first); example.md is the host's format.\n{fmt}\nWrite outline.md in this folder and nowhere else.")


def apply_answer(work: str, name: str, p: Path) -> tuple[bool, str]:
    try:
        text = Path(p).read_text(encoding="utf-8-sig")
    except OSError:
        return False, "Claude's answer could not be read."
    m = parse(text)
    if len(m["sections"]) < 2 or not any(it["type"] in ("aroll", "vo") for s in m["sections"] for it in s["items"]):
        return False, "Claude's outline had no usable sections, so nothing was changed."
    path = scriptedit.script_path(work, name)
    scriptedit._write(work, name, text.rstrip("\n").splitlines(), "claude outline" if not path.exists() else "claude revised the outline")
    return True, f"Claude wrote an outline with {len(m['sections'])} sections."
