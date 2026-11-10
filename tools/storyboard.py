"""Storyboard: one frame per beat for the whole video.

Usage (needs ffmpeg, Pillow and OpenCV: run it with the editor venv, the app does):
    python storyboard.py build <work> <name> [--all]    # new/changed beats only, or everything with --all
    python storyboard.py check <work> <name>            # print the state

Reads   <name>.beatmap.json (the plan) and <name>.footage.json (where the footage lives).
Writes  _editor\\work\\<work>\\storyboard\\<beat>.jpg  frames.json  index.html
        <name>.storyboard.marks.json                                              (the host's OK / change marks, outside that folder)

A frame is 960x540:
  * A-roll / punch-in beats: a real frame of the planned take (the middle of the beat); a punch-in is cropped to about
    1.6x with the face in the upper third (approximate: the real punch-in is planned later)
  * B-roll beats: a frame of the first B-roll insert (or a placeholder naming the file)
  * screenshot / text / full-frame graphic beats: a brand-navy panel with the note
  * a live (not cut) graphic is drawn as a DRAFT card in the brand style (Poppins, navy, orange chip) over the frame in
    the spot that covers your face least; `graphic.draft` = a still image Claude made of the real graphic (HyperFrames
    snapshot) replaces the generic card. If the only spots cover the face the frame is flagged.
Python stdlib for state/marks; build() imports Pillow, OpenCV and facedet lazily.
"""
import argparse
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(os.path.abspath(__file__)).parent
import config
WORK = config.WORK
sys.path.insert(0, str(HERE))
W, H = 960, 540
NAVY, ORANGE, CREAM, BLUE_LT, INK = (20, 44, 68), (226, 112, 58), (244, 237, 228), (169, 205, 232), (11, 23, 36)
FONT_CANDIDATES = [os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "Windows", "Fonts", "Poppins-ExtraBold.ttf"),
                   os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "Windows", "Fonts", "Poppins-Bold.ttf"),
                   os.path.join(str(HERE.parent.parent), "fonts", "Oswald-Bold.ttf"),
                   r"C:\Windows\Fonts\segoeuib.ttf", r"C:\Windows\Fonts\arialbd.ttf"]


def _replace(tmp, p):
    """os.replace that survives a reader holding the destination open (Windows: 'Access is denied' while the board polls)."""
    for i in range(8):
        try:
            os.replace(tmp, p)
            return
        except PermissionError:
            if i == 7:
                raise
            time.sleep(0.05 * (i + 1))


def read_json(p: Path, default=None):
    if not p.exists():
        return default
    return json.loads(p.read_text(encoding="utf-8-sig"))


import projectstore  # noqa: E402  (plan-file writes are recorded: ADR 0005)


def write_json(p: Path, data):
    projectstore.write_json(p, data)


def sb_dir(work: str) -> Path:
    return WORK / work / "storyboard"


def marks_path(work: str, name: str) -> Path:
    return WORK / work / f"{name}.storyboard.marks.json"


def beats_of(work: str, name: str):
    bm = read_json(WORK / work / f"{name}.beatmap.json")
    return bm, [b for b in (bm or {}).get("beats", []) if not b.get("skip")]


def beat_sig(b: dict) -> str:
    """What a frame depends on. A change here makes the frame outdated and clears the host's mark on it."""
    g = b.get("graphic") or {}
    draft = g.get("draft")
    extra = ""
    if draft and Path(draft).exists():
        st = Path(draft).stat()
        extra = f"{st.st_size}:{int(st.st_mtime)}"
    key = {k: b.get(k) for k in ("aroll", "on_screen", "graphic", "missing")}
    if key["aroll"]:
        key["aroll"] = {k: v for k, v in key["aroll"].items() if k != "words"}                 # the shown words are a view of the take, not a decision
    return hashlib.sha1((json.dumps(key, sort_keys=True, ensure_ascii=False) + extra).encode()).hexdigest()[:12]


