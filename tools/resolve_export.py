"""Export the stitched video as a rough-cut timeline for DaVinci Resolve (stage "Send to Resolve", a button on the Dashboard).

Usage (editor venv):
    python resolve_export.py <work> <name>        # writes <work>\\resolve\\ : the timeline files, a README and export.json

The timeline is built from exactly what the stitched preview was built from (selfreview.timeline: the section render.json + section.edit.json files) and the
final render's audio plan (finalrender.audio_plan: music beds and sound effects resolved to files and times), so Resolve opens what the host watched:
  V1  the A-roll takes at the cuts the app made, pointing at the ORIGINAL recordings (not the half-size previews); voice-over beats show their B-roll picture
  V2+ B-roll (stabilized copies the app already made, rotation, zoom, slow motion)      V(top) the rendered HyperFrames graphics (ProRes 4444 with alpha)
  A1  the takes' own sound at the preview's per-take level     A2  voice-over     then sound effects, then music beds (one lane per overlap)
  markers for every section.
Two files are written because the import cannot be tested from here: FCPXML 1.8 (File > Import > Timeline) and Final Cut Pro 7 XML (xmeml 4), which Resolve also
imports. Nothing is copied: the files point at the sources where they are.
Not carried over: the voice chain, the music ducking and fades, the -14 LUFS loudness step, a pan across a clip (it is a fixed zoom with a marker) - see NOT_CARRIED.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from fractions import Fraction
from pathlib import Path
from urllib.parse import quote
from xml.sax.saxutils import quoteattr

HERE = Path(os.path.abspath(__file__)).parent
sys.path.insert(0, str(HERE))
import config  # noqa: E402
import finalrender  # noqa: E402
import sectionrender  # noqa: E402
import selfreview  # noqa: E402
import workflow  # noqa: E402

WORK = finalrender.WORK
FPS = finalrender.FPS
W, H = finalrender.SIZE
SPEECH_REF_LUFS = sectionrender.LEVEL_TARGET          # every take of the previews is levelled to about this, so the music is set relative to it

NOT_CARRIED = [
    "Your voice processing (the warmer, less bright voice) and the -14 LUFS loudness step of the final render: the takes come in with their original sound, levelled the way the preview was.",
    "The music dip while you talk and the music fades: each music bed is one clip at the level it has while you talk. Drag the fade handles in Resolve.",
    "Anything the app did with sound inside B-roll: B-roll is picture only here too.",
]


def say(msg):
    print(msg, flush=True)


# ----------------------------------------------------------------------------- numbers as the formats write them
def rat(x) -> str:
    """FCPXML time: a rational number of seconds."""
    x = Fraction(x)
    if x == 0:
        return "0s"
    return f"{x.numerator}s" if x.denominator == 1 else f"{x.numerator}/{x.denominator}s"


def tl(frames: int) -> Fraction:
    return Fraction(int(frames), FPS)


def snap_t(sec: float, rate: Fraction) -> Fraction:
    """A time in a source moved onto that source's own frame grid."""
    return Fraction(round(Fraction(sec) * rate)) / rate if rate else Fraction(round(sec * 1000), 1000)


def fr(sec: float) -> int:
    return int(round(float(sec) * FPS))


def zpath(p) -> str:
    """A network share as this PC maps it. With `share_map` in config.local.json ({"\\\\server\\share\\": "Z:\\"}) the UNC name becomes the drive letter, because Resolve and the beat map use the letter. No map: the path is unchanged."""
    s = str(p).replace("/", "\\")
    for unc, drive in (config._local().get("share_map") or {}).items():
        if s.lower().startswith(unc.lower()):
            return drive + s[len(unc):]
    return s


def file_url(p: str, localhost: bool = False) -> str:
    u = Path(p).as_uri()                                          # file:///Z:/dir/a%20b.mkv
    return u.replace("file:///", "file://localhost/", 1) if localhost else u


# ----------------------------------------------------------------------------- what is in a file (cached)
def _probe_cache_path(work: str) -> Path:
    return WORK / work / "resolve" / "probe-cache.json"


