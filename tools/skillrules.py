"""The numbers and notes the rough cut takes from the youtube-edit skill (ADR 0009).

`youtube-edit/rough-cut.json` holds the numbers, `rough-cut.md` the rules and lessons. The app reads them every time it makes a cut, so a change to the skill
changes the next cut; a missing or broken file falls back to DEFAULTS. Background Claude runs get copies of the skill files they should follow.
Override the folder with WOOTS_SKILLS_DIR (tests). Two places hold the skills: the user's own (`~/.claude/skills`) and the starter set that ships with the app (`skills/` in the repo).
A file in the user's folder is used instead of the starter file of the same name; a file only the starter set has is used as it is.
"""
import json
import os
import shutil
from pathlib import Path

SKILLS = Path(os.environ.get("WOOTS_SKILLS_DIR") or (Path.home() / ".claude" / "skills"))
STARTER = Path(os.path.dirname(os.path.abspath(__file__))).parent / "skills"           # the starter skills in the repo


def find(rel: str):
    """The file `skill/name.md`: the user's copy if they have one, else the starter copy, else None."""
    for root in (SKILLS, STARTER):
        if (root / rel).is_file():
            return root / rel
    return None


def files(skill: str, pattern: str = "*.md") -> list:
    """The files of one skill, user copies replacing starter copies of the same name, sorted by name."""
    got = {}
    for root in (STARTER, SKILLS):
        got.update({f.name: f for f in (root / skill).glob(pattern) if f.is_file()})
    return [got[k] for k in sorted(got)]
DEFAULTS = {"min_piece_s": 3.0, "beat_min_s": 15.0, "beat_max_s": 30.0, "repeat_phrase_words": 4, "repeat_phrase_within_words": 40,
            "repeat_phrase_within_s": 20.0, "repeat_sentence_share": 0.5, "repeat_sentence_far_share": 0.7, "repeat_sentence_s": 60.0, "cold_open_after_s": 120.0,
            "cold_open_min_s": 6.0, "cold_open_max_s": 15.0, "broll_max_s": 8.0, "max_pause_s": 0.5, "broll_min_beat_s": 12.0, "retake_share": 0.6, "splice_min_words": 4, "punch_in_zoom": 1.3, "punch_hold_s": 15.0, "punch_flat_s": 30.0, "hook_total_s": 30.0, "min_words": 60, "min_words_per_s": 0.8}
SHORTS_DEFAULTS = {"min_s": 10.0, "favour_s": 60.0, "max_s": 180.0, "minutes_per_short": 3.5, "hard_cap": 8, "strong": 3.0, "setup_s": 8.0, "payoff_s": 8.0,
                   "max_moment_s": 90.0, "caption_max_words": 3, "caption_max_chars": 17, "hook_s": 2.8,
                   "moment_min_s": 20.0, "moment_max_s": 55.0, "moment_min_score": 3.0, "soft_below_px": 1080, "broll_similarity": 0.5,
                   "raw_min_words": 20, "raw_min_words_per_s": 0.8, "raw_max_shorts": 3, "overlay_lead_s": 0.15, "overlay_min_s": 1.0, "overlay_max_s": 4.0,
                   "caption_style": "pop", "emphasis_gap_s": 3.0, "safe_top_px": 1050, "safe_bottom_px": 380, "safe_right_px": 150, "sfx_gap_s": 0.4,
                   "sfx_max_per_10s": 6, "sfx_cut_lead_s": 0.08, "music_below_speech_db": 26, "duck_db": 9}
RULES_FILE = "youtube-edit/rough-cut.json"
SHORTS_FILE = "youtube-shorts/shorts.json"
FOR_CLAUDE = ("youtube-edit/rough-cut.md", "youtube-edit/editing-style.md", "youtube-edit/cut-rules.md", "youtube-script/hook-library.md")


def numbers(rel: str, defaults: dict) -> dict:
    """The numbers in one skill file: `defaults`, each replaced by the file's value when that is a positive number (a word, where the default is a word)."""
    out = dict(defaults)
    try:
        got = json.loads((find(rel) or Path("missing")).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return out
    for k, v in (got.items() if isinstance(got, dict) else []):
        if k in defaults and isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0 and not isinstance(defaults[k], str):
            out[k] = type(defaults[k])(v)
        elif k in defaults and isinstance(defaults[k], str) and isinstance(v, str) and v.strip():
            out[k] = v.strip()
    return out


def rules() -> dict:
    return numbers(RULES_FILE, DEFAULTS)


def shorts() -> dict:
    """The numbers for shorts (youtube-shorts/shorts.json): lengths, how many, how strong a moment must be, caption size, hook time."""
    return numbers(SHORTS_FILE, SHORTS_DEFAULTS)


def shorts_notes() -> str:
    """The prose rules for choosing shorts (youtube-shorts/shorts.md), with the numbers filled in."""
    p = find("youtube-shorts/shorts.md")
    try:
        text = p.read_text(encoding="utf-8-sig") if p else ""
    except OSError:
        text = ""
    text = "\n".join(line for line in text.splitlines() if not line.startswith("#")).strip() or "- Each short is a complete thought of {min_s} to {max_s} seconds."
    r = shorts()
    for k in ("min_s", "max_s", "hook_s"):
        text = text.replace("{" + k + "}", f"{r[k]:g}")
    return text


def copy_into(fd: Path, rels=FOR_CLAUDE) -> list:
    """Copy the skill files a Claude run should read into its folder; returns the file names that were there."""
    fd.mkdir(parents=True, exist_ok=True)
    got = []
    for rel in rels:
        src = find(rel)
        if src:
            shutil.copyfile(src, fd / src.name)
            got.append(src.name)
    return got


def read_first_line(names: list) -> str:
    return ("Read " + ", ".join(names) + " first: they hold the rules the host has set for his cuts and his hook patterns. " if names else "")
