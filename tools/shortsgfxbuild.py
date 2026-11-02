"""Building the graphics of a short (what `shortsgfx` planned), in the channel's colours and font.

  wanted(short)                              -> the planned graphics that are built: every one the host has not cut
  kinetic_events(short, pieces, speed)       -> [(start, end, ass text)] key-word pop-ups: the words land with a pop, in the accent colour (drawn with the captions)
  cards(short, pieces, speed, folder, f)     -> [{"png", "t0", "t1", "x", "y", "first", "last"}] explainer cards: a panel in the graphic's region (top, full, bottom) with the
                                                headline and, one line at a time, the items under it; each step of the reveal is a picture shown from its time to the next
  sound_events(short, pieces, speed)         -> [{"t", "role"}] for sfxkit: a hit when an explainer lands, a pop when a key word does

A graphic's `text` is its headline; a list or a comparison puts the headline first and each item on its own line (up to four). Every other look than `kinetic` is built as a card,
because they all say the same thing: what appears, when. Times in a plan are main-video seconds: `shortsgfx.to_short` gives the time in the finished short.
"""
from pathlib import Path

import brandstyle
import shortsgfx

FADE_S = 0.15
SLIDE_PX = 60                                   # a card rises this far into place while it fades in
MAX_ITEMS = 4


def single_source(short: dict) -> bool:
    """Plans are timed in one recording's seconds: a short joined from several recordings gets none (yet)."""
    return len({r["src"] for r in short.get("ranges") or [] if isinstance(r, dict)}) <= 1


def wanted(short: dict) -> list:
    if not single_source(short):
        return []
    return [g for g in (short.get("gfx") or {}).get("graphics", []) if g.get("status") != "cut"]


def is_kinetic(g: dict) -> bool:
    return g.get("look") == "kinetic"


def window(g: dict, pieces: list, speed: float) -> tuple:
    return shortsgfx.to_short(pieces, speed, g["t0"]), shortsgfx.to_short(pieces, speed, g["t1"])


def lines_of(g: dict) -> list:
    """The headline and up to MAX_ITEMS items of a card, from its text (one per line); the 'what' stands in when no text was written."""
    text = (g.get("text") or g.get("what") or "").strip()
    return [x.strip() for x in text.splitlines() if x.strip()][: MAX_ITEMS + 1]


def region_of(g: dict) -> tuple:
    return shortsgfx.REGIONS.get(g.get("place"), shortsgfx.REGIONS["top"])


# ----------------------------------------------------------------------------- key-word pop-ups (ASS)
def kinetic_events(short: dict, pieces: list, speed: float = 1.0) -> list:
    import shorts as sh
    pal = brandstyle.palette()
    accent = brandstyle.ass(pal["accent"])
    out = []
    for g in wanted(short):
        if not is_kinetic(g):
            continue
        a, b = window(g, pieces, speed)
        words = [x.strip() for x in (g.get("text") or g.get("what") or "").upper().replace("{", "").replace("}", "").splitlines() if x.strip()]
        if not words or b - a < 0.2:
            continue
        x0, y0, x1, y1 = region_of(g)
        text = "\\N".join(words[:3])
        longest = max(len(w) for w in words[:3])
        size = max(60, min(170, int((x1 - x0) / (longest * 0.5 + 1)), int((y1 - y0) / (len(words[:3]) * 1.25))))
        tags = (f"{{\\an5\\pos({(x0 + x1) // 2},{(y0 + y1) // 2})\\fs{size}\\c{accent}\\fad(60,160)\\fscx45\\fscy45"
                f"\\t(0,140,\\fscx112\\fscy112)\\t(140,260,\\fscx100\\fscy100)}}")
        out.append((a, b, tags + text))
    return out


# ----------------------------------------------------------------------------- explainer cards (pictures)
def _fit(draw, text, font_file, box_w, box_h, start, floor=24):
    """The largest font size (from `start`) at which `text` wraps into box_w x box_h; returns (font, wrapped lines)."""
    from PIL import ImageFont
    size = start
    while True:
        font = ImageFont.truetype(str(font_file), size)
        lines, cur = [], ""
        for word in text.split():
            trial = (cur + " " + word).strip()
            if cur and draw.textlength(trial, font=font) > box_w:
                lines.append(cur)
                cur = word
            else:
                cur = trial
        lines.append(cur)
        if size <= floor or (len(lines) * size * 1.15 <= box_h and all(draw.textlength(x, font=font) <= box_w for x in lines)):
            return font, lines
        size -= 4


