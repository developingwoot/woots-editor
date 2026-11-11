"""Final render (stage 8): the full-quality video, built from the stitched half-size preview (unfinished work only warns).

Usage (editor venv; the app runs it as a job):
    python finalrender.py plan <work> <name>     # what would be mixed (music, SFX), what cannot be found, chapters: no rendering
    python finalrender.py run  <work> <name>     # renders "<title> vN (1080p).mp4" in the work folder (never overwrites)

What it does (the same cut lists as the preview, at full quality):
  1. picture: every section's section.edit.json + the SNAPPED cut points recorded in its render.json -> 1920x1080, 30 fps,
     NVENC cq 19, video only (sectionrender.py in "final" mode). Graphics are the full-size MOVs rendered by the Build step.
  2. speech: the voice chain (the host's "V2 warmer, less bright") runs on the CONTINUOUS source audio, filter delay compensated,
     then each take is cut at sample positions derived from the picture's frame counts (8 ms fades at joins).
  3. music + SFX from the beat map, by EXPLICIT name (see below), mixed like the old pipeline: each bed -26 LU under the speech,
     ducked a further 9 dB while the host talks (fast attack, slow release), 1.5 s crossfades, SFX scaled to the speech peak.
  4. loudness: two-pass loudnorm to -14 LUFS, -1.5 dBTP (YouTube); one AAC encode (192 kbps) muxed with the picture by stream copy.
  5. the final self-check on the finished FILE: frame count and duration, audio length, loudness and true peak, resolution, a contact
     sheet of every join; plus chapters.txt and description.txt from the beat map's sections.
Music / SFX in the beat map (beat.audio.music, beat.audio.sfx) are matched by name, never guessed:
    music  "TrackTribe - Boardwalk"          a file in <workspace>\\Music (name or enough of it to match exactly ONE file);
                                             consecutive beats with the same name share one bed; tracks the catalog marks as having vocals are refused
    sfx    "pop-up @ 1.2"  /  "ding @graphic"  a file in <workspace>\\SFX (any subfolder); "@ seconds" into the beat, "@graphic" = when
                                             the beat's graphic starts, no "@" = start of the beat
Anything that cannot be matched (or matches several files) is listed as NOT MIXED in the plan and in the result.
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(os.path.abspath(__file__)).parent
EDITOR = HERE.parent
import config
WORK = config.WORK
MUSIC_DIR = config.MUSIC_DIR
SFX_DIR = config.SFX_DIR
FPS = 30
SIZE = [1920, 1080]
FADE = 0.008
# The host's chosen "V2: warmer, less bright" (SKILL.md, Voice processing)
VOICE_CHAIN = ("highpass=f=70:poles=2,afftdn=nr=6:nf=-55:tn=1,equalizer=f=100:t=q:w=6:g=-4,lowshelf=f=220:g=1.5,"
               "equalizer=f=160:t=q:w=1.0:g=2.5,equalizer=f=450:t=q:w=1.4:g=-2.5,equalizer=f=3200:t=q:w=1.2:g=1.5,"
               "highshelf=f=7500:g=-1.5,deesser=i=0.4,acompressor=threshold=-26dB:ratio=3:attack=10:release=180:makeup=3dB:knee=5")
sys.path.insert(0, str(HERE))
import workflow  # noqa: E402
from audiomix import SR, AUDIO_EXT  # noqa: E402,F401


def read_json(p: Path, default=None):
    if not p.exists():
        return default
    return json.loads(p.read_text(encoding="utf-8-sig"))


def _replace(tmp, p):
    for i in range(8):
        try:
            os.replace(tmp, p)
            return
        except PermissionError:
            if i == 7:
                raise
            time.sleep(0.05 * (i + 1))


import projectstore  # noqa: E402  (plan-file writes are recorded: ADR 0005)


def write_json(p: Path, data):
    projectstore.write_json(p, data)


def say(msg):
    print(msg, flush=True)


def tc(t: float) -> str:
    t = int(round(t))
    return f"{t // 3600}:{t % 3600 // 60:02d}:{t % 60:02d}" if t >= 3600 else f"{t // 60}:{t % 60:02d}"


# ----------------------------------------------------------------------------- naming
def title_of(work: str, name: str) -> str:
    t = (workflow.load(work, name).get("title") or name).strip()
    return re.sub(r'[<>:"/\\|?*]+', "", t).strip() or name


VER_RE = re.compile(r" v(\d+) \(1080p\)\.mp4$")


def next_version(work: str, title: str) -> int:
    nums = [int(m.group(1)) for p in (WORK / work).glob(f"{title} v* (1080p).mp4") if (m := VER_RE.search(p.name))]
    return max(nums, default=0) + 1


def finals(work: str, name: str) -> list[dict]:
    out = []
    for p in sorted((WORK / work).glob("* v* (1080p).mp4"), key=lambda p: -p.stat().st_mtime):
        info = read_json(p.with_name(p.stem + ".final.json")) or {}
        out.append({"file": p.name, "size_mb": round(p.stat().st_size / 1e6, 1), "mtime": p.stat().st_mtime, **{k: info.get(k) for k in ("version", "dur", "loudness", "checks", "created", "audio", "delivered")}})
    return out


def deliver(work: str, name: str, out: Path, fd: Path) -> dict:
    """Copy what the host uploads (the final, its chapters and its description draft) into the video's own project folder, next to the footage, so it is easy to find.
    The work folder keeps the originals (the app plays and checks them from there). Never overwrites a file that is already there."""
    try:
        import shootplan
        folder, _how = shootplan.footage_folder(work, name)
    except Exception as e:
        return {"ok": False, "why": f"could not look up the project folder: {e}", "files": []}
    if not folder:
        return {"ok": False, "why": "no footage folder is chosen for this video (Clips tab), so the final stays in the work folder only", "files": []}
    files = []
    for src, dst_name in ((out, out.name), (fd / "chapters.txt", out.stem + " chapters.txt"), (fd / "description.txt", out.stem + " description.txt")):
        if not src.exists():
            continue
        dst = Path(folder) / dst_name
        if dst.exists():
            files.append({"file": dst_name, "skipped": "already there"})
            continue
        tmp = dst.with_name(dst.name + ".part")
        shutil.copy2(src, tmp)
        os.replace(tmp, dst)
        files.append({"file": dst_name, "mb": round(dst.stat().st_size / 1e6, 1)})
    return {"ok": True, "folder": str(folder), "files": files}


# ----------------------------------------------------------------------------- the audio plan: what is mixed, what is not
def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def _match(name: str, files: list[Path]):
    n = norm(Path(name).stem if Path(name).suffix.lower() in AUDIO_EXT else name)
    if not n:
        return None, "empty name"
    exact = [f for f in files if norm(f.stem) == n]
    if len(exact) == 1:
        return exact[0], ""
    toks = n.split()
    near = exact or [f for f in files if all(t in norm(f.stem) for t in toks)]
    if len(near) == 1:
        return near[0], ""
    if not near:
        return None, "no file with that name"
    return None, "matches several files, use the full name: " + "; ".join(f.stem for f in near[:4]) + ("…" if len(near) > 4 else "")


def resolve_music(name: str):
    if not MUSIC_DIR.exists():
        return None, "the Music folder was not found"
    files = [f for f in MUSIC_DIR.iterdir() if f.suffix.lower() in AUDIO_EXT]
    f, why = _match(name, files)
    if not f:
        return None, why
    cat = read_json(config.EDITOR_DATA / "music_catalog.json", []) or []
    item = next((c for c in cat if c.get("file", "").lower() == f.name.lower()), None)
    if item and item.get("vocals") == "yes":
        return None, "this track has vocals: never under dialogue (the host's rule)"
    return f, ("vocals unclear: listen once" if item and item.get("vocals") == "maybe" else "")


def resolve_sfx(name: str):
    if not SFX_DIR.exists():
        return None, "the SFX folder was not found"
    files = [f for f in SFX_DIR.rglob("*") if f.is_file() and f.suffix.lower() in AUDIO_EXT]
    return _match(name, files)


def transition_sounds(brolls: list, kit: dict | None = None) -> list:
    """The whoosh (or other sound) of each cutaway's transition, on the output timeline. The sounds of a role take turns."""
    import transitions
    out, n = [], {}
    for b in brolls:
        start = (b.get("seg_info") or {}).get("start")
        if start is None:
            continue
        for at, role in transitions.sound_times(b):
            if kit is None:
                import sfxkit
                kit = sfxkit.kit()
            f = transitions.sound_file(role, n.get(role, 0), kit)
            if f:
                n[role] = n.get(role, 0) + 1
                out.append({"name": f"{role} (transition)", "beat": b["seg"], "t": round(float(start) + at, 3), "file": f, "why": ""})
    return out


