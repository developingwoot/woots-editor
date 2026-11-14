"""What the starter skills have that the user's own copy of a skill does not have yet, and adding it.

The user's copy of a skill file (`~/.claude/skills/...`) is used instead of the starter file of the same name (skillrules.py). So a rule or a number added to the
starter set never reaches a user who has their own copy: the program falls back to the built-in number, but the file does not show it, and Claude runs (which are
given the user's copy) never read the rule. This module finds that and adds it, changing nothing else in the user's file:

  numbers  a key of a starter numbers file (rough-cut.json, publish.json, graphics.json, shorts.json) that the user's copy of that file lacks.
  rules    an entry of `skills/updates.json` ({id, date, file, section, text, about}) whose text is not in the user's copy of `file`. Every rule added to a
           starter skill file after its first version gets an entry there, with the same words as in the starter file (a test checks that).

A file the user has no copy of needs nothing (the starter file is used). `apply()` keeps the file as it was in `<file>.bak` before the first change.
"""
import json
import shutil

import skillrules

NUMBER_FILES = (skillrules.RULES_FILE, skillrules.PUBLISH_FILE, skillrules.GRAPHICS_FILE, skillrules.SHORTS_FILE)
UPDATES = "updates.json"
ADDED = "## Added by the app"


def _json(p):
    try:
        got = json.loads(p.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None
    return got if isinstance(got, dict) else None


def _flat(text: str) -> str:
    return " ".join(text.split()).lower()


def updates() -> list:
    try:
        got = json.loads((skillrules.STARTER / UPDATES).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return []
    return [u for u in got if isinstance(u, dict) and u.get("file") and u.get("text")] if isinstance(got, list) else []


def missing_numbers() -> list:
    """[{file, key, value}]: numbers of the starter files that the user's own copy lacks. A copy that cannot be read is left alone."""
    out = []
    for rel in NUMBER_FILES:
        mine, starter = _json(skillrules.SKILLS / rel), _json(skillrules.STARTER / rel)
        if mine is None or starter is None:
            continue
        out += [{"file": rel, "key": k, "value": v} for k, v in starter.items() if k not in mine]
    return out


def missing_rules() -> list:
    """The entries of updates.json whose words are not in the user's own copy of the file they belong to."""
    out, texts = [], {}
    for u in updates():
        p = skillrules.SKILLS / u["file"]
        if not p.is_file():
            continue
        if u["file"] not in texts:
            try:
                texts[u["file"]] = _flat(p.read_text(encoding="utf-8-sig"))
            except OSError:
                continue
        if _flat(u["text"]) not in texts[u["file"]]:
            out.append(u)
    return out


def pending() -> dict:
    """What the Settings and home screens show: the rules and numbers the user's copy lacks, in plain words."""
    rules, nums = missing_rules(), missing_numbers()
    return {"count": len(rules) + len(nums),
            "rules": [{"file": u["file"], "about": u.get("about") or u["text"][:80], "text": u["text"]} for u in rules],
            "numbers": [{"file": n["file"], "key": n["key"], "value": n["value"]} for n in nums]}


def add_rule(text: str, section: str, rule: str) -> str:
    """`text` (a skill file) with `rule` as the last bullet of the section whose heading starts with `section`; a file without that section gets it under ADDED."""
    lines = text.rstrip("\n").split("\n")
    want = _flat(section) if section else ""
    start = next((i for i, ln in enumerate(lines) if want and ln.startswith("## ") and _flat(ln[3:]).startswith(want)), None)
    if start is None:
        start = next((i for i, ln in enumerate(lines) if ln.strip() == ADDED), None)
        if start is None:
            return "\n".join(lines + ["", ADDED, f"- {rule}"]) + "\n"
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
    while end > start + 1 and not lines[end - 1].strip():
        end -= 1
    lines[end:end] = [f"- {rule}"]
    return "\n".join(lines) + "\n"


def _backup(p):
    bak = p.with_name(p.name + ".bak")
    if not bak.exists():
        shutil.copyfile(p, bak)


def apply() -> dict:
    """Add every missing rule and number to the user's own copies. Nothing already there is changed. Returns {rules, numbers, files}."""
    rules, nums = missing_rules(), missing_numbers()
    touched = []
    for rel in sorted({n["file"] for n in nums}):
        p = skillrules.SKILLS / rel
        mine = _json(p)
        if mine is None:
            continue
        _backup(p)
        mine.update({n["key"]: n["value"] for n in nums if n["file"] == rel})
        p.write_text(json.dumps(mine, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        touched.append(rel)
    for rel in sorted({u["file"] for u in rules}):
        p = skillrules.SKILLS / rel
        _backup(p)
        text = p.read_text(encoding="utf-8-sig")
        for u in rules:
            if u["file"] == rel:
                text = add_rule(text, u.get("section", ""), u["text"])
        p.write_text(text, encoding="utf-8")
        touched.append(rel)
    return {"rules": len(rules), "numbers": len(nums), "files": touched}
