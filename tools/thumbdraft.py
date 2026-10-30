"""A thumbnail LAYOUT DRAFT: a frame of the final with the text drawn on it, in the channel's look (Oswald Bold, navy, orange, cream).
Claude does not generate images; the host makes the real thumbnail with an image tool from the prompts. This shows where the words go and whether
they can be read at the size YouTube shows (168 x 94), the same way storyboard.draw_card draws a draft card.
"""
import subprocess
from pathlib import Path

import config

W, H = 1280, 720
NAVY, ORANGE, CREAM = (20, 44, 68), (226, 112, 58), (244, 237, 228)
FONT = config.CODE_ROOT / "fonts" / "Oswald-Bold.ttf"
MAX_LINES = 3


def find_ffmpeg() -> str:
    import storyboard
    return storyboard.find_ffmpeg()


def grab(video: Path, t: float, out: Path) -> Path:
    """One frame of `video` at t seconds, cover-cropped to 1280 x 720."""
    r = subprocess.run([find_ffmpeg(), "-nostdin", "-v", "error", "-ss", f"{max(0.0, t):.2f}", "-i", str(video), "-frames:v", "1",
                        "-vf", f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H}", "-q:v", "2", "-y", str(out)], capture_output=True, timeout=120)
    if r.returncode != 0 or not out.exists():
        raise ValueError("could not read a picture from the video")
    return out


def lines_of(text: str) -> list:
    """The words split into at most MAX_LINES lines of similar length (all caps)."""
    words = text.upper().split()
    if not words:
        return []
    n = min(MAX_LINES, len(words))
    per = -(-len(words) // n)
    return [" ".join(words[i:i + per]) for i in range(0, len(words), per)]


def draw(frame: Path, text: str, out: Path) -> Path:
    """Draw `text` on the frame: left side, the last line in orange, a soft navy shade behind so it reads over any picture. Returns `out`."""
    from PIL import Image, ImageDraw, ImageFont
    lines = lines_of(text)
    if not lines:
        raise ValueError("write the thumbnail words first")
    img = Image.open(frame).convert("RGB").resize((W, H))
    shade = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shade)
    for x in range(0, int(W * 0.62)):                                       # a navy gradient from the left edge, fading out
        sd.line((x, 0, x, H), fill=NAVY + (int(200 * (1 - x / (W * 0.62))),))
    img = Image.alpha_composite(img.convert("RGBA"), shade)
    d = ImageDraw.Draw(img)
    box_w, box_h = int(W * 0.56), int(H * 0.8)
    size = 260
    while size > 40:
        f = ImageFont.truetype(str(FONT), size)
        if max(d.textlength(ln, font=f) for ln in lines) <= box_w and size * 1.05 * len(lines) <= box_h:
            break
        size -= 6
    f = ImageFont.truetype(str(FONT), size)
    y = (H - size * 1.05 * len(lines)) / 2
    for i, ln in enumerate(lines):
        fill = ORANGE if i == len(lines) - 1 and len(lines) > 1 else CREAM
        d.text((64 + 5, y + 5), ln, font=f, fill=(0, 0, 0, 160))             # a hard shadow keeps it legible at 168 x 94
        d.text((64, y), ln, font=f, fill=fill)
        y += size * 1.05
    img.convert("RGB").save(out, quality=90)
    return out


def make(video: Path, t: float, text: str, out: Path) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(out.stem + ".frame.jpg")
    try:
        return draw(grab(video, t, tmp), text, out)
    finally:
        tmp.unlink(missing_ok=True)