def audio_plan(work: str, name: str) -> dict:
    """Music beds and SFX resolved to files and to times on the OUTPUT timeline. Pure planning: nothing is rendered."""
    import selfreview
    T = selfreview.timeline(work, name)
    bm = read_json(WORK / work / f"{name}.beatmap.json") or {"beats": []}
    beats = {b["id"]: b for b in bm["beats"]}
    beds, sfx, missing = [], [], []
    cur = None
    for sg in T["segments"]:
        b = beats.get(sg["id"], {})
        m = ((b.get("audio") or {}).get("music") or "").strip()
        if m and cur and cur["name"] == m and abs(cur["end"] - sg["start"]) < 0.05:
            cur["end"] = sg["start"] + sg["dur"]
            cur["beats"].append(sg["id"])
        elif m:
            cur = {"name": m, "start": sg["start"], "end": sg["start"] + sg["dur"], "beats": [sg["id"]]}
            beds.append(cur)
        else:
            cur = None
        for line in (b.get("audio") or {}).get("sfx") or []:
            txt = line.strip()
            if not txt:
                continue
            nm, _, at = txt.partition("@")
            nm, at = nm.strip(), at.strip()
            off = 0.0
            if at.lower().startswith("graphic"):
                ov = next((o for o in T["overlays"] if o["seg"] == sg["id"]), None)
                off = float(ov.get("at", 0.0)) if ov else 0.0
                m = re.match(r"graphic\s*\+\s*([\d.]+)", at.lower())             # "@graphic+4.0": that many seconds after the graphic starts
                off += float(m.group(1)) if m else 0.0
            elif at.lower() == "end":                                   # the effect ends where the beat's last piece ends
                import sectionrender
                f0, _ = resolve_sfx(nm)
                tail = [x for x in T["segments"] if x["id"].split(".")[0] == sg["id"].split(".")[0]][-1]
                off = (tail["start"] + tail["dur"] - sg["start"]) - (sectionrender.probe_duration(f0) if f0 else 0.0)
            elif at:
                try:
                    off = float(at)
                except ValueError:
                    missing.append({"kind": "sfx", "name": txt, "beat": sg["id"], "why": f"could not read the time {at!r} (use '@ 1.2' or '@graphic')"})
                    continue
            f, why = resolve_sfx(nm)
            row = {"name": nm, "beat": sg["id"], "t": round(sg["start"] + off, 3), "file": str(f) if f else None, "why": why}
            (sfx if f else missing).append(row if f else {"kind": "sfx", **row})
    sfx.extend(transition_sounds(T["broll"]))
    for bed in beds:
        f, why = resolve_music(bed["name"])
        bed["file"], bed["why"] = (str(f) if f else None), why
        if not f:
            missing.append({"kind": "music", "name": bed["name"], "beat": bed["beats"][0], "why": why})
    return {"beds": [b for b in beds if b["file"]], "sfx": sfx, "not_mixed": missing, "all_beds": beds, "dur": T["stitch"].get("dur")}