def draw_card(g: dict, shown: int, f: float = 1.0):
    """The card with the headline and the first `shown` items, as an RGBA picture the size of its region (times `f`)."""
    from PIL import Image, ImageDraw
    pal = brandstyle.palette()
    primary, accent, light = brandstyle.rgb(pal["primary"]), brandstyle.rgb(pal["accent"]), brandstyle.rgb(pal["light"])
    ff = brandstyle.font("headline")["file"]
    x0, y0, x1, y1 = region_of(g)
    w, h = int((x1 - x0) * f), int((y1 - y0) * f)
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((0, 0, w - 1, h - 1), int(28 * f), fill=primary + (255 if g.get("place") == "full" else 238,))
    d.rounded_rectangle((0, 0, int(14 * f), h - 1), int(7 * f), fill=accent + (255,))
    lines = lines_of(g)
    if not lines:
        return im
    head, items = lines[0].upper(), [x.upper() for x in lines[1:]]
    pad = int(48 * f)
    inner_w, inner_h = w - 2 * pad, h - 2 * pad
    if not items:                                                   # one line: the headline fills the card
        font, wrapped = _fit(d, head, ff, inner_w, inner_h * 0.8, int(150 * f))
        total = len(wrapped) * font.size * 1.15
        y = (h - total) / 2
        for ln in wrapped:
            d.text((w / 2, y), ln, font=font, fill=light + (255,), anchor="ma")
            y += font.size * 1.15
        d.rounded_rectangle((w / 2 - 90 * f, y + 8 * f, w / 2 + 90 * f, y + 8 * f + 10 * f), int(5 * f), fill=accent + (255,))
        return im
    hfont, hwrap = _fit(d, head, ff, inner_w, inner_h * 0.3, int(84 * f))
    y = pad
    for ln in hwrap:
        d.text((pad, y), ln, font=hfont, fill=accent + (255,))
        y += hfont.size * 1.15
    y += 22 * f
    room = (h - pad - y) / len(items)
    ifont, _ = _fit(d, max(items, key=len), ff, inner_w - 70 * f, room * 0.85, int(78 * f))
    for k, item in enumerate(items[:shown]):
        cy = y + k * room
        d.ellipse((pad, cy + ifont.size * 0.3, pad + 30 * f, cy + ifont.size * 0.3 + 30 * f), fill=accent + (255,))
        d.text((pad + 56 * f, cy), item, font=ifont, fill=light + (255,))
    return im


def cards(short: dict, pieces: list, speed: float, folder, f: float = 1.0) -> list:
    """The pictures to lay over the video, one per step of each card's reveal (the headline, then each item), written to `folder`."""
    out = []
    folder = Path(folder)
    for gi, g in enumerate(wanted(short)):
        if is_kinetic(g) or not lines_of(g):
            continue
        a, b = window(g, pieces, speed)
        if b - a < 0.4:
            continue
        n_items = len(lines_of(g)) - 1
        steps = n_items + 1 if n_items else 1
        reveal = (b - a) * 0.7                                        # the items are all there for the last 30 % of the time
        x0, y0, _, _ = region_of(g)
        for k in range(steps):
            png = folder / f"gfx_{gi}_{k}.png"
            draw_card(g, k, f).save(png)
            start = a if k == 0 else a + reveal * k / steps
            end = b if k == steps - 1 else a + reveal * (k + 1) / steps
            out.append({"png": str(png), "t0": round(start, 3), "t1": round(end, 3), "x": int(x0 * f), "y": int(y0 * f), "first": k == 0, "last": k == steps - 1})
    return out


def sound_events(short: dict, pieces: list, speed: float = 1.0) -> list:
    return [{"t": window(g, pieces, speed)[0], "role": "pop" if is_kinetic(g) else "hit"} for g in wanted(short) if lines_of(g)]