# ----------------------------------------------------------------------------- state and marks (stdlib only)
def _mtime(work: str, img: str) -> int:
    """Changes whenever a frame is redrawn, even with the same beat signature, so the browser never shows a stale one."""
    try:
        return int((sb_dir(work) / img).stat().st_mtime)
    except OSError:
        return 0


def state(work: str, name: str) -> dict:
    bm, beats = beats_of(work, name)
    fj = read_json(sb_dir(work) / "frames.json") or {}
    marks = (read_json(marks_path(work, name)) or {}).get("marks", {})
    out = {"beatmap_ready": bool(bm), "built": bool(fj), "frames": [], "stale": False, "total": len(beats),
           "counts": {"ok": 0, "change": 0, "unseen": 0, "outdated": 0, "unbuilt": 0}, "fix_flags": 0,
           "face_model": fj.get("face_model"), "generated": fj.get("generated")}
    if not bm:
        return out
    seen = set()
    for b in beats:
        sig = beat_sig(b)
        meta = (fj.get("frames") or {}).get(b["id"])
        mk = marks.get(b["id"]) or {}
        g = b.get("graphic")
        if not meta:
            status = "unbuilt"
        elif meta["sig"] != sig:
            status = "outdated"
        elif mk.get("sig") == sig and mk.get("status") in ("ok", "change"):
            status = mk["status"]
        else:
            status = "unseen"
        seen.add(b["id"])
        out["counts"][status] += 1
        flags = meta["flags"] if meta and meta["sig"] == sig else []
        out["fix_flags"] += sum(1 for f in flags if f["level"] == "fix")
        out["frames"].append({"id": b["id"], "section": b.get("section", ""), "script_lines": b["script_lines"],
                              "start": b.get("start"), "end": b.get("end"), "said": b["said"][:140],
                              "shot": b["on_screen"].get("shot", "a-roll"), "note": b["on_screen"].get("note", ""),
                              "kind": g["kind"] if g and not g.get("struck") else "", "idea": (g or {}).get("idea", "") if g and not g.get("struck") else "",
                              "img": f"{meta['img']}?v={meta['sig']}-{_mtime(work, meta['img'])}" if meta else None,
                              "flags": flags, "status": status,
                              "mark_note": mk.get("note", ""), "sig": sig})
    removed = [k for k in (fj.get("frames") or {}) if k not in seen]
    out["stale"] = bool(removed) or out["counts"]["outdated"] > 0 or out["counts"]["unbuilt"] > 0
    out["removed"] = removed
    return out


def mark(work: str, name: str, beat: str, status: str, note: str = "") -> dict:
    if status not in ("ok", "change", ""):
        raise ValueError("status must be ok, change or empty")
    _, beats = beats_of(work, name)
    b = next((x for x in beats if x["id"] == beat), None)
    if not b:
        raise ValueError(f"unknown beat {beat!r}")
    p = marks_path(work, name)
    d = read_json(p) or {"marks": {}, "log": []}
    if status == "change" and not note.strip():
        note = (d["marks"].get(beat) or {}).get("note", "")
    if status:
        d["marks"][beat] = {"status": status, "note": note.strip(), "sig": beat_sig(b), "t": time.strftime("%Y-%m-%dT%H:%M:%S")}
    else:
        d["marks"].pop(beat, None)
    d["log"].append({"t": time.strftime("%Y-%m-%dT%H:%M:%S"), "beat": beat, "status": status, "note": note.strip()})
    write_json(p, d)
    return state(work, name)


# ----------------------------------------------------------------------------- drawing (Pillow / OpenCV)
def find_ffmpeg() -> str:
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    base = Path(os.environ.get("LOCALAPPDATA", ""))
    for p in base.glob("Microsoft/WinGet/Packages/Gyan.FFmpeg*/*/bin/ffmpeg.exe"):
        return str(p)
    raise RuntimeError("ffmpeg not found")


