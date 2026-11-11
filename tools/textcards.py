"""On-screen text cards: a short line of text in a box near the bottom left of the picture, in the channel's colours and headline font.

Two kinds: `correction` (the host misspoke: "*0.4 mm nozzle, not 0.6") and `detail` (a price, a model number, a setting). A card is a full-frame PNG
with alpha (1920x1080, transparent outside the box), drawn with Pillow and cached by its text, kind and brand, so the same card is never drawn twice.
The renderer (sectionrender.py) shows it as a still overlay that fades in and out; on a beat it lives in `on_screen.text`:
    [{"text": "*0.4 mm nozzle, not 0.6", "kind": "correction|detail", "at": 1.2, "dur": 4.0}]
"""
import hashlib
import json
import os
from pathlib import Path

import config

KINDS = ("correction", "detail")
W, H = 1920, 1080
FADE_S = 0.2
MAX_CHARS = 90
SIZE = 54                      # px at 1080p
LEFT, BOTTOM = 96, 150         # the box's left edge and its distance from the bottom (clear of the lower edge YouTube's controls cover)
MAX_W = 1100                   # text wider than this wraps (three lines at most)


def folder() -> Path:
    return config.EDITOR_DATA / "textcards"


def clean(text) -> str:
    return " ".join(str(text or "").split())[:MAX_CHARS]


def _brand() -> dict:
    import brandstyle
    pal, f = brandstyle.palette(), brandstyle.font("headline")
    return {"primary": pal["primary"], "accent": pal["accent"], "light": pal["light"], "dark": pal["dark"], "font": f.get("file", "")}


def _wrap(draw, text: str, font, width: int) -> list:
    lines, cur = [], ""
    for w in text.split():
        trial = f"{cur} {w}".strip()
        if cur and draw.textlength(trial, font=font) > width:
            lines.append(cur)
            cur = w
        else:
            cur = trial
    if cur:
        lines.append(cur)
    if len(lines) > 3:
        lines = lines[:3]
        lines[-1] = lines[-1].rstrip(".,") + "…"
    return lines


def bar_colour(kind: str, brand: dict) -> str:
    """The stripe on the left of the box: the accent for a correction, the primary colour for a detail, or the light colour when the primary would vanish on the box."""
    import brandstyle
    if kind == "correction":
        return brand["accent"]
    return brand["primary"] if abs(brandstyle.luminance(brand["primary"]) - brandstyle.luminance(brand["dark"])) > 0.15 else brand["light"]


def draw(text: str, kind: str, brand: dict, out: Path) -> Path:
    """Draw one card to `out` (PNG with alpha)."""
    from PIL import Image, ImageDraw, ImageFont
    import brandstyle
    try:
        font = ImageFont.truetype(brand["font"], SIZE)
    except (OSError, ValueError):
        font = ImageFont.load_default(SIZE)
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    lines = _wrap(d, text, font, MAX_W)
    asc, desc = font.getmetrics()
    line_h = int((asc + desc) * 1.1)
    pad_x, pad_y, bar = 34, 22, 12
    tw = max(int(d.textlength(x, font=font)) for x in lines)
    bw, bh = bar + pad_x * 2 + tw, pad_y * 2 + line_h * len(lines)
    x0, y1 = LEFT, H - BOTTOM
    y0 = y1 - bh
    d.rounded_rectangle([x0, y0, x0 + bw, y1], radius=14, fill=(*brandstyle.rgb(brand["dark"]), 225))
    d.rounded_rectangle([x0, y0, x0 + bar, y1], radius=6, fill=(*brandstyle.rgb(bar_colour(kind, brand)), 255))
    for i, line in enumerate(lines):
        d.text((x0 + bar + pad_x, y0 + pad_y + i * line_h), line, font=font, fill=(*brandstyle.rgb(brand["light"]), 255))
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(out.stem + f".{os.getpid()}.part.png")
    img.save(tmp)
    os.replace(tmp, out)
    return out


def card(text: str, kind: str = "detail", brand: dict | None = None) -> Path:
    """The PNG of a card (drawn once, then reused)."""
    text, kind = clean(text), kind if kind in KINDS else "detail"
    if not text:
        raise ValueError("the text is empty")
    brand = brand or _brand()
    key = hashlib.sha1(json.dumps([text, kind, brand, SIZE, LEFT, BOTTOM, 1], sort_keys=True).encode("utf-8")).hexdigest()[:16]
    out = folder() / f"{key}.png"
    return out if out.is_file() else draw(text, kind, brand, out)


def entry(x: dict, beat_dur: float, default_s: float) -> dict | None:
    """A beat's on_screen.text row, cleaned: {text, kind, at, dur} kept inside the beat; None when it has no text."""
    text = clean(x.get("text"))
    if not text:
        return None
    at = max(0.0, float(x.get("at") or 0))
    dur = float(x.get("dur") or default_s)
    if beat_dur > 0:
        at = min(at, max(0.0, beat_dur - 1.0))
        dur = min(dur, beat_dur - at)
    return {"text": text, "kind": x.get("kind") if x.get("kind") in KINDS else "detail", "at": round(at, 2), "dur": round(max(0.5, dur), 2)}