# ----------------------------------------------------------------------------- chapters
def chapters(work: str, name: str) -> list[tuple[float, str]]:
    import selfreview
    T = selfreview.timeline(work, name)
    bm = read_json(WORK / work / f"{name}.beatmap.json") or {"beats": []}
    head = {b["id"]: b.get("section") or "" for b in bm["beats"]}
    out, last = [], None
    for sg in T["segments"]:
        h = head.get(sg["id"], "")
        if h != last:
            out.append([sg["start"], h or f"Part {len(out) + 1}"])
            last = h
    out = [c for c in out]
    merged = []
    for c in out:                                                  # YouTube: chapters at least 10 s long
        if merged and c[0] - merged[-1][0] < 10:
            continue
        merged.append(c)
    if merged:
        merged[0][0] = 0.0
    total = T["stitch"].get("dur") or 0
    if len(merged) > 1 and total - merged[-1][0] < 10:
        merged.pop()
    return [(t, n) for t, n in merged] if len(merged) >= 3 else []


# ----------------------------------------------------------------------------- state (stdlib)
def state(work: str, name: str) -> dict:
    out = {"can_render": False, "why_not": "", "ready": False, "finals": finals(work, name), "plan": None, "chapters": [], "warnings": []}
    try:
        st = workflow.state(work, name)
    except ValueError as e:
        out["why_not"] = str(e)
        return out
    out["title"] = title_of(work, name)
    out["next_version"] = next_version(work, out["title"])
    stitch = (WORK / work / f"{name}.stitch.json").exists()
    if not stitch:
        out["why_not"] = "Build and stitch the half-size preview first (Build tab): the final is rendered from it."
        out["warnings"].append("no stitched preview yet")
        return out
    out["can_render"] = True
    try:
        p = audio_plan(work, name)
        out["plan"] = {"beds": [{k: bd[k] for k in ("name", "start", "end", "file", "why")} for bd in p["all_beds"]],
                       "sfx": p["sfx"], "not_mixed": p["not_mixed"], "dur": p["dur"]}
        out["chapters"] = [{"t": t, "title": n} for t, n in chapters(work, name)]
    except ValueError as e:
        out["warnings"].append(str(e))
    sr_row = next((s for s in st["stages"] if s["id"] == "selfreview"), {})
    if sr_row.get("warnings"):
        out["warnings"].append("the self-review is not a clean pass: " + "; ".join(sr_row["warnings"]))
    moved = projectstore.changes_since(WORK / work, name, "stitch")
    if moved and (moved["changed"] or moved["added"] or moved["removed"]):
        names = sorted({f[len(name) + 1:] for f in moved["changed"] + moved["added"] + moved["removed"] if f.startswith(name + ".")})
        out["warnings"].append("the plan changed since the preview was stitched (" + ", ".join(names) + "): the final will not match what you watched")
    try:                                                   # unfinished graphics only warn (ADR 0003)
        import gfxplan
        out["warnings"] += gfxplan.review_state(work, name).get("warnings", [])
    except Exception:                                      # noqa: BLE001 - a warning is a convenience
        pass
    out["ready"] = out["can_render"] and out["plan"] is not None
    fd = WORK / work / "final"
    for key, fn in (("chapters_text", "chapters.txt"), ("description", "description.txt")):
        out[key] = (fd / fn).read_text(encoding="utf-8") if (fd / fn).exists() else None
    out["joins_sheet"] = (fd / "joins.jpg").exists()
    return out


