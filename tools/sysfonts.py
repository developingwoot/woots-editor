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


def _windows_files() -> dict[str, str]:
    import os
    import winreg
    out = {}
    for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        try:
            with winreg.OpenKey(hive, r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts") as k:
                for i in range(winreg.QueryInfoKey(k)[1]):
                    name, data, _ = winreg.EnumValue(k, i)
                    path = data if os.path.isabs(data) else os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts", data)
                    for n in re.split(r"\s+&\s+", name.split(" (")[0]):
                        f = parse(n)
                        if f:
                            out.setdefault(f["name"].lower(), path)
        except OSError:
            continue
    return out


def _fc_files() -> dict[str, str]:
    if not shutil.which("fc-list"):
        return {}
    out = subprocess.run(["fc-list", "--format", "%{file}|%{family}|%{style}\n"], capture_output=True, text=True).stdout
    files = {}
    for line in out.splitlines():
        path, fam, style = (line.split("|") + ["", ""])[:3]
        fam, style = fam.split(",")[0].strip(), style.split(",")[0].strip()
        files.setdefault((fam if style.lower() in ("", "regular", "book") else f"{fam} {style}").lower(), path)
    return files


def files() -> dict[str, str]:
    """Lower-case font name -> the font's file on this computer."""
    return _windows_files() if sys.platform == "win32" else _fc_files()


def file_for(name: str) -> str:
    """The file of the font called `name` (as saved in the profile), or '' when it is not installed."""
    f = parse(name)
    return files().get(f["name"].lower(), "") if f else ""


def family_of_file(path: str) -> str:
    """The family name stored inside a TrueType/OpenType file (what libass matches on), or '' when it cannot be read."""
    import struct
    try:
        with open(path, "rb") as fh:
            head = fh.read(12)
            if head[:4] == b"ttcf":                                         # a collection: use its first font
                off = struct.unpack(">I", fh.read(8)[4:8])[0]
                fh.seek(off)
                head = fh.read(12)
            n = struct.unpack(">H", head[4:6])[0]
            table = {}
            for _ in range(n):
                tag, _sum, off, ln = struct.unpack(">4sIII", fh.read(16))
                table[tag] = (off, ln)
            if b"name" not in table:
                return ""
            off, ln = table[b"name"]
            fh.seek(off)
            data = fh.read(ln)
        count, str_off = struct.unpack(">HH", data[2:6])
        found = {}
        for i in range(count):
            plat, _enc, _lang, nid, length, offset = struct.unpack(">6H", data[6 + 12 * i:18 + 12 * i])
            if nid not in (1, 16):
                continue
            raw = data[str_off + offset:str_off + offset + length]
            text = raw.decode("utf-16-be" if plat in (0, 3) else "latin-1", "ignore")
            if text and (nid not in found or plat == 3):
                found[nid] = text
        return found.get(16) or found.get(1) or ""
    except (OSError, struct.error):
        return ""