def font(size: int):
    from PIL import ImageFont
    for f in FONT_CANDIDATES:
        if Path(f).exists():
            return ImageFont.truetype(f, size)
    return ImageFont.load_default()


def grab(path: Path, t: float):
    """One frame of a video at t seconds, cover-cropped to 960x540."""
    from PIL import Image
    r = subprocess.run([find_ffmpeg(), "-nostdin", "-v", "error", "-ss", f"{max(0.0, t):.2f}", "-i", str(path), "-frames:v", "1",
                        "-vf", f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H}", "-f", "image2pipe", "-vcodec", "mjpeg",
                        "-q:v", "3", "-"], capture_output=True, timeout=120)
    if r.returncode != 0 or not r.stdout:
        raise RuntimeError((r.stderr or b"").decode("utf-8", "replace").strip()[-200:] or "no frame")
    return Image.open(io.BytesIO(r.stdout)).convert("RGB")


def panel(text: str, sub: str = ""):
    """A brand-navy placeholder panel with a dot grid and centred text."""
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (W, H), NAVY)
    d = ImageDraw.Draw(img)
    for y in range(24, H, 48):
        for x in range(24, W, 48):
            d.ellipse((x - 1, y - 1, x + 1, y + 1), fill=(36, 62, 88))
    wrap_text(d, text, (60, 60, W - 60, H - 100), CREAM, 54, align="center", valign="center")
    if sub:
        wrap_text(d, sub, (60, H - 90, W - 60, H - 30), BLUE_LT, 22, align="center", valign="center")
    return img