# ----------------------------------------------------------------------------- audio rendering
from audiomix import _np, ff, decode, mix  # noqa: E402,F401  (moved to audiomix.py; shorts mix with the same recipe)


def chain_latency(chain: str) -> int:
    from render import chain_latency as cl                          # measured with a noise burst, already proven on the old pipeline
    return cl(chain)


def source_speech(src: str, lo: float, hi: float, cache: Path, voice: bool):
    """Processed audio of src[lo:hi] (voice chain on the continuous range, delay compensated) as float32 stereo at 48 kHz."""
    np, sf = _np()
    st = Path(src).stat()
    key = hashlib.sha1(f"{src}|{st.st_size}|{int(st.st_mtime)}|{lo:.2f}|{hi:.2f}|{voice}|v1".encode()).hexdigest()[:12]
    wav = cache / f"speech_{key}.wav"
    if not wav.exists():
        af = ["-af", VOICE_CHAIN] if voice else []
        r = ff("-ss", f"{lo:.3f}", "-t", f"{hi - lo:.3f}", "-i", src, "-map", "0:a:0", *af, "-ac", 2, "-ar", SR, "-c:a", "pcm_f32le", wav)
        if r.returncode != 0:
            raise RuntimeError(f"no usable audio in {Path(src).name}: {r.stderr.strip()[-200:]}")
    a, _ = sf.read(str(wav), dtype="float32", always_2d=True)
    if voice:
        lat = chain_latency(VOICE_CHAIN)
        if lat:
            a = np.vstack([a[lat:], np.zeros((lat, a.shape[1]), np.float32)])
    return a


