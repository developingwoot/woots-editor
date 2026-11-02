"""The fonts installed on this computer, for the font pickers in Settings.

Each font is {name, family, weight, italic}: `name` is what is saved in the channel profile (as the font is named on the computer, for example
"Oswald Bold"); `family`, `weight` and `italic` are what the page needs to draw a sample of it."""
import re
import shutil
import subprocess
import sys

WEIGHTS = {"thin": 100, "hairline": 100, "extralight": 200, "ultralight": 200, "light": 300, "semilight": 350, "regular": 400, "normal": 400, "book": 400,
           "medium": 500, "semibold": 600, "demibold": 600, "bold": 700, "extrabold": 800, "ultrabold": 800, "heavy": 800, "black": 900}
SYMBOL = re.compile(r"marlett|wingdings|webdings|^symbol$|mdl2|fluent icons|hololens|emoji|sitka (small|text) ", re.I)


def parse(name: str) -> dict | None:
    """A font's name as the system lists it ("Oswald Bold Italic") -> {name, family, weight, italic}. None for symbol fonts and empty names."""
    name = re.sub(r"\s*\((TrueType|OpenType|All res)\)\s*$", "", (name or "").strip(), flags=re.I).strip()
    if not name or SYMBOL.search(name):
        return None
    words, weight, italic = name.split(), 400, False
    while len(words) > 1:
        w = words[-1].lower().replace("-", "")
        if w in ("italic", "oblique"):
            italic = True
        elif w in WEIGHTS:
            weight = WEIGHTS[w]
        else:                                    # a width ("Arial Narrow") is part of the family name
            break
        words.pop()
    return {"name": name, "family": " ".join(words), "weight": weight, "italic": italic}


def _windows_names() -> list[str]:
    import winreg
    out = []
    for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        try:
            with winreg.OpenKey(hive, r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts") as k:
                for i in range(winreg.QueryInfoKey(k)[1]):
                    out += re.split(r"\s+&\s+", winreg.EnumValue(k, i)[0].split(" (")[0])      # "Cambria & Cambria Math (TrueType)" is two fonts
        except OSError:
            continue
    return out


def _fc_names() -> list[str]:
    if not shutil.which("fc-list"):
        return []
    out = subprocess.run(["fc-list", ":", "family", "style"], capture_output=True, text=True).stdout
    names = []
    for line in out.splitlines():
        fam, _, style = line.partition(":style=")
        fam = fam.split(",")[0].strip()
        style = style.split(",")[0].strip()
        names.append(fam if style.lower() in ("", "regular", "book") else f"{fam} {style}")
    return names


def installed() -> list[dict]:
    """Every installed font, one entry per name, sorted by family then weight."""
    names = _windows_names() if sys.platform == "win32" else _fc_names()
    seen, fonts = set(), []
    for n in names:
        f = parse(n)
        if f and f["name"].lower() not in seen:
            seen.add(f["name"].lower())
            fonts.append(f)
    return sorted(fonts, key=lambda f: (f["family"].lower(), f["italic"], f["weight"]))