def probe(path: str, cache: dict) -> dict:
    p = Path(path)
    try:
        s = p.stat()
    except OSError:
        return {"path": path, "missing": True}
    key = f"{path}|{s.st_size}|{int(s.st_mtime)}|v2"
    if key in cache:
        return cache[key]
    r = subprocess.run([sectionrender.FFPROBE, "-v", "error", "-show_entries",
                        "stream=codec_type,codec_name,width,height,r_frame_rate,sample_rate,channels:format=duration", "-of", "json", path], capture_output=True, text=True)
    info = {"path": path, "dur": 0.0, "has_v": False, "has_a": False, "w": 0, "h": 0, "fps": "0/1", "ach": 0, "arate": 48000}
    try:
        j = json.loads(r.stdout or "{}")
    except ValueError:
        j = {}
    info["dur"] = float((j.get("format") or {}).get("duration") or 0)
    for st in j.get("streams") or []:
        if st.get("codec_type") == "video" and not info["has_v"]:
            info.update(has_v=True, w=int(st.get("width") or 0), h=int(st.get("height") or 0), fps=st.get("r_frame_rate") or "30/1")
        elif st.get("codec_type") == "audio" and not info["has_a"]:
            info.update(has_a=True, acodec=st.get("codec_name") or "", ach=int(st.get("channels") or 2), arate=int(st.get("sample_rate") or 48000))
    cache[key] = info
    return info


def fps_of(info: dict) -> Fraction:
    try:
        n, _, d = info["fps"].partition("/")
        return Fraction(int(n), int(d or 1))
    except (ValueError, ZeroDivisionError):
        return Fraction(30)


def stab_cached(file: str, ss: float, dur: float, cache_dir: Path):
    """The stabilized copy the section previews already made of file[ss:ss+dur] (sectionrender.stabilized), or None when it is not there: never makes one."""
    try:
        import hashlib
        st = Path(file).stat()
        key = hashlib.sha1(f"{file}|{st.st_size}|{int(st.st_mtime)}|{ss:.2f}|{dur:.2f}|v1".encode()).hexdigest()[:12]
        out = cache_dir / f"stab_{key}.mp4"
        return str(out) if out.exists() else None
    except OSError:
        return None


def convert_sony(work: str, src: str, warns: list) -> str:
    """Copy of src in the work folder's resolve/media with the picture copied as it is and the sound as 16-bit little-endian PCM in a .mov (made once)."""
    d = WORK / work / "resolve" / "media"
    d.mkdir(parents=True, exist_ok=True)
    out = d / (Path(src).stem + ".mov")
    s = Path(src).stat()
    if not out.exists() or out.stat().st_mtime < s.st_mtime:
        tmp = out.with_name(out.stem + ".part.mov")
        say(f"  converting {Path(src).name} ({s.st_size / 1e6:.0f} MB)")
        r = subprocess.run([sectionrender.FFMPEG, "-nostdin", "-y", "-v", "error", "-i", src, "-map", "0:v:0", "-map", "0:a:0?", "-c:v", "copy", "-c:a", "pcm_s16le",
                            "-movflags", "+faststart", str(tmp)], capture_output=True, text=True)
        if r.returncode != 0:
            warns.append(f"could not make a Resolve-friendly copy of {Path(src).name}: {r.stderr.strip()[-150:]}")
            return src
        os.replace(tmp, out)
    return zpath(out)


# ----------------------------------------------------------------------------- the timeline model
def pack(items: list) -> int:
    """Give every item a lane (0, 1, ...) so that items on one lane never overlap; returns how many lanes were needed."""
    ends: list = []
    for it in sorted(items, key=lambda x: (x["start"], x["dur"])):
        for i, e in enumerate(ends):
            if e <= it["start"]:
                it["lane"], ends[i] = i, it["start"] + it["dur"]
                break
        else:
            it["lane"] = len(ends)
            ends.append(it["start"] + it["dur"])
    return len(ends)