def wrap_text(d, text: str, box, fill, size: int, align="left", valign="top", min_size=16):
    """Fit `text` in box by shrinking the font; returns the font size used."""
    x0, y0, x1, y1 = box
    paras = [" ".join(p.split()) for p in text.split("\n") if p.strip()] or [""]      # a new line in the text starts a new line on the card (lists)
    while True:
        f = font(size)
        lines = []
        for para in paras:
            cur = ""
            for w in para.split():
                t = (cur + " " + w).strip()
                if d.textlength(t, font=f) <= x1 - x0 or not cur:
                    cur = t
                else:
                    lines.append(cur)
                    cur = w
            lines.append(cur)
        lh = int(size * 1.25)
        if lh * len(lines) <= y1 - y0 or size <= min_size:
            break
        size -= 2
    total = lh * len(lines)
    y = y0 + ((y1 - y0 - total) // 2 if valign == "center" else 0)
    for ln in lines:
        w = d.textlength(ln, font=f)
        x = x0 + ((x1 - x0 - w) // 2 if align == "center" else 0)
        d.text((x, y), ln, font=f, fill=fill)
        y += lh
    return size


REGIONS = {"lower": (0.05, 0.60, 0.95, 0.95), "right": (0.54, 0.08, 0.97, 0.92), "left": (0.03, 0.08, 0.46, 0.92),
           "full": (0.0, 0.0, 1.0, 1.0),                                   # edge to edge: nothing of the frame behind shows
           "left35": (0.0, 0.0, 0.35, 1.0),                                # a column down the left, 35% of the width
           "right35": (0.65, 0.0, 1.0, 1.0),                               # a column down the right, 35% of the width
           "bl33": (0.02, 0.60, 0.35, 0.97)}                               # bottom-left corner, 33% of the width
PLACES = ("", "auto", "full", "left35", "right35", "bl33")                            # graphic.place: where the creator wants a graphic
ORDER = {"ui": ["right", "left", "lower"], "explainer": ["right", "left", "lower"], "3d": ["right", "left", "lower"]}


def region_box(name: str):
    a, b, c, d = REGIONS[name]
    return (int(a * W), int(b * H), int(c * W), int(d * H))


def overlap(box, face) -> float:
    """Share of the face box covered by the region."""
    fx, fy, fw, fh = face
    ix = max(0, min(box[2], fx + fw) - max(box[0], fx))
    iy = max(0, min(box[3], fy + fh) - max(box[1], fy))
    return (ix * iy) / max(1, fw * fh)


def draw_card(base, box, g: dict, opaque: bool = False):
    """A DRAFT card for a graphic, in the brand style, composited over `base` inside `box`.
    A full-frame card is opaque so nothing from the frame behind it shows through."""
    from PIL import Image, ImageDraw
    x0, y0, x1, y1 = box
    layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    d.rounded_rectangle((x0 + 4, y0 + 8, x1 + 4, y1 + 8), 28, fill=(0, 0, 0, 70))
    d.rounded_rectangle(box, 28, fill=NAVY + (255 if opaque else 238,))
    chip = (g.get("kind") or "graphic").upper()
    cf = font(20)
    cw = int(d.textlength(chip, font=cf)) + 28
    d.rounded_rectangle((x0 + 20, y0 + 18, x0 + 20 + cw, y0 + 54), 18, fill=ORANGE + (255,))
    d.text((x0 + 34, y0 + 22), chip, font=cf, fill=CREAM)
    d.text((x1 - 100, y0 + 24), "DRAFT", font=font(16), fill=BLUE_LT + (255,))
    head = g.get("text") or g.get("idea") or "(no idea written)"
    foot = f"timed to: “{g['words']}”" if g.get("words") else ""
    inner = (x0 + 24, y0 + 70, x1 - 24, y1 - (56 if foot else 24))
    size = 52
    if "\n" in head:                                   # a list: each item on one line, so shrink until the longest fits
        f = font(size)
        while size > 20 and max(d.textlength(p.strip(), font=font(size)) for p in head.split("\n")) > inner[2] - inner[0]:
            size -= 2
    wrap_text(d, head, inner, CREAM + (255,), size, valign="center")
    if foot:
        wrap_text(d, foot, (x0 + 24, y1 - 50, x1 - 24, y1 - 14), BLUE_LT + (255,), 18)
    return Image.alpha_composite(base.convert("RGBA"), layer).convert("RGB")


def paste_draft(base, box, path: str):
    """Place Claude's own draft still of the real graphic into `box`, keeping its aspect ratio."""
    from PIL import Image
    im = Image.open(path).convert("RGBA")
    bw, bh = box[2] - box[0], box[3] - box[1]
    s = min(bw / im.width, bh / im.height)
    im = im.resize((max(1, int(im.width * s)), max(1, int(im.height * s))))
    out = base.convert("RGBA")
    out.alpha_composite(im, (box[0] + (bw - im.width) // 2, box[1] + (bh - im.height) // 2))
    return out.convert("RGB")


def punch_crop(img, faces_found, zoom: float):
    cw, ch = int(W / zoom), int(H / zoom)
    if faces_found:
        fx, fy, fw, fh = faces_found[0]
        cx, top = fx + fw / 2, fy + fh / 2 - ch * 0.33          # face centre in the upper third
    else:
        cx, top = W / 2, H * 0.45 - ch / 2
    x = int(min(max(0, cx - cw / 2), W - cw))
    y = int(min(max(0, top), H - ch))
    return img.crop((x, y, x + cw, y + ch)).resize((W, H))


def compose(b: dict, folder: Path | None, use_faces: bool):
    """-> (image, flags, meta) for one beat."""
    import facedet
    import numpy as np
    flags = []
    add = lambda level, text: flags.append({"level": level, "text": text})
    on = b["on_screen"]
    shot = on.get("shot", "a-roll")
    g = b.get("graphic")
    g = g if g and not g.get("struck") else None
    a = b.get("aroll")
    base, from_footage = None, False

    def aroll_frame():
        if not a or not folder:
            return None
        p = folder / a["rel"]
        if not p.exists():
            add("fix", f"footage file not found: {a['rel']}")
            return None
        try:
            k = a.get("keep")                           # a trimmed beat: the middle of its first kept piece (the middle of in..out can fall in a cut-out silence)
            return grab(p, (k[0][0] + k[0][1]) / 2 if k else a["in"] + 0.45 * (a["out"] - a["in"]))
        except (RuntimeError, subprocess.TimeoutExpired) as e:
            add("fix", f"could not read a frame: {e}")
            return None

    if shot in ("a-roll", "punch-in"):
        base = aroll_frame()
        from_footage = base is not None
        if base is None and not b.get("missing"):
            base = panel("A-roll", base_note(b))
        if b.get("missing"):
            base = panel("No footage yet", " ".join(b["script_lines"]) + ": record this line")
            add("fix", "no footage for this line yet")
    elif shot == "b-roll":
        br = next((x for x in on.get("broll", []) if x.get("file")), None)
        if br and folder:
            p = Path(br["file"]) if Path(br["file"]).is_absolute() else folder / br["file"]
            if p.exists():
                try:
                    base = grab(p, float(br.get("in") or 0) + float(br.get("dur") or 2) / 2)
                    from_footage = True
                except (RuntimeError, subprocess.TimeoutExpired) as e:
                    add("fix", f"could not read B-roll: {e}")
            else:
                add("fix", f"B-roll file not found: {br['file']}")
        if base is None:
            base = panel("B-roll", (br or {}).get("file") or on.get("note") or "no insert listed")
        if not on.get("broll"):
            add("look", "B-roll shot but no insert is listed in the beat map")
    elif shot == "graphic" and g:                      # the graphic card is drawn over a plain panel below
        base = panel("")
    else:                                              # screenshot, text card, a full-frame graphic that was cut
        base = panel(on.get("note") or {"screenshot": "Screenshot", "text": "Text card", "graphic": "Full-frame graphic"}.get(shot, shot))

    found = []
    if from_footage and shot in ("a-roll", "punch-in"):
        if shot == "punch-in":
            if use_faces:
                found = facedet.faces(np.array(base)[:, :, ::-1])
            base = punch_crop(base, found, float(on.get("zoom") or 1.6))
            add("look", "punch-in framing is approximate; the real zoom is planned in the build")
        if use_faces:
            found = facedet.faces(np.array(base)[:, :, ::-1])
    region = ""
    if g:
        place = g.get("place") if g.get("place") in REGIONS else ""
        full = place == "full" or (not place and (shot in ("graphic",) or g.get("kind") in ("title", "end") or not from_footage and shot not in ("a-roll", "punch-in", "b-roll")))
        draft = g.get("draft") if g.get("draft") and Path(g["draft"]).exists() else None
        if g.get("draft") and not draft:
            add("look", "graphic.draft file not found: using the generic draft card")
        if full:
            region = "full"
            box = region_box("full")
            base = paste_draft(base, box, draft) if draft else draw_card(base, box, g, opaque=True)
        else:
            order = [place] if place else ORDER.get(g.get("kind"), ["lower", "right", "left"])
            if found:
                scored = sorted(((max(overlap(region_box(r), f) for f in found), i, r) for i, r in enumerate(order)))
                ov, _, region = scored[0]
                if ov > 0.02:
                    add("fix", f"a graphic would cover your face ({int(ov * 100)}%) in every spot tried: move it, shrink it or use a full-frame graphic")
            else:
                region = order[0]
                if from_footage:
                    add("look", "face check unavailable" if not use_faces else "no face found in this frame: graphic placement not checked")
            box = region_box(region)
            base = paste_draft(base, box, draft) if draft else draw_card(base, box, g)
    meta = {"shot": shot, "kind": g.get("kind") if g else "", "region": region, "faces": len(found), "flags": flags}
    return base, flags, meta


def base_note(b):
    return b["on_screen"].get("note") or ""


# ----------------------------------------------------------------------------- build
def esc(s):
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def write_index(work: str, name: str, beats: list, frames: dict):
    rows, sec = [], None
    for b in beats:
        if b.get("section") != sec:
            sec = b.get("section")
            rows.append(f"<h2>{esc(sec)}</h2>" if sec else "")
        f = frames.get(b["id"])
        if not f:
            continue
        flags = "".join(f"<li class='{x['level']}'>{esc(x['text'])}</li>" for x in f["flags"])
        rows.append(f"<figure><img src='{f['img']}' loading='lazy'><figcaption><b>{b['id']}</b> {', '.join(b['script_lines'])} · "
                    f"{b.get('start', 0):.0f}s · {esc(f['shot'])}{(' · ' + esc(f['kind'])) if f['kind'] else ''}<br>{esc(b['said'][:140])}"
                    f"<ul>{flags}</ul></figcaption></figure>")
    html = ("<!doctype html><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
            f"<title>Storyboard: {esc(name)}</title><style>body{{background:#0C1B2B;color:#F4EDE4;font:15px Segoe UI,sans-serif;margin:16px}}"
            "h2{color:#A9CDE8;margin:24px 0 8px}figure{display:inline-block;width:300px;margin:6px;vertical-align:top}"
            "img{width:100%;border-radius:8px}figcaption{font-size:12px;color:#8FA9C2}ul{margin:4px 0;padding-left:16px}"
            "li.fix{color:#E2703A}li.look{color:#D9B44A}</style>"
            f"<h1>Storyboard: {esc(name)}</h1>" + "".join(rows))
    (sb_dir(work) / "index.html").write_text(html, encoding="utf-8")


def build(work: str, name: str, full: bool = False) -> dict:
    import facedet
    bm, beats = beats_of(work, name)
    if not bm:
        raise ValueError("no beat map yet")
    d = sb_dir(work)
    d.mkdir(exist_ok=True)
    fj = read_json(d / "frames.json") or {}
    old = fj.get("frames") or {}
    cfg = read_json(WORK / work / f"{name}.footage.json") or {}
    folder = Path(cfg["folder"]) if cfg.get("folder") else None
    if folder and not folder.is_dir():
        print(f"warning: footage folder not found: {folder}", flush=True)
        folder = None
    use_faces = facedet.available()
    if not use_faces:
        print("warning: no face model: graphics go in a default spot and frames are flagged", flush=True)
    frames, made, kept = {}, 0, 0
    for b in beats:
        sig = beat_sig(b)
        prev = old.get(b["id"])
        img_path = d / f"{b['id']}.jpg"
        if prev and prev["sig"] == sig and img_path.exists() and not full:
            frames[b["id"]] = prev
            kept += 1
            continue
        img, flags, meta = compose(b, folder, use_faces)
        img.resize((W, H)).save(img_path, quality=86)
        frames[b["id"]] = {"img": img_path.name, "sig": sig, **meta}
        made += 1
        print(f"FRAME {b['id']} {meta['shot']}{(' + ' + meta['kind']) if meta['kind'] else ''}"
              f"{' [' + str(len(flags)) + ' flags]' if flags else ''}", flush=True)
    for gone in [k for k in old if k not in frames]:     # beats that were removed or left out
        (d / f"{gone}.jpg").unlink(missing_ok=True)
    write_json(d / "frames.json", {"generated": time.strftime("%Y-%m-%dT%H:%M:%S"), "beatmap_version": bm.get("version", 1),
                                   "face_model": use_faces, "size": [W, H], "frames": frames})
    write_index(work, name, beats, frames)
    print(f"{made} frames made, {kept} unchanged", flush=True)
    return state(work, name)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["build", "check"])
    ap.add_argument("work")
    ap.add_argument("name")
    ap.add_argument("--all", action="store_true")
    a = ap.parse_args()
    try:
        s = build(a.work, a.name, a.all) if a.cmd == "build" else state(a.work, a.name)
    except ValueError as e:
        sys.exit(f"storyboard: {e}")
    c = s["counts"]
    print(f"{s['total']} frames: {c['ok']} OK, {c['change']} need changes, {c['unseen']} unseen, {c['outdated']} outdated, "
          f"{c['unbuilt']} not built; {s['fix_flags']} with a problem")


if __name__ == "__main__":
    main()
