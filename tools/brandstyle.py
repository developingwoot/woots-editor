"""The channel's look as the renderers need it: colours and fonts from the profile (Settings > Channel), with plain fallbacks when the profile has none.

Nothing about a channel is in the code: `shorts.py` and `shortsgfx.py` ask here. The colours text is what the Settings palette writes ("primary #142C44, accent #E2703A,
colour 3 #E4EDF4"); free text such as "navy #142C44, orange #E2703A" works too (the first colour is the primary, the second the accent).
"""
import re
from pathlib import Path

import channel
import sysfonts

FALLBACK = {"primary": "#1A1A1A", "accent": "#FFC400", "light": "#FFFFFF", "dark": "#000000"}
FALLBACK_FONT = ("Oswald", Path(__file__).resolve().parent.parent / "fonts" / "Oswald-Bold.ttf")         # ships with the app (open licence), so every computer has one
HEX = re.compile(r"(#[0-9a-f]{6}|#[0-9a-f]{3})\b", re.I)


def parse_colors(text: str) -> list:
    """[(name, '#RRGGBB'), ...] from the profile's colours text; entries without a hex code are skipped."""
    out = []
    for part in re.split(r"[\n,;]+", text or ""):
        m = HEX.search(part)
        if not m:
            continue
        hx = m.group(1).upper()
        if len(hx) == 4:
            hx = "#" + "".join(c * 2 for c in hx[1:])
        out.append((re.sub(r"[:\-\u2013\s]+$", "", part[:m.start()]).strip().lower(), hx))
    return out


def luminance(hx: str) -> float:
    r, g, b = (int(hx[i:i + 2], 16) / 255 for i in (1, 3, 5))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def palette(profile: dict | None = None) -> dict:
    """{'primary', 'accent', 'light', 'dark', 'extra': [...]}, every colour as '#RRGGBB'.

    A colour named primary / accent takes that role; the rest fill the roles still empty in order, then go to `extra`.
    `light` is the lightest colour that is light enough to carry text on a dark picture, `dark` the darkest that is dark enough to outline text (else white / black).
    """
    colors = parse_colors((profile if profile is not None else channel.load()).get("colors", ""))
    got = {}
    rest = []
    for name, hx in colors:
        role = "primary" if name == "primary" else "accent" if name == "accent" else ""
        if role and role not in got:
            got[role] = hx
        else:
            rest.append(hx)
    for role in ("primary", "accent"):
        if role not in got and rest:
            got[role] = rest.pop(0)
    allc = [hx for _, hx in colors]
    light = max(allc, key=luminance, default="")
    dark = min(allc, key=luminance, default="")
    return {"primary": got.get("primary", FALLBACK["primary"]), "accent": got.get("accent", FALLBACK["accent"]),
            "light": light if light and luminance(light) >= 0.8 else FALLBACK["light"],
            "dark": dark if dark and luminance(dark) <= 0.12 else FALLBACK["dark"], "extra": rest}


def rgb(hx: str) -> tuple:
    return tuple(int(hx[i:i + 2], 16) for i in (1, 3, 5))


def bgr(hx: str) -> tuple:
    """OpenCV's channel order."""
    return rgb(hx)[::-1]


def ass(hx: str) -> str:
    """An ASS colour (&H00BBGGRR&)."""
    r, g, b = rgb(hx)
    return f"&H00{b:02X}{g:02X}{r:02X}&"


def ffmpeg(hx: str) -> str:
    return "0x" + hx[1:]


def font(role: str = "headline", profile: dict | None = None) -> dict:
    """{'name', 'family', 'file', 'bold'} for the profile's `headline_font` or `label_font`. The family is read from the file (libass matches on it), and an
    installed font that cannot be found falls back to the label font, then the headline font, then the font that ships with the app."""
    p = profile if profile is not None else channel.load()
    for key in ([f"{role}_font", "headline_font"] if role != "headline" else ["headline_font"]):
        name = (p.get(key) or "").strip()
        path = sysfonts.file_for(name) if name else ""
        if path and Path(path).is_file():
            f = sysfonts.parse(name)
            return {"name": name, "family": sysfonts.family_of_file(path) or f["family"], "file": path, "bold": f["weight"] >= 600}
    name, path = FALLBACK_FONT
    return {"name": name, "family": sysfonts.family_of_file(str(path)) or name, "file": str(path), "bold": True}
