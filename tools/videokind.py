"""The kind of video: what the talking picture shows, which decides what may cover it and what Claude is told.

An unboxing and a desk video need opposite rules: over a talking head a cutaway is welcome; over the host's hands on the thing it hides the video.
The host chooses the kind on the Footage screen (`kind` in <name>.footage.json), or leaves it on "auto" and the app decides from what the frame
library saw in the talking recordings.

  talking   the host talks to the camera; the work is shown in other footage
  hands-on  the camera is on the work and the host talks while working (an unboxing, a build, a repair)
  screen    the host talks over a recording of the screen (a software tutorial)
"""
import json

import brolllib
import clipmap
import config

WORK = config.WORK
KINDS = {"auto": "Let the app decide", "talking": "Talking to the camera", "hands-on": "Hands-on (unboxing, build, repair)", "screen": "Talking over the screen"}
HINTS = {"talking": "Cutaways go over the talking head.", "hands-on": "Your hands on the thing are the picture: cutaways only where you face the camera.",
         "screen": "The screen is the picture: cutaways only where you face the camera."}
LINES = {
    "talking": "",
    "hands-on": ("This is a hands-on video: the camera is on the work and the host talks while working. What the host does is the content. A sentence that only narrates the obvious can go; "
                 "one that gives a decision, a problem, a surprise, an opinion or a number the viewer needs stays. Never ask for a cutaway over a moment where the host is showing the thing.\n"),
    "screen": ("This is a screen video: the host talks over a recording of the screen, and the screen is the picture. Keep what explains a step or its reason; "
               "never ask for a cutaway over a moment where the host is showing something on the screen.\n"),
}
WORK_SHARE = 0.5             # auto: this share of the looks at the talking recordings show hands at work -> hands-on
SCREEN_SHARE = 0.6           # auto: this share are a screen recording -> screen


def get(work: str, name: str) -> str:
    """The host's choice ('auto' when none)."""
    k = (clipmap.read_json(WORK / work / f"{name}.footage.json", {}) or {}).get("kind")
    return k if k in KINDS else "auto"


def set(work: str, name: str, kind: str) -> str:        # noqa: A001
    if kind not in KINDS:
        raise ValueError("unknown kind of video")
    p = WORK / work / f"{name}.footage.json"
    cfg = clipmap.read_json(p, {}) or {}
    cfg["kind"] = kind
    clipmap.write_json(p, cfg)
    return kind


def guess(samples: list) -> str:
    """The kind from the frame library's looks at the talking recordings (`samples`: every sample of them)."""
    if not samples:
        return "talking"
    n = len(samples)
    if sum(1 for s in samples if s.get("kind") == "screen recording") / n >= SCREEN_SHARE:
        return "screen"
    if sum(1 for s in samples if s.get("hands") or s.get("kind") == "screen recording") / n >= WORK_SHARE:
        return "hands-on"
    return "talking"


def resolve(work: str, name: str) -> str:
    """The kind the cut is made by: the host's choice, or the guess when it is 'auto'."""
    k = get(work, name)
    if k != "auto":
        return k
    import recut
    cfg = clipmap.read_json(WORK / work / f"{name}.footage.json", {}) or {}
    jp = brolllib.paths(work, name)[1]
    if not jp.exists():
        return "talking"
    try:
        clips = json.loads(jp.read_text(encoding="utf-8")).get("clips", {})
    except ValueError:
        return "talking"
    analysis = cfg.get("analysis") or {}
    return guess([s for rel, c in clips.items() if recut.is_talking(analysis.get(rel) or {}) for s in c.get("samples", [])])


def line(kind: str) -> str:
    """What every Claude run of the cut is told first about this kind of video ('' for a talking video)."""
    return LINES.get(kind, "")


def view(work: str, name: str) -> dict:
    """For the Footage screen: the choice, the options, and what 'auto' comes to."""
    k = get(work, name)
    now = resolve(work, name)
    return {"value": k, "now": now, "hint": (f"Looks like: {KINDS[now].lower()}. " if k == "auto" else "") + HINTS[now],
            "options": [{"id": i, "label": label} for i, label in KINDS.items()]}