def build_speech(segs: list[dict], frames: list[int], cache: Path, voice: bool):
    """The continuous speech track: each take cut from the processed source at sample positions derived from its frame count."""
    np, _ = _np()
    import pyloudnorm as pyln

    def aud(s):                                                  # where a take's SOUND comes from: a voice-over beat has its own recording
        if s.get("audio_src"):
            return s["audio_src"], float(s["audio_in"]), float(s["audio_in"]) + (s["out"] - s["in"])
        return s["src"], s["in"], s["out"]
    ranges: dict[str, list[float]] = {}
    for s in segs:
        asrc, ain, aout = aud(s)
        r = ranges.setdefault(asrc, [ain, aout])
        r[0], r[1] = min(r[0], ain), max(r[1], aout)
    pad = 2.0                                                     # warm-up for the denoiser/compressor before the first take
    cached = {}
    for src, (a, b) in ranges.items():
        lo = max(0.0, a - pad)
        cached[src] = (lo, source_speech(src, lo, b + 1.0, cache, voice))
    n_fade = int(FADE * SR)
    ramp = np.linspace(0.0, 1.0, n_fade, dtype=np.float32)[:, None]
    pieces = []
    for s, nf in zip(segs, frames):
        asrc, ain, _ = aud(s)
        lo, audio = cached[asrc]
        n = round(nf / FPS * SR)
        a0 = round((ain - lo) * SR)
        p = audio[a0:a0 + n].copy()
        if len(p) < n:
            p = np.vstack([p, np.zeros((n - len(p), 2), np.float32)])
        if len(p) > 2 * n_fade:
            p[:n_fade] *= ramp
            p[-n_fade:] *= ramp[::-1]
        if s.get("mute"):                                          # a take the creator asked to be silent (a title card): the picture stays, the speech goes
            p = np.zeros_like(p)
            asrc = None
        pieces.append((asrc, p))
    # level match: recordings made on different days (or the voice-over) differ in loudness; bring each recording's speech to the weighted average
    meter = pyln.Meter(SR)
    by_src: dict[str, list] = {}
    for asrc, p in pieces:
        if asrc is not None:
            by_src.setdefault(asrc, []).append(p)
    loud = {}
    for asrc, ps in by_src.items():
        cat = np.concatenate(ps)
        if len(cat) > SR * 1.5:
            try:
                l = meter.integrated_loudness(cat)
                if np.isfinite(l) and l > -60:
                    loud[asrc] = (l, len(cat))
            except ValueError:
                pass
    gains = {}
    if loud:
        tgt = sum(l * n for l, n in loud.values()) / sum(n for _, n in loud.values())
        gains = {a: max(-12.0, min(12.0, tgt - l)) for a, (l, n) in loud.items()}
        say("  level match: " + ", ".join(f"{Path(a).name} {g:+.1f} dB" for a, g in gains.items() if abs(g) >= 0.5) + f" (target {tgt:.1f} LUFS)")
    out_pieces = []
    for asrc, p in pieces:
        g = gains.get(asrc, 0.0)
        out_pieces.append(p * np.float32(10 ** (g / 20)) if abs(g) >= 0.5 else p)
    return np.concatenate(out_pieces)


