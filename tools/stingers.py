"""Stingers: short animations in the channel's colours and font that cover a cut, so the switch to a cutaway (and back) happens under them.

Templates are HyperFrames compositions in `youtube-graphics/stingers/<id>.html` (the user's copy in ~/.claude/skills wins, and a user can add more).
They are filled with the brand from Settings > Your channel (brandstyle: colours __PRIMARY__ __ACCENT__ __LIGHT__ __DARK__, the channel's name __NAME__,
the headline font copied in as font.ttf) and rendered ONCE, transparent, into <state>/stingers/<id>-<signature>/<id>.mov. The signature changes when the
template or the brand changes, so a new brand means making them again; nothing is rendered while a video builds.
A transitions preset of kind "stinger" names the template and the moment it covers the whole frame ("cover"); see transitions.py.
"""
import hashlib
import html
import shutil
import subprocess
from pathlib import Path

import config
import skillrules

OUT = config.EDITOR_DATA / "stingers"
SUBDIR = "stingers"


def templates() -> dict:
    """{id: template path}: the starter templates with the user's copies and additions on top."""
    return {f.stem: f for f in skillrules.files("youtube-graphics", f"{SUBDIR}/*.html")}


def brand() -> dict:
    import brandstyle
    import channel
    p = channel.load()
    pal = brandstyle.palette(p)
    return {"colors": {k: pal[k] for k in ("primary", "accent", "light", "dark")}, "font": brandstyle.font("headline", p)["file"],
            "name": (p.get("channel") or "").strip()}


def fill(text: str, b: dict) -> str:
    out = text
    for k, v in b["colors"].items():
        out = out.replace(f"__{k.upper()}__", v)
    return out.replace("__NAME__", html.escape(b["name"] or ""))


def signature(sid: str, b: dict | None = None) -> str:
    b = b or brand()
    t = templates().get(sid)
    if not t:
        raise ValueError("unknown stinger")
    h = hashlib.sha1(t.read_bytes())
    h.update(repr((sorted(b["colors"].items()), b["name"], Path(b["font"]).name, Path(b["font"]).stat().st_size if Path(b["font"]).is_file() else 0)).encode())
    return h.hexdigest()[:10]


def folder(sid: str, b: dict | None = None) -> Path:
    return OUT / f"{sid}-{signature(sid, b)}"


def file_of(sid: str, b: dict | None = None):
    """The rendered stinger for the brand as it is now, or None when it has not been made (or the brand changed since)."""
    try:
        f = folder(sid, b) / f"{sid}.mov"
    except (ValueError, OSError):
        return None
    return f if f.is_file() and f.stat().st_size > 0 else None


def prepare(sid: str, b: dict | None = None) -> Path:
    """The composition folder: index.html filled with the brand, and the headline font next to it."""
    b = b or brand()
    d = folder(sid, b)
    d.mkdir(parents=True, exist_ok=True)
    (d / "index.html").write_text(fill(templates()[sid].read_text(encoding="utf-8"), b), encoding="utf-8")
    if Path(b["font"]).is_file():
        shutil.copyfile(b["font"], d / "font.ttf")
    return d


def render_cmd(sid: str, d: Path) -> list:
    import builder
    npx = shutil.which("npx", path=builder.tool_env().get("PATH")) or "npx"
    return [npx, "--yes", builder.HF, "render", str(d), "-o", str(d / f"{sid}.mov"), "--format", "mov", "--quality", "draft", "--fps", "30", "--quiet"]


def still_at(sid: str) -> float:
    """When to take the Settings picture: the template's <meta name="still" content="seconds">, else 0.15 s (coming in)."""
    import re
    m = re.search(r'<meta\s+name="still"\s+content="([\d.]+)"', templates()[sid].read_text(encoding="utf-8"))
    return float(m.group(1)) if m else 0.15


def still_cmd(sid: str, d: Path, at: float = 0.15) -> list:
    """A small picture of the stinger coming in (on a grey ground), for Settings. Trimmed and restarted at 0 so its first frame meets the ground's
    first frame (a seeked input can start a frame late, and the picture is then only the ground)."""
    return ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=0x808080:s=1920x1080", "-i", str(d / f"{sid}.mov"),
            "-filter_complex", f"[1]trim=start={at:.2f},setpts=PTS-STARTPTS[s];[0][s]overlay=shortest=1,scale=320:-2", "-frames:v", "1", str(d / f"{sid}.png")]


def make(ids: list | None = None, run=subprocess.run, log=print) -> dict:
    """Render the stingers that are missing for the current brand. {id: "made" | "ready" | error text}."""
    import builder
    b = brand()
    out = {}
    for sid in ids or sorted(templates()):
        if file_of(sid, b):
            out[sid] = "ready"
            continue
        d = prepare(sid, b)
        log(f"rendering the stinger {sid}")
        for _ in range(2):                                              # the first render after a download now and then makes no file: once more
            r = run(render_cmd(sid, d), cwd=str(d), env=builder.tool_env(), capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600)
            if r.returncode == 0 and file_of(sid, b):
                break
        if r.returncode != 0 or not file_of(sid, b):
            out[sid] = ((r.stderr or r.stdout or "").strip()[-300:]) or "the render did not make a file"
            continue
        run(still_cmd(sid, d, still_at(sid)), capture_output=True, text=True, timeout=60)
        for old in OUT.glob(f"{sid}-*"):                                # earlier brands' renders
            if old != d and old.is_dir():
                shutil.rmtree(old, ignore_errors=True)
        out[sid] = "made"
    return out


def view() -> list:
    """For Settings: each stinger, whether it is made for the current brand, and its picture."""
    b = brand()
    rows = []
    for sid in sorted(templates()):
        f = file_of(sid, b)
        png = f.with_suffix(".png") if f else None
        rows.append({"id": sid, "ready": bool(f), "still": f"/stingers/{f.parent.name}/{sid}.png" if png and png.is_file() else ""})
    return rows


def served(rel: str):
    """The file behind /stingers/<folder>/<file> (a picture or the clip), only inside the stingers folder."""
    parts = rel.strip("/").split("/")
    if len(parts) != 2 or any(not p or p in (".", "..") or "\\" in p for p in parts) or Path(parts[1]).suffix.lower() not in (".png", ".mov"):
        return None
    p = OUT / parts[0] / parts[1]
    return p if config.inside(OUT, p) and p.is_file() else None
