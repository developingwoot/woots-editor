"""The channel profile: who makes the videos, so the prompts Claude gets say "Sam" and "Sam's Workshop", not a name written into the code.

Saved per user next to the settings file (`profile.json`; override with WOOTS_PROFILE_FILE). Every field is optional; a missing one reads as a neutral default
("the host", "the channel"), so the app works before a profile is filled in. Prompts are written with the original author's words and passed through `apply`
on their way to Claude, which swaps in this profile's name, channel, topic, and co-host.
"""
import json
import os
import re
import tempfile
from pathlib import Path

import config

FIELDS = {
    "name": ("the host", "The name the presenter goes by in the videos."),
    "channel": ("the channel", "The channel's name."),
    "topic": ("a YouTube channel", "What the channel is about, as a phrase: \"a 3D printing channel\"."),
    "cohost": ("", "A second voice that appears in the videos (blank if none)."),
    "subjects": ("", "What your footage usually shows, so the footage describer uses the right names (for example: 3D printed parts, a printer, calipers, a CAD program on a screen)."),
    "audience": ("", "Who watches, in a sentence."),
    "voice": ("", "How the host sounds and writes: tone, habits, words to avoid."),
    "terms": ("", "Names and words speech recognition gets wrong, one per line: heard => right (for example: clipper => Klipper). A word followed by * matches any ending. A line with only a word is a spelling to keep."),
    "headline_font": ("", "The font for big titles, as it is named on your computer (for example Oswald Bold)."),
    "label_font": ("", "The font for small labels."),
    "colors": ("", "Your brand colours, name and hex code, one per line or separated by commas (for example: navy #142C44, orange #E2703A)."),
    "tone": ("", "How the videos feel (for example: plain, curious, a little dry)."),
    "always": ("", "Things every video does (for example: show the result before the explanation)."),
    "never": ("", "Things no video does (for example: no clickbait numbers)."),
}
STYLE_KEYS = ("headline_font", "label_font", "colors", "tone", "always", "never")     # these go into the brand and house-style files, not into every prompt
NL = chr(10)
GENERATED = "<!-- Written from your channel profile in Settings. Delete this line to keep your own edits. -->"
def path() -> Path:
    env = os.environ.get("WOOTS_PROFILE_FILE")
    return Path(env) if env else config.settings_file().with_name("profile.json")


def load() -> dict:
    """The profile with defaults filled in."""
    out = {k: v[0] for k, v in FIELDS.items()}
    try:
        got = json.loads(path().read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return out
    for k, v in (got.items() if isinstance(got, dict) else []):
        if k in out and isinstance(v, str) and v.strip():
            out[k] = v.strip()
    return out


def save(values: dict) -> dict:
    """Merge `values` into the saved profile; a blank value removes the field (back to its default). Atomic write."""
    try:
        have = json.loads(path().read_text(encoding="utf-8-sig"))
        have = have if isinstance(have, dict) else {}
    except (OSError, ValueError):
        have = {}
    for k, v in values.items():
        if k not in FIELDS:
            continue
        v = str(v or "").strip()
        if v:
            have[k] = v
        else:
            have.pop(k, None)
    p = path()
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=p.parent, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(have, f, indent=1)
    os.replace(tmp, p)
    if any(k in values for k in STYLE_KEYS):
        write_style_files()
    return load()


def is_set() -> bool:
    return load()["name"] != FIELDS["name"][0]


def about(p: dict | None = None) -> str:
    """A short paragraph for the top of a prompt, from what the user wrote about their channel; empty when they wrote nothing."""
    p = p or load()
    bits = []
    ident = []
    if p["name"] != FIELDS["name"][0]:
        ident.append(f"The host is {p['name']}.")
    if p["channel"] != FIELDS["channel"][0]:
        ident.append(f"The channel is {p['channel']}" + (f", {p['topic']}." if p["topic"] != FIELDS["topic"][0] else "."))
    if p["cohost"]:
        ident.append(f"A second voice, {p['cohost']}, appears in the videos.")
    if ident:
        bits.append(" ".join(ident))
    if p["audience"]:
        bits.append(f"The audience: {p['audience']}")
    if p["voice"]:
        bits.append(f"The host's voice and habits: {p['voice']}")
    return ("About the channel (from its profile). " + " ".join(bits) + "\n\n") if bits else ""


def prompt(text: str) -> str:
    """What a Claude run is given: the prompt with the channel paragraph (who the host is, the audience, the voice) first."""
    p = load()
    return about(p) + text


def _bullets(pairs) -> str:
    return NL.join(f"- {label}: {value}" for label, value in pairs if value)


def style_files(p: dict | None = None) -> dict:
    """{"woots-channel/brand.md": text, "woots-channel/house-style.md": text} from the profile; a file is left out when the profile has nothing for it."""
    p = p or load()
    out = {}
    brand = _bullets([("Headline font", p["headline_font"]), ("Label font", p["label_font"]), ("Colours", p["colors"])])
    if brand:
        out["woots-channel/brand.md"] = NL.join([GENERATED, "# Brand", "", "Graphics, title cards and thumbnails use these.", "", brand, ""])
    house = _bullets([("Tone", p["tone"]), ("Always", p["always"]), ("Never", p["never"])])
    if house:
        out["woots-channel/house-style.md"] = NL.join([GENERATED, "# House style", "", house, ""])
    return out


def write_style_files() -> list:
    """Put the generated brand and house-style files in the user's skills folder, where they replace the starter templates. A file the user has edited by hand
    (it no longer starts with the generated line) is never overwritten. Returns the files written."""
    import skillrules
    wrote = []
    for rel, text in style_files().items():
        dest = skillrules.SKILLS / rel
        try:
            if dest.exists() and not dest.read_text(encoding="utf-8").startswith(GENERATED):
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(text, encoding="utf-8")
            wrote.append(rel)
        except OSError:
            continue
    return wrote


def corrections(p: dict | None = None) -> list:
    """[(regex, right spelling)] from the `heard => right` lines of the profile's terms, matched against a whole word, case-insensitive; `word*` matches any ending."""
    out = []
    for line in (p or load())["terms"].splitlines():
        heard, arrow, right = (x.strip() for x in line.partition("=>"))
        if arrow and heard and right:
            out.append((("^" + re.escape(heard[:-1]) if heard.endswith("*") else "^" + re.escape(heard) + "$"), right))
    return out


def spellings(p: dict | None = None) -> list:
    """The right spelling of every term in the profile, for prompts that warn Claude the transcript mishears them."""
    out = []
    for line in (p or load())["terms"].splitlines():
        right = line.partition("=>")[2].strip() or line.strip() if line.strip() else ""
        if right and right not in out:
            out.append(right)
    return out


def thumbnail_style(p: dict | None = None) -> str:
    """What the thumbnail prompts say about colours and type, from the profile; nothing when the profile has none."""
    p = p or load()
    bits = ([f"brand colors {p['colors']}"] if p["colors"] else []) + ([f"{p['headline_font']} style text"] if p["headline_font"] else [])
    return (", " + ", ".join(bits)) if bits else ""


def host() -> str:
    return load()["name"]


def people() -> list:
    """Everyone who talks in the videos: the host, then the co-host if the profile names one."""
    p = load()
    return [p["name"]] + ([p["cohost"]] if p["cohost"] else [])


def view() -> dict:
    """For the Settings card: each field with its help text, its value ('' while it is the default) and the file it is saved in."""
    have = load()
    return {"fields": [{"key": k, "help": h, "value": "" if have[k] == d else have[k], "default": d} for k, (d, h) in FIELDS.items()], "file": str(path()), "set": is_set()}