def loudnorm(raw: Path, dst: Path) -> dict:
    import sectionrender
    p1 = subprocess.run([sectionrender.FFMPEG, "-nostdin", "-hide_banner", "-i", str(raw), "-af", "loudnorm=I=-14:TP=-1.5:LRA=11:print_format=json", "-f", "null", "-"],
                        capture_output=True, text=True).stderr
    meas = json.loads(p1[p1.rindex("{"): p1.rindex("}") + 1])
    af = (f"loudnorm=I=-14:TP=-1.5:LRA=11:measured_I={meas['input_i']}:measured_TP={meas['input_tp']}:measured_LRA={meas['input_lra']}:"
          f"measured_thresh={meas['input_thresh']}:offset={meas['target_offset']}:linear=true")
    r = ff("-i", raw, "-af", af, "-ar", SR, "-c:a", "pcm_s16le", dst)
    if r.returncode != 0:
        raise RuntimeError("loudness pass failed: " + r.stderr.strip()[-200:])
    return meas


# ----------------------------------------------------------------------------- the check on the finished file
def probe_one(path, entries, stream):
    import sectionrender
    r = subprocess.run([sectionrender.FFPROBE, "-v", "error", "-select_streams", stream, "-show_entries", entries, "-of", "csv=p=0", str(path)], capture_output=True, text=True)
    return r.stdout.strip()


def measure_loudness(path: Path) -> dict:
    import sectionrender
    r = subprocess.run([sectionrender.FFMPEG, "-nostdin", "-hide_banner", "-i", str(path), "-vn", "-af", "ebur128=peak=true", "-f", "null", "-"], capture_output=True, text=True).stderr
    tail = r[r.rindex("Summary:"):] if "Summary:" in r else r
    i = re.search(r"I:\s+(-?[\d.]+) LUFS", tail)
    pk = re.search(r"Peak:\s+(-?[\d.]+) dBFS", tail)
    return {"I": float(i.group(1)) if i else None, "TP": float(pk.group(1)) if pk else None}


def final_check(out: Path, total_frames: int, joins: list[float], dur_expected: float, plan: dict, workdir: Path) -> list[dict]:
    import sectionrender
    checks = []
    add = lambda cid, ok, note: checks.append({"id": cid, "ok": bool(ok), "note": note})
    w, h = probe_one(out, "stream=width,height", "v:0").split(",")[:2]
    add("resolution", (int(w), int(h)) == tuple(SIZE), f"{w}x{h}")
    nb = probe_one(out, "stream=nb_frames", "v:0")
    nb = int(nb) if nb.isdigit() else round(float(probe_one(out, "stream=duration", "v:0") or 0) * FPS)
    add("frames", abs(nb - total_frames) <= 1, f"{nb} frames, expected {total_frames}")
    dv, da = float(probe_one(out, "stream=duration", "v:0") or 0), float(probe_one(out, "stream=duration", "a:0") or 0)
    add("av_length", abs(dv - da) <= 0.05, f"picture {dv:.3f} s, sound {da:.3f} s")
    add("duration", abs(dv - dur_expected) <= 0.1, f"{dv:.2f} s, the preview is {dur_expected:.2f} s")
    L = measure_loudness(out)
    add("loudness", L["I"] is not None and abs(L["I"] + 14) <= 0.8, f"{L['I']} LUFS (target -14)")
    add("true_peak", L["TP"] is not None and L["TP"] <= -1.0, f"{L['TP']} dBFS (ceiling -1.5)")
    sheet_ok = False
    sel = joins[:24]
    if sel:                                                         # a glance at every cut: the frame just before and just after
        parts = []
        for k, t in enumerate(sel):
            for j, dt in enumerate((-0.12, 0.12)):
                p = workdir / f"join_{k:02d}_{j}.jpg"
                sectionrender_run = subprocess.run([sectionrender.FFMPEG, "-nostdin", "-y", "-v", "error", "-ss", f"{max(0.0, t + dt):.3f}", "-i", str(out), "-frames:v", "1",
                                                    "-vf", "scale=240:-2", "-q:v", "6", str(p)], capture_output=True)
                if sectionrender_run.returncode == 0:
                    parts.append(p)
        if parts:
            cols = 6
            rows = (len(parts) + cols - 1) // cols
            inputs = sum([["-i", str(p)] for p in parts], [])
            fc = "".join(f"[{i}:v]" for i in range(len(parts))) + f"xstack=inputs={len(parts)}:layout=" + "|".join(
                f"{(i % cols) * 240}_{(i // cols) * 135}" for i in range(len(parts)))
            r = subprocess.run([sectionrender.FFMPEG, "-nostdin", "-y", "-v", "error", *inputs, "-filter_complex", fc, "-frames:v", "1", str(workdir / "joins.jpg")], capture_output=True)
            sheet_ok = r.returncode == 0
            for p in parts:
                p.unlink(missing_ok=True)
    add("joins", True, f"{len(sel)} cut{'s' if len(sel) != 1 else ''}: contact sheet saved (before | after each cut)" if sheet_ok else f"{len(joins)} cuts")
    add("mix", True, f"{len(plan['beds'])} music bed(s), {len(plan['sfx'])} sound effect(s)" + (f"; {len(plan['not_mixed'])} NOT mixed (could not be matched)" if plan["not_mixed"] else ""))
    return checks