def build(work: str, name: str) -> dict:
    """The whole timeline as plain data: spine (V1 + A1), then lists of connected items with lanes, markers, the media they use and the warnings."""
    T = selfreview.timeline(work, name)
    plan = finalrender.audio_plan(work, name)
    settings = {**workflow.DEFAULT_SETTINGS, **workflow.load(work, name)["settings"]}
    cache = {}
    pc = _probe_cache_path(work)
    try:
        cache = json.loads(pc.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        cache = {}
    warns: list = []
    segs = T["segments"]
    starts, t = [], 0
    for s in segs:
        starts.append(t)
        t += fr(s["out_dur"])
    total = t
    seg_ix = {s["id"]: i for i, s in enumerate(segs)}
    media: dict = {}

    def use(path: str) -> dict:
        if path not in media:
            media[path] = probe(path, cache)
            if media[path].get("missing"):
                warns.append(f"file not found, the clip will be offline in Resolve: {path}")
        return media[path]

    spine, vo_audio, broll, graphics, sfx, music, markers = [], [], [], [], [], [], []
    for i, s in enumerate(segs):
        n = fr(s["out_dur"])
        info = use(s["src"])
        va = s.get("audio_src")
        has_sound = bool(info.get("has_a")) and not s.get("mute") and not va
        z, cx, cy = float(s.get("zoom") or 1.0), float(s.get("cx", 0.5)), float(s.get("cy", 0.4))
        item = {"kind": "av" if has_sound else "v", "name": s["id"], "file": s["src"], "start": starts[i], "dur": n, "src_in": float(s["in"]), "speed": 1.0,
                "gain_db": float(s.get("gain_db") or 0.0) if has_sound else 0.0, "scale": z, "section": s.get("section"),
                "dx": -W * (z - 1.0) * (cx - 0.5) if z > 1.0 else 0.0, "dy": -H * (z - 1.0) * (cy - 0.5) if z > 1.0 else 0.0, "rot": 0}
        spine.append(item)
        if va:                                                      # a voice-over beat: the picture is a B-roll clip, the sound is the voice-over recording
            ai = use(va)
            vo_audio.append({"kind": "a", "name": f"{s['id']} voice-over", "file": va, "start": starts[i], "dur": n, "src_in": float(s.get("audio_in", 0)), "speed": 1.0,
                             "gain_db": float(s.get("gain_db") or 0.0)})
    for b in T["broll"]:
        i = seg_ix.get(b["seg"])
        if i is None:
            continue
        at = fr(b.get("at", 0.5))
        n = min(fr(b["dur"]), fr(segs[i]["out_dur"]) - at)
        if n <= 0:
            pieces = [x for x in segs if x["id"].split(".")[0] == b["seg"].split(".")[0]]
            warns.append(f"{b['seg']}: the B-roll {Path(b['file']).name} is planned {at / FPS:.1f} s into the beat, " + (
                "after a cut inside it; the app only shows B-roll over the first piece of a trimmed beat, so the stitched preview does not show it either (left out; add it in Resolve if you want it)"
                if len(pieces) > 1 else f"but the take is only {fr(segs[i]['out_dur']) / FPS:.1f} s long, so the stitched preview does not show it either: left out"))
            continue
        sp = float(b.get("speed") or 1.0)
        f, src_in, notes = b["file"], float(b.get("in") or 0.0), []
        if b.get("stabilize"):
            sc = stab_cached(f, src_in, float(b["dur"]) * sp, WORK / work / "sections" / name / b["section"] / "out" / "stab")
            if sc:
                f, src_in = zpath(sc), 0.0
            else:
                notes.append("stabilize")
                warns.append(f"{b['seg']}: its stabilized copy is not there, the plain clip is used (turn on Stabilizer in Resolve)")
        use(f)
        zoom = float(b.get("zoom") or 1.0)
        rot = {0: 0, 180: 180, 90: -90, 270: 90}.get(int(b.get("rotate") or 0) % 360, 0)
        if int(b.get("rotate") or 0) % 360 in (90, 270):
            notes.append("rotated 90 degrees: check the fit")
        if b.get("pan") and zoom > 1.0:
            notes.append(f"the app panned {b['pan']} across this clip; here it is a fixed {zoom:g}x zoom: add a Position keyframe")
        if abs(sp - 1.0) > 0.01:
            notes.append(f"slow motion {sp:g}x")
        broll.append({"kind": "v", "name": f"{b['seg']} B-roll · {Path(b['file']).stem}", "file": f, "start": starts[i] + at, "dur": n, "src_in": src_in, "speed": sp,
                      "gain_db": 0.0, "scale": zoom, "dx": 0.0, "dy": 0.0, "rot": rot, "notes": notes})
    for o in T["overlays"]:
        i = seg_ix.get(o["seg"])
        if i is None:
            continue
        at = fr(o.get("at", 0.0))
        n = min(fr(o["dur"]), fr(segs[i]["out_dur"]) - at)
        if n <= 0:
            continue
        use(o["file"])
        graphics.append({"kind": "v", "name": f"{o['seg']} graphic", "file": o["file"], "start": starts[i] + at, "dur": n, "src_in": float(o.get("in") or 0.0), "speed": 1.0,
                         "gain_db": 0.0, "scale": 1.0, "dx": 0.0, "dy": 0.0, "rot": 0, "alpha": True})
    for x in plan["sfx"]:
        a = fr(x["t"])
        if a >= total:
            continue
        inf = use(x["file"])
        n = max(1, min(fr(inf.get("dur") or 1.0), total - a))
        sfx.append({"kind": "a", "name": f"SFX · {x['name']}", "file": x["file"], "start": a, "dur": n, "src_in": 0.0, "speed": 1.0, "gain_db": round(sectionrender.sfx_gain(x["file"]), 1)})
    below, duck = float(settings["music_below_speech_db"]), float(settings["duck_db"])
    loud_cache = {}
    for k, bed in enumerate(plan["beds"]):
        a, b = fr(bed["start"]), min(total, fr(bed["end"]))
        if b - a < FPS:
            continue
        inf = use(bed["file"])
        if bed["file"] not in loud_cache:
            loud_cache[bed["file"]] = sectionrender.measure_lufs(bed["file"], 0.0, 60.0)
        loud = loud_cache[bed["file"]]
        gain = round(max(-60.0, min(12.0, (SPEECH_REF_LUFS - below - duck) - loud)), 1) if loud is not None else -30.0
        tl_len = fr(inf.get("dur") or 0.0) or (b - a)
        pos = a
        while pos < b:                                              # a track shorter than its bed plays again (the final render loops it with a crossfade)
            n = min(tl_len, b - pos)
            music.append({"kind": "a", "name": f"Music · {bed['name']}", "file": bed["file"], "start": pos, "dur": n, "src_in": 0.0, "speed": 1.0, "gain_db": gain})
            pos += n
    first_of = {}
    for i, s in enumerate(segs):
        first_of.setdefault(s["section"], i)
    for sec in T["stitch"]["sections"]:
        if sec["id"] in first_of:
            title = re.sub(r"\s*\(\d+:\d\d\s*-\s*\d+:\d\d\)\s*$", "", sec.get("title") or "")          # the plan's old time range is not the stitched one
            markers.append({"frame": starts[first_of[sec["id"]]], "text": f"{sec['id']} {title}".strip(), "color": "blue"})
    for it in broll + graphics:
        for nt in it.get("notes") or []:
            markers.append({"frame": it["start"], "text": f"{it['name'].split(' ')[0]}: {nt}", "color": "red"})
    remap = {}
    for p0, inf in list(media.items()):                              # Sony .MP4 files with big-endian PCM sound: Resolve lists them as missing; a copy with the same picture and little-endian sound opens
        if inf.get("acodec") == "pcm_s16be" and inf.get("has_v"):
            remap[p0] = convert_sony(work, p0, warns)
    if remap:
        for lst in (spine, broll, graphics, vo_audio, sfx, music):
            for it in lst:
                it["file"] = remap.get(it["file"], it["file"])
        for p0, p1 in remap.items():
            media[p1] = probe(p1, cache)
            del media[p0]
    n_b, n_g = pack(broll), pack(graphics)
    n_vo, n_s, n_m = pack(vo_audio), pack(sfx), pack(music)
    try:
        pc.parent.mkdir(parents=True, exist_ok=True)
        pc.write_text(json.dumps(cache), encoding="utf-8")
    except OSError:
        pass
    return {"title": finalrender.title_of(work, name), "total": total, "spine": spine, "broll": broll, "graphics": graphics, "vo": vo_audio, "sfx": sfx, "music": music,
            "lanes": {"broll": n_b, "graphics": n_g, "vo": n_vo, "sfx": n_s, "music": n_m}, "markers": sorted(markers, key=lambda m: m["frame"]),
            "media": media, "warnings": warns, "stitch": {"file": T["stitch"].get("file"), "stitched": T["stitch"].get("stitched")}}


# ----------------------------------------------------------------------------- FCPXML 1.8
def _q(s) -> str:
    return quoteattr(str(s))


def write_fcpxml(M: dict, path: Path):
    media = M["media"]
    res, ids, fmts = [], {}, {}
    res.append(f'<format id="r1" name="FFVideoFormat1080p30" frameDuration="1/{FPS}s" width="{W}" height="{H}"/>')

    def fmt_of(info) -> str:
        key = (info["fps"], info["w"], info["h"])
        if key not in fmts:
            rate = fps_of(info)
            fmts[key] = f"r{2 + len(fmts)}"
            res.append(f'<format id="{fmts[key]}" frameDuration="{rat(1 / rate)}" width="{info["w"]}" height="{info["h"]}"/>')
        return fmts[key]
    for p, info in media.items():
        if info.get("missing"):
            continue
        rid = f"a{len(ids) + 1}"
        ids[p] = rid
        attrs = [f'id="{rid}"', f"name={_q(Path(p).name)}", 'start="0s"', f'duration="{rat(Fraction(round(info["dur"] * 1000), 1000))}"']
        if info["has_v"]:
            attrs += ['hasVideo="1"', f'format="{fmt_of(info)}"']
        if info["has_a"]:
            attrs += ['hasAudio="1"', 'audioSources="1"', f'audioChannels="{max(1, min(2, info["ach"]))}"', f'audioRate="{info["arate"]}"']
        attrs.append(f"src={_q(file_url(p))}")
        res.append("<asset " + " ".join(attrs) + "/>")

    def src_time(it) -> Fraction:
        info = media.get(it["file"]) or {}
        return snap_t(it["src_in"], fps_of(info)) if info.get("has_v") else Fraction(round(it["src_in"] * 48000), 48000)

    def clip_xml(it, tag, offset, indent, lane=None, children="") -> str:
        info = media.get(it["file"])
        if not info or info.get("missing"):
            return ""
        start = src_time(it)
        dur = tl(it["dur"])
        a = [f'ref="{ids[it["file"]]}"', f'lane="{lane}"' if lane else "", f"offset={_q(rat(offset))}", f"name={_q(it['name'])}", f"start={_q(rat(start))}", f"duration={_q(rat(dur))}"]
        if tag == "asset-clip":
            a.append('tcFormat="NDF"')
        if tag != "audio" and info.get("has_v") is False:
            return ""
        body = ""
        sp = float(it.get("speed") or 1.0)
        if abs(sp - 1.0) > 0.01:                                    # constant slow motion: local time 0..dur plays source time start .. start + dur * speed
            a[4] = f"start={_q('0s')}"
            body += f'<timeMap><timept time="0s" value={_q(rat(start))} interp="linear"/><timept time={_q(rat(dur))} value={_q(rat(start + dur * Fraction(sp).limit_denominator(1000)))} interp="linear"/></timeMap>'
        if tag != "audio" and (abs(float(it.get("scale", 1.0)) - 1.0) > 1e-6 or abs(it.get("dx", 0)) > 0.5 or abs(it.get("dy", 0)) > 0.5 or it.get("rot")):
            sc = float(it.get("scale", 1.0))
            body += (f'<adjust-transform position="{it.get("dx", 0) / H * 100 + 0.0:.4f} {-it.get("dy", 0) / H * 100 + 0.0:.4f}" scale="{sc:.4f} {sc:.4f}" rotation="{it.get("rot", 0)}"/>')
        if tag != "video" and abs(float(it.get("gain_db") or 0.0)) > 0.04:
            body += f'<adjust-volume amount="{float(it["gain_db"]):.1f}dB"/>'
        inner = body + children
        a = " ".join(x for x in a if x)
        return f"{indent}<{tag} {a}>{inner}</{tag}>\n" if inner else f"{indent}<{tag} {a}/>\n"

    # connected items: video lanes 1.. (B-roll, then graphics above), audio lanes -1.. (voice-over, SFX, music)
    conn = []
    for it in M["broll"]:
        conn.append((it, "video", 1 + it["lane"]))
    for it in M["graphics"]:
        conn.append((it, "video", 1 + M["lanes"]["broll"] + it["lane"]))
    for it in M["vo"]:
        conn.append((it, "audio", -(1 + it["lane"])))
    for it in M["sfx"]:
        conn.append((it, "audio", -(1 + M["lanes"]["vo"] + it["lane"])))
    for it in M["music"]:
        conn.append((it, "audio", -(1 + M["lanes"]["vo"] + M["lanes"]["sfx"] + it["lane"])))
    spine = M["spine"]
    kids = {i: [] for i in range(len(spine))}
    for it, tag, lane in conn:
        for i, sp_ in enumerate(spine):
            if sp_["start"] <= it["start"] < sp_["start"] + sp_["dur"]:
                kids[i].append((it, tag, lane))
                break
    marks = {i: [] for i in range(len(spine))}
    for m in M["markers"]:
        for i, sp_ in enumerate(spine):
            if sp_["start"] <= m["frame"] < sp_["start"] + sp_["dur"]:
                marks[i].append(m)
                break
    out = []
    for i, sp_ in enumerate(spine):
        parent_start = src_time(sp_)
        ch = ""
        for it, tag, lane in kids[i]:
            ch += clip_xml(it, tag, parent_start + tl(it["start"] - sp_["start"]), "", lane=lane)
        for m in marks[i]:
            ch += f'<marker start={_q(rat(parent_start + tl(m["frame"] - sp_["start"])))} duration="1/{FPS}s" value={_q(m["text"])}/>'
        out.append(clip_xml(sp_, "asset-clip" if sp_["kind"] == "av" else "video", tl(sp_["start"]), "      ", children=ch))
    xml = ('<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE fcpxml>\n<fcpxml version="1.8">\n  <resources>\n    ' + "\n    ".join(res) + "\n  </resources>\n"
           f'  <library>\n    <event name={_q(M["title"])}>\n      <project name={_q(M["title"] + " rough cut")}>\n'
           f'        <sequence format="r1" duration="{rat(tl(M["total"]))}" tcStart="0s" tcFormat="NDF" audioLayout="stereo" audioRate="48k">\n          <spine>\n'
           + "".join(out) + "          </spine>\n        </sequence>\n      </project>\n    </event>\n  </library>\n</fcpxml>\n")
    path.write_text(xml, encoding="utf-8")


# ----------------------------------------------------------------------------- Final Cut Pro 7 XML (xmeml 4)
def _rate_xml(rate: Fraction) -> str:
    ntsc = rate.denominator != 1
    tb = round(float(rate))
    return f"<rate><timebase>{tb}</timebase><ntsc>{'TRUE' if ntsc else 'FALSE'}</ntsc></rate>"


def write_xmeml(M: dict, path: Path):
    media = M["media"]
    file_ids: dict = {}
    clip_n = [0]
    seq_rate = _rate_xml(Fraction(FPS))

    def file_xml(p: str) -> str:
        info = media[p]
        if p in file_ids:
            return f'<file id="{file_ids[p]}"/>'
        file_ids[p] = f"file-{len(file_ids) + 1}"
        rate = fps_of(info) if info["has_v"] else Fraction(FPS)
        frames = round(info["dur"] * float(rate))
        s = f'<file id="{file_ids[p]}"><name>{xesc(Path(p).name)}</name><pathurl>{xesc(file_url(p, True))}</pathurl>{_rate_xml(rate)}<duration>{frames}</duration><media>'
        if info["has_v"]:
            s += (f'<video><samplecharacteristics>{_rate_xml(rate)}<width>{info["w"]}</width><height>{info["h"]}</height><anamorphic>FALSE</anamorphic>'
                  '<pixelaspectratio>square</pixelaspectratio><fielddominance>none</fielddominance></samplecharacteristics></video>')
        if info["has_a"]:
            s += f'<audio><samplecharacteristics><depth>16</depth><samplerate>{info["arate"]}</samplerate></samplecharacteristics><channelcount>{max(1, min(2, info["ach"]))}</channelcount></audio>'
        return s + "</media></file>"

    def level_filter(db: float) -> str:
        lin = 10 ** (db / 20)
        return ('<filter><effect><name>Audio Levels</name><effectid>audiolevels</effectid><effectcategory>audiolevels</effectcategory><effecttype>audiolevels</effecttype>'
                f'<mediatype>audio</mediatype><parameter><parameterid>level</parameterid><name>Level</name><valuemin>0</valuemin><valuemax>3.98109</valuemax><value>{lin:.5f}</value></parameter></effect></filter>')

    def motion_filter(it) -> str:
        sc, dx, dy, rot = float(it.get("scale", 1.0)), it.get("dx", 0.0), it.get("dy", 0.0), it.get("rot", 0)
        if abs(sc - 1.0) < 1e-6 and abs(dx) < 0.5 and abs(dy) < 0.5 and not rot:
            return ""
        return ('<filter><effect><name>Basic Motion</name><effectid>basic</effectid><effectcategory>motion</effectcategory><effecttype>motion</effecttype><mediatype>video</mediatype>'
                f'<parameter><parameterid>scale</parameterid><name>Scale</name><valuemin>0</valuemin><valuemax>1000</valuemax><value>{sc * 100:.2f}</value></parameter>'
                f'<parameter><parameterid>rotation</parameterid><name>Rotation</name><valuemin>-8640</valuemin><valuemax>8640</valuemax><value>{rot}</value></parameter>'
                f'<parameter><parameterid>center</parameterid><name>Center</name><value><horiz>{dx / W:.5f}</horiz><vert>{dy / H:.5f}</vert></value></parameter></effect></filter>')

    def speed_filter(sp: float) -> str:
        if abs(sp - 1.0) < 0.01:
            return ""
        return ('<filter><effect><name>Time Remap</name><effectid>timeremap</effectid><effectcategory>motion</effectcategory><effecttype>motion</effecttype><mediatype>video</mediatype>'
                '<parameter><parameterid>variablespeed</parameterid><name>variablespeed</name><valuemin>0</valuemin><valuemax>1</valuemax><value>0</value></parameter>'
                f'<parameter><parameterid>speed</parameterid><name>speed</name><valuemin>-100000</valuemin><valuemax>100000</valuemax><value>{sp * 100:.2f}</value></parameter>'
                '<parameter><parameterid>reverse</parameterid><name>reverse</name><value>FALSE</value></parameter>'
                '<parameter><parameterid>frameblending</parameterid><name>frameblending</name><value>FALSE</value></parameter></effect></filter>')

    def clip(it, mediatype: str, links: str = "") -> str:
        info = media.get(it["file"])
        if not info or info.get("missing"):
            return ""
        clip_n[0] += 1
        rate = fps_of(info) if info["has_v"] else Fraction(FPS)           # a take's sound uses its picture's rate: the same in-point, to the frame
        sp = float(it.get("speed") or 1.0)
        i0 = round(it["src_in"] * float(rate))
        span = round(it["dur"] / FPS * sp * float(rate))
        cid = it.setdefault("cid", f"clipitem-{clip_n[0]}")
        s = (f'<clipitem id="{cid}"><name>{xesc(it["name"])}</name><enabled>TRUE</enabled><duration>{round(info["dur"] * float(rate))}</duration>{_rate_xml(rate)}'
             f'<start>{it["start"]}</start><end>{it["start"] + it["dur"]}</end><in>{i0}</in><out>{i0 + span}</out>{file_xml(it["file"])}')
        if mediatype == "audio":
            s += f'<sourcetrack><mediatype>audio</mediatype><trackindex>1</trackindex></sourcetrack>'
            if abs(float(it.get("gain_db") or 0.0)) > 0.04:
                s += level_filter(float(it["gain_db"]))
        else:
            s += motion_filter(it) + speed_filter(sp)
        return s + links + "</clipitem>"

    def link(it, mt, ti, ci) -> str:
        return f'<link><linkclipref>{it["cid"]}</linkclipref><mediatype>{mt}</mediatype><trackindex>{ti}</trackindex><clipindex>{ci}</clipindex></link>'

    # V1 / A1: the spine, video and its own sound linked
    spine = M["spine"]
    v1, a1 = [], []
    for k, it in enumerate(spine, 1):
        if it["kind"] == "av":
            pair = dict(it)
            it["cid"] = f"clipitem-v{k}"
            pair["cid"] = f"clipitem-a{k}"
            lk = link(it, "video", 1, k) + link(pair, "audio", 1, k)
            v1.append(clip(it, "video", lk))
            a1.append(clip(pair, "audio", lk))
        else:
            it["cid"] = f"clipitem-v{k}"
            v1.append(clip(it, "video"))

    def lanes_xml(items, n, mediatype) -> str:
        out = ""
        for ln in range(max(n, 0)):
            xs = [clip(it, mediatype) for it in sorted(items, key=lambda x: x["start"]) if it["lane"] == ln]
            out += "<track>" + "".join(xs) + "<enabled>TRUE</enabled><locked>FALSE</locked></track>"
        return out
    vtracks = ("<track>" + "".join(v1) + "<enabled>TRUE</enabled><locked>FALSE</locked></track>" + lanes_xml(M["broll"], M["lanes"]["broll"], "video")
               + lanes_xml(M["graphics"], M["lanes"]["graphics"], "video"))
    atracks = ('<track totalExplodedTrackCount="2" premiereTrackType="Stereo">' + "".join(a1) + "<enabled>TRUE</enabled><locked>FALSE</locked></track>")
    for items, key in ((M["vo"], "vo"), (M["sfx"], "sfx"), (M["music"], "music")):
        for ln in range(M["lanes"][key]):
            xs = [clip(it, "audio") for it in sorted(items, key=lambda x: x["start"]) if it["lane"] == ln]
            atracks += '<track totalExplodedTrackCount="2" premiereTrackType="Stereo">' + "".join(xs) + "<enabled>TRUE</enabled><locked>FALSE</locked></track>"
    marks = "".join(f'<marker><name>{xesc(m["text"])}</name><comment></comment><in>{m["frame"]}</in><out>-1</out></marker>' for m in M["markers"])
    xml = ('<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE xmeml>\n<xmeml version="4">\n<sequence id="sequence-1">'
           f'<name>{xesc(M["title"])} rough cut</name><duration>{M["total"]}</duration>{seq_rate}'
           f'<timecode>{seq_rate}<string>00:00:00:00</string><frame>0</frame><displayformat>NDF</displayformat></timecode>'
           f'<media><video><format><samplecharacteristics>{seq_rate}<width>{W}</width><height>{H}</height><anamorphic>FALSE</anamorphic>'
           '<pixelaspectratio>square</pixelaspectratio><fielddominance>none</fielddominance><colordepth>24</colordepth></samplecharacteristics></format>'
           f'{vtracks}</video><audio><numOutputChannels>2</numOutputChannels><format><samplecharacteristics><depth>16</depth><samplerate>48000</samplerate></samplecharacteristics></format>'
           f'{atracks}</audio></media>{marks}</sequence>\n</xmeml>\n')
    path.write_text(xml, encoding="utf-8")


def xesc(s) -> str:
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


# ----------------------------------------------------------------------------- the whole export
README = """Opening "{title}" in DaVinci Resolve
====================================

1. In Resolve, set the project to 1920 x 1080 and 30 frames per second first (Project Settings > Master Settings), or import into a new project.
2. File > Import > Timeline... and pick  "{fcp}"
   Leave "Automatically import source clips into media pool" ticked. If Resolve asks where the media is, point it at {root} (nothing is copied; the
   timeline points at your recordings, the graphics in this video's work folder, and the Music and SFX folders in it).
3. If that file does not open well, try the second one:  "{xml}"  (File > Import > Timeline... as well; Resolve reads Final Cut Pro 7 XML too).

What is in it
-------------
{contents}

Not carried over
----------------
{not_carried}

Exported {when} from the stitched preview {stitched}. Export again after changing the video; it overwrites these files.
"""


def export(work: str, name: str) -> dict:
    t0 = time.time()
    M = build(work, name)
    out = WORK / work / "resolve"
    out.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r'[\\/:*?"<>|]+', " ", M["title"]).strip() or name
    f1 = out / f"{safe} - rough cut (FCPXML).fcpxml"
    f2 = out / f"{safe} - rough cut (FCP7 XML).xml"
    write_fcpxml(M, f1)
    write_xmeml(M, f2)
    n_av = sum(1 for x in M["spine"] if x["kind"] == "av")
    contents = [f"{len(M['spine'])} takes on V1 ({n_av} with their own sound on A1, {len(M['vo'])} voice-over beats with their B-roll picture)",
                f"{len(M['broll'])} B-roll clips (V2" + (f"-V{1 + M['lanes']['broll']}" if M["lanes"]["broll"] > 1 else "") + ")",
                f"{len(M['graphics'])} graphics (transparent ProRes 4444) above the B-roll",
                f"{len(M['sfx'])} sound effects, {len(M['music'])} music clips ({len(set(x['file'] for x in M['music']))} track{'s' if len(set(x['file'] for x in M['music'])) != 1 else ''})",
                f"{sum(1 for m in M['markers'] if m['color'] == 'blue')} section markers, {sum(1 for m in M['markers'] if m['color'] == 'red')} notes on clips that needed a manual touch"]
    when = time.strftime("%Y-%m-%d %H:%M")
    (out / "README - open in DaVinci Resolve.txt").write_text(README.format(root=zpath(config.DATA_ROOT), title=M["title"], fcp=f1.name, xml=f2.name, contents="\n".join("- " + c for c in contents),
                                                                          not_carried="\n".join("- " + c for c in NOT_CARRIED), when=when, stitched=M["stitch"].get("file") or ""),
                                                             encoding="utf-8")
    res = {"exported": time.strftime("%Y-%m-%dT%H:%M:%S"), "folder": zpath(out), "files": [f1.name, f2.name], "dur": round(M["total"] / FPS, 2), "total_frames": M["total"],
           "counts": {"takes": len(M["spine"]), "broll": len(M["broll"]), "graphics": len(M["graphics"]), "sfx": len(M["sfx"]), "music": len(M["music"]), "markers": len(M["markers"])},
           "lanes": M["lanes"], "contents": contents, "warnings": M["warnings"], "not_carried": NOT_CARRIED, "stitched_file": M["stitch"].get("file"),
           "elapsed": round(time.time() - t0, 1)}
    (out / "export.json").write_text(json.dumps(res, indent=1, ensure_ascii=False), encoding="utf-8")
    say(f"DONE {f1.name}, {f2.name}: {res['dur']:.1f} s, {res['counts']}")
    return res


def state(work: str, name: str) -> dict:
    """What the Dashboard shows: the last export (if any) and whether it is older than the stitched preview or the beat map."""
    d = WORK / work / "resolve"
    last = None
    try:
        last = json.loads((d / "export.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    sj = WORK / work / f"{name}.stitch.json"
    out = {"ready": sj.exists(), "why": "" if sj.exists() else "Make a preview first: the export is made from it.",
           "last": last, "folder": zpath(d), "not_carried": NOT_CARRIED, "stale": None}
    if last and sj.exists():
        try:
            t_exp = os.path.getmtime(d / last["files"][0])
            newer = [p.name for p in (sj, WORK / work / f"{name}.beatmap.json") if p.exists() and os.path.getmtime(p) > t_exp + 1]
            out["stale"] = ("changed since the last export: " + ", ".join(n.split(".")[-2] for n in newer)) if newer else None
        except OSError:
            pass
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("work")
    ap.add_argument("name")
    a = ap.parse_args()
    try:
        export(a.work, a.name)
    except (ValueError, RuntimeError) as e:
        sys.exit(f"resolve_export: {e}")


if __name__ == "__main__":
    main()