# ----------------------------------------------------------------------------- run
def run(work: str, name: str) -> dict:
    s = state(work, name)                                   # whether it can render is checked BEFORE anything heavy is loaded
    if not s["can_render"]:
        raise ValueError(s["why_not"])
    if s["plan"] is None:
        raise ValueError("; ".join(s["warnings"]) or "nothing to render yet")
    projectstore.mark(WORK / work, name, "final")           # the plan this final is rendered from
    import selfreview
    import sectionrender
    np, sf = _np()
    settings = {**workflow.DEFAULT_SETTINGS, **workflow.load(work, name)["settings"]}
    T = selfreview.timeline(work, name)
    plan = audio_plan(work, name)
    title, ver = s["title"], s["next_version"]
    fd = WORK / work / "final"
    cache = fd / "cache"
    cache.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    say("STEP 1/7 the plan: " + f"{len(T['segments'])} takes, {len(plan['beds'])} music bed(s), {len(plan['sfx'])} SFX" + (f", {len(plan['not_mixed'])} NOT mixed" if plan["not_mixed"] else ""))
    for m in plan["not_mixed"]:
        say(f"  NOT MIXED ({m['kind']}): {m['name']}: {m['why']}")

    say("STEP 2/7 picture: full-quality video (no sound yet)")
    segs = [{"id": g["id"], "src": g["src"], "in": g["in"], "out": g["out"], "zoom": g.get("zoom", 1.0), "cx": g.get("cx", 0.5), "cy": g.get("cy", 0.4),
             **({"audio_src": g["audio_src"], "audio_in": g.get("audio_in", 0)} if g.get("audio_src") else {}), **({"mute": True} if g.get("mute") else {})} for g in T["segments"]]
    edit = {"size": SIZE, "fps": FPS, "snap": False, "audio": False, "quality": "final", "segments": segs,
            "broll": [{k: b[k] for k in ("seg", "file", "in", "dur", "at", "stabilize", "rotate", "zoom", "pan", "speed", "t_in", "t_out") if k in b} for b in T["broll"]],
            "overlays": [{k: o[k] for k in ("seg", "file", "at", "dur", "in", "still", "fade_in", "fade_out") if k in o} for o in T["overlays"]]}
    ep = fd / "final.edit.json"
    write_json(ep, edit)
    info = sectionrender.render(ep, fd / "video", "video-only.mp4")
    frames = [round(x["out_dur"] * FPS) for x in info["segments"]]
    total_frames = sum(frames)

    say("STEP 3/7 speech: voice chain on the continuous recording, then cut to the picture")
    speech = build_speech(segs, frames, cache, bool(settings.get("voice_chain", True)))

    say("STEP 4/7 music and sound effects")
    mixed, speech_lufs = mix(speech, plan, settings, cache)
    raw = fd / "mix.wav"
    sf.write(str(raw), mixed, SR, subtype="FLOAT")

    say("STEP 5/7 loudness to -14 LUFS, then the final file")
    wav = fd / "mix-14.wav"
    meas = loudnorm(raw, wav)
    out = WORK / work / f"{title} v{ver} (1080p).mp4"
    tmp = out.with_name(out.stem + ".part.mp4")
    r = ff("-i", fd / "video" / "video-only.mp4", "-i", wav, "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", tmp)
    if r.returncode != 0:
        raise RuntimeError("muxing failed: " + r.stderr.strip()[-300:])
    os.replace(tmp, out)
    for f in (raw, wav):
        f.unlink(missing_ok=True)

    say("STEP 6/7 checking the finished file")
    joins = [j["t"] for j in T["joins"]]
    checks = final_check(out, total_frames, joins, float(T["stitch"].get("dur") or 0), plan, fd)
    ch = chapters(work, name)
    (fd / "chapters.txt").write_text("\n".join(f"{tc(t)} {n}" for t, n in ch) + ("\n" if ch else ""), encoding="utf-8")
    desc = [title, "", "[FILL: one or two sentences about the video]", ""]
    desc += (["Chapters"] + [f"{tc(t)} {n}" for t, n in ch] + [""]) if ch else ["(Too few chapters for YouTube to show them: it needs at least 3, each 10 s or longer.)", ""]
    desc += ["[FILL: parts list and links]", "[FILL: affiliate / sponsor disclosure if any]"]
    (fd / "description.txt").write_text("\n".join(desc) + "\n", encoding="utf-8")
    result = {"version": ver, "file": out.name, "created": time.strftime("%Y-%m-%dT%H:%M:%S"), "dur": round(total_frames / FPS, 3), "frames": total_frames,
              "fps": FPS, "size": SIZE, "elapsed": round(time.time() - t0, 1), "loudness": measure_loudness(out), "speech_lufs": round(speech_lufs, 1),
              "audio": {"voice_chain": bool(settings.get("voice_chain", True)), "beds": plan["beds"], "sfx": plan["sfx"], "not_mixed": plan["not_mixed"]},
              "checks": checks, "chapters": [{"t": t, "title": n} for t, n in ch],
              "sections": [{"id": x["id"], "start": x["start"], "dur": x.get("dur")} for x in T["stitch"]["sections"]]}
    say("STEP 7/7 copying the upload files into the project folder")
    result["delivered"] = deliver(work, name, out, fd)
    say("delivered: " + (", ".join(f["file"] for f in result["delivered"]["files"]) + " -> " + result["delivered"]["folder"] if result["delivered"]["ok"] else result["delivered"]["why"]))
    write_json(out.with_name(out.stem + ".final.json"), result)
    bad = [c for c in checks if not c["ok"]]
    say(f"DONE {out.name}: {result['dur']:.1f} s, {out.stat().st_size / 1e6:.0f} MB, {result['loudness']['I']} LUFS; " + ("all checks passed" if not bad else f"{len(bad)} check(s) failed: " + ", ".join(c["id"] for c in bad)))
    return result


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["plan", "run"])
    ap.add_argument("work")
    ap.add_argument("name")
    a = ap.parse_args()
    try:
        if a.cmd == "plan":
            s = state(a.work, a.name)
            print(json.dumps({k: s[k] for k in ("can_render", "ready", "next_version", "warnings", "plan", "chapters")}, indent=1, ensure_ascii=False))
        else:
            run(a.work, a.name)
    except (ValueError, RuntimeError) as e:
        sys.exit(f"finalrender: {e}")


if __name__ == "__main__":
    main()
