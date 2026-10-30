"""Half-size render of ONE section from a section.edit.json (stage 5). Multi-clip, no tokens.

Usage (editor venv):
    python sectionrender.py <section.edit.json> [--out <folder>]    # writes preview-half.mp4 + render.json in --out
                                                                     # (default: the folder next to the edit file, out\\)
section.edit.json:
  {"size": [960, 540], "fps": 30, "snap": true,
   "segments": [{"id": "B01", "src": "<video>", "in": 11.2, "out": 15.8, "zoom": 1.0, "cx": 0.5, "cy": 0.4}],
   "broll":    [{"seg": "B03", "file": "<video>", "in": 2.0, "dur": 4.0, "at": 0.5}],     # cutaway over the segment, muted
   "overlays": [{"seg": "B01", "file": "<mov/mp4 with alpha>", "at": 0.0, "dur": 3.0}]}  # a rendered graphic over the segment

* Segments play in the order listed, each re-encoded (H.264, 30 fps, AAC 48 kHz) and joined by stream copy.
* `snap`: every cut point moves to the quietest 5 ms inside +-0.12 s of the nominal time (Parakeet word times can be
  0.2 s off in either direction; the host's lavs gate to digital silence between words), so no clipped words and no dead air.
* `zoom` > 1 is an instant punch-in (crop around cx, cy; the face goes in the upper third at cy about 0.4).
* B-roll and overlays are placed `at` seconds into their segment; the speech of the A-roll plays underneath.
* Audio is the A-roll's speech only: music and SFX are not in section previews yet.
Needs ffmpeg/ffprobe, numpy.
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

LEVEL_TARGET = -16.0   # LUFS: every take of a section preview is brought to about this loudness, so clips from different days sound even
LEVEL_MIN_S = 1.5      # s: a take shorter than this is too short to measure, it is left alone
SNAP = 0.12      # s, search radius around a cut point
WIN = 0.005      # s, RMS window


def find_exe(name: str) -> str:
    exe = shutil.which(name)
    if exe:
        return exe
    base = Path(os.environ.get("LOCALAPPDATA", ""))
    for p in base.glob(f"Microsoft/WinGet/Packages/Gyan.FFmpeg*/*/bin/{name}.exe"):
        return str(p)
    raise RuntimeError(f"{name} not found")


FFMPEG, FFPROBE = find_exe("ffmpeg"), find_exe("ffprobe")


def probe_duration(path) -> float:
    r = subprocess.run([FFPROBE, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)], capture_output=True, text=True)
    return float(r.stdout.strip() or 0)


def video_seconds(path, fps: float) -> float:
    """Length of a file's PICTURE from its frame count (exact). The container duration also counts the audio's priming
    padding, a few ms per segment, which piled up over many cuts and pushed later times and chapters off by seconds."""
    r = subprocess.run([FFPROBE, "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=nb_frames", "-of", "csv=p=0", str(path)],
                       capture_output=True, text=True).stdout.strip()
    return int(r) / fps if r.isdigit() else probe_duration(path)


def has_audio(path) -> bool:
    r = subprocess.run([FFPROBE, "-v", "error", "-select_streams", "a:0", "-show_entries", "stream=codec_type", "-of", "csv=p=0", str(path)],
                       capture_output=True, text=True)
    return "audio" in r.stdout


def snap(src: str, t: float) -> float:
    """The quietest point within +-SNAP of t (5 ms RMS). Returns t unchanged if the audio cannot be read."""
    import numpy as np
    lo = max(0.0, t - SNAP - 0.05)
    r = subprocess.run([FFMPEG, "-nostdin", "-v", "error", "-ss", f"{lo:.3f}", "-t", f"{2 * SNAP + 0.1:.3f}", "-i", src,
                        "-vn", "-ac", "1", "-ar", "16000", "-f", "f32le", "-"], capture_output=True)
    a = np.frombuffer(r.stdout, np.float32)
    n = int(16000 * WIN)
    if len(a) < n * 4:
        return t
    rms = np.sqrt(np.mean(a[:len(a) // n * n].reshape(-1, n) ** 2, axis=1))
    times = lo + (np.arange(len(rms)) + 0.5) * WIN
    ok = np.abs(times - t) <= SNAP
    if not ok.any():
        return t
    best = np.where(ok, rms, np.inf)
    floor = best.min()
    cands = np.where(ok & (rms <= floor * 1.05 + 1e-6))[0]            # ties (digital silence): the one nearest t
    i = cands[np.argmin(np.abs(times[cands] - t))]
    return round(float(times[i]), 3)


def base_filter(W: int, H: int, fps: int, z: float = 1.0, cx: float = 0.5, cy: float = 0.4) -> str:
    """The ffmpeg filter chain that turns a source frame into the section's picture: cover-crop to W x H, then an
    optional instant punch-in (crop around cx, cy). The self-review reuses it to grab a CLEAN frame (no graphic on top)."""
    f = f"fps={fps},scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H}"
    if z > 1.0:
        f += f",crop=w=in_w/{z}:h=in_h/{z}:x=(in_w-out_w)*{cx}:y=(in_h-out_h)*{cy},scale={W}:{H}"
    return f


def encoder(nv=True, quality="half"):
    """quality "half" = fast preview; "final" = what gets uploaded (the section previews use "half")."""
    if quality == "final":
        if nv:
            return ["-c:v", "h264_nvenc", "-preset", "p6", "-rc", "vbr", "-cq", "19", "-b:v", "0", "-pix_fmt", "yuv420p"]
        return ["-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p"]
    if nv:
        return ["-c:v", "h264_nvenc", "-preset", "p4", "-rc", "vbr", "-cq", "30", "-b:v", "0", "-pix_fmt", "yuv420p"]
    return ["-c:v", "libx264", "-preset", "veryfast", "-crf", "28", "-pix_fmt", "yuv420p"]


def measure_lufs(path, ss: float, dur: float):
    """Integrated loudness (LUFS) of path[ss:ss+dur], or None when it cannot be measured (silence, no audio)."""
    r = subprocess.run([FFMPEG, "-nostdin", "-hide_banner", "-ss", f"{ss:.3f}", "-t", f"{dur:.3f}", "-i", str(path), "-vn",
                        "-af", "loudnorm=I=-16:TP=-1.5:LRA=11:print_format=json", "-f", "null", "-"], capture_output=True, text=True)
    m = re.search(r'"input_i"\s*:\s*"(-?[\d.]+)"', r.stderr)
    return float(m.group(1)) if m else None


def stabilized(file: str, ss: float, dur: float, cache: Path):
    """(file, in) of a stabilized copy of file[ss:ss+dur] (vidstab, two passes, cached); the original on any failure."""
    try:
        cache.mkdir(parents=True, exist_ok=True)
        st = Path(file).stat()
        key = hashlib.sha1(f"{file}|{st.st_size}|{int(st.st_mtime)}|{ss:.2f}|{dur:.2f}|v1".encode()).hexdigest()[:12]
        out = cache / f"stab_{key}.mp4"
        if not out.exists():
            trf = f"{key}.trf"
            r1 = subprocess.run([FFMPEG, "-nostdin", "-y", "-v", "error", "-ss", f"{ss:.3f}", "-t", f"{dur:.3f}", "-i", str(file), "-an",
                                 "-vf", f"vidstabdetect=shakiness=6:accuracy=15:result={trf}", "-f", "null", "-"], cwd=cache, capture_output=True, text=True)
            if r1.returncode != 0:
                return file, ss
            tmp = cache / f"{key}.part.mp4"
            r2 = subprocess.run([FFMPEG, "-nostdin", "-y", "-v", "error", "-ss", f"{ss:.3f}", "-t", f"{dur:.3f}", "-i", str(file), "-an",
                                 "-vf", f"vidstabtransform=input={trf}:smoothing=20:optzoom=1:zoom=0,unsharp=5:5:0.6",
                                 "-c:v", "libx264", "-preset", "fast", "-crf", "16", "-pix_fmt", "yuv420p", str(tmp)], cwd=cache, capture_output=True, text=True)
            if r2.returncode != 0:
                return file, ss
            os.replace(tmp, out)
        return str(out), 0.0
    except OSError:
        return file, ss


def _stab(b: dict, cache: Path) -> dict:
    f, a = stabilized(b["file"], float(b.get("in") or 0), float(b.get("dur") or 2) * float(b.get("speed") or 1.0), cache)
    return {**b, "file": f, "in": a}


_PEAK = {}


def sfx_gain(path: str) -> float:
    """dB to apply so a sound effect peaks at about -18 dBFS (they come from many sources at very different levels; -10 was too loud, the host 2026-10-25)."""
    if path not in _PEAK:
        r = subprocess.run([FFMPEG, "-nostdin", "-hide_banner", "-i", str(path), "-af", "volumedetect", "-vn", "-f", "null", "-"], capture_output=True, text=True)
        m = re.search(r"max_volume:\s*(-?[\d.]+) dB", r.stderr)
        _PEAK[path] = max(-24.0, min(24.0, -18.0 - float(m.group(1)))) if m else -6.0
    return _PEAK[path]


def join_sound(wavs: list, seconds: list, out: Path, rate: int = 48000) -> None:
    """Lay the pieces' sound end to end, each cut or padded with silence to exactly its picture's length (frames / fps), so the sound stays on the lips however many pieces there are."""
    import wave
    with wave.open(str(out), "wb") as o:
        o.setnchannels(2)
        o.setsampwidth(2)
        o.setframerate(rate)
        end = 0.0
        done = 0
        for w, sec in zip(wavs, seconds):
            end += sec                                           # cumulative target, so the rounding of one piece never piles up
            want = int(round(end * rate)) - done
            with wave.open(str(w), "rb") as i:
                data = i.readframes(want)
            data += b"\0" * (4 * want - len(data))
            o.writeframes(data)
            done += want


def render_segment(edit: dict, seg: dict, a_in: float, a_out: float, out: Path, brolls: list, overlays: list, gain_db: float = 0.0, sfx: list = ()):
    W, H = edit["size"]
    fps = edit.get("fps", 30)
    D = max(0.1, a_out - a_in)
    z = float(seg.get("zoom") or 1.0)
    cx, cy = float(seg.get("cx", 0.5)), float(seg.get("cy", 0.4))
    brolls = [{**b, "dur": D - float(b.get("at", 0.5))} if 0 < D - float(b.get("at", 0.5)) - float(b["dur"]) <= 0.25 else b for b in brolls]   # a B-roll that ends a few frames short of its piece (the cut point snapped later than the beat length) would leave one frame of the A-roll at the end: let it run to the end
    args = ["-ss", f"{a_in:.3f}", "-t", f"{D:.3f}", "-i", seg["src"]]
    va = seg.get("audio_src")                               # a voice-over beat: the picture is a B-roll clip, the sound is the voice-over take
    if va:
        args += ["-ss", f"{float(seg.get('audio_in', 0)):.3f}", "-t", f"{D:.3f}", "-i", va]
    for br in brolls:
        args += ["-ss", f"{br['in']:.3f}", "-t", f"{br['dur'] * float(br.get('speed') or 1.0):.3f}", "-i", br["file"]]       # speed < 1 = slow motion: dur is the time on screen, the source needed is dur * speed
    for ov in overlays:
        args += (["-ss", f"{float(ov['in']):.3f}"] if float(ov.get("in") or 0) > 0 else []) + ["-i", ov["file"]]        # "in": this piece starts that far into the graphic (it carries on across a cut)
    chains, last, k = [f"[0:v]{base_filter(W, H, fps, z, cx, cy)},setsar=1[v0]"], "v0", (2 if va else 1)
    for i, br in enumerate(brolls):
        at, dur = float(br.get("at", 0.5)), min(br["dur"], max(0.1, D - float(br.get("at", 0.5))))
        rot = {180: "hflip,vflip,", 90: "transpose=1,", 270: "transpose=2,"}.get(int(br.get("rotate") or 0) % 360, "")           # a clip filmed upside down or sideways
        zm = float(br.get("zoom") or 1.0)                                                                                # a slow push-in / pan across the clip: zoom 1.3, pan left|right|up|down
        move = ""
        if zm > 1.0:
            zw, zh = int(W * zm) // 2 * 2, int(H * zm) // 2 * 2
            fr = f"min(t/{max(0.1, float(br['dur'])):.3f},1)"
            px = {"right": f"(iw-{W})*{fr}", "left": f"(iw-{W})*(1-{fr})"}.get(br.get("pan"), f"(iw-{W})/2")
            py = {"down": f"(ih-{H})*{fr}", "up": f"(ih-{H})*(1-{fr})"}.get(br.get("pan"), f"(ih-{H})/2")
            move = f"scale={zw}:{zh}:force_original_aspect_ratio=increase,crop={W}:{H}:x='{px}':y='{py}',"
        sp = float(br.get("speed") or 1.0)
        slow = f"setpts=(PTS-STARTPTS)/{sp:.4f}," if abs(sp - 1.0) > 0.01 else ""
        chains.append(f"[{k}:v]{rot}{slow}fps={fps},scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},{move}setsar=1,setpts=PTS-STARTPTS+{at}/TB[b{i}]")
        chains.append(f"[{last}][b{i}]overlay=enable='between(t,{at:.3f},{at + dur:.3f})':eof_action=pass[vb{i}]")
        last, k = f"vb{i}", k + 1
    for i, ov in enumerate(overlays):
        at = float(ov.get("at", 0.0))
        chains.append(f"[{k}:v]format=rgba,fps={fps},scale={W}:{H},setpts=PTS-STARTPTS+{at}/TB[o{i}]")
        chains.append(f"[{last}][o{i}]overlay=eof_action=pass[vo{i}]")
        last, k = f"vo{i}", k + 1
    chains.append(f"[{last}]format=yuv420p[vout]")
    with_audio = edit.get("audio", True)                    # the final render builds its sound separately (voice chain, music, SFX)
    if with_audio:
        vol = f",volume={gain_db:.2f}dB,alimiter=limit=0.95" if abs(gain_db) > 0.4 else ""
        if va:
            chains.append(f"[1:a]aresample=48000,aformat=channel_layouts=stereo,afade=t=in:st=0:d=0.008,afade=t=out:st={max(0, D - 0.008):.3f}:d=0.008{vol}[abase]")
        elif has_audio(seg["src"]) and not seg.get("mute"):
            chains.append(f"[0:a]aresample=48000,aformat=channel_layouts=stereo,afade=t=in:st=0:d=0.008,afade=t=out:st={max(0, D - 0.008):.3f}:d=0.008{vol}[abase]")
        else:
            args += ["-f", "lavfi", "-t", f"{D:.3f}", "-i", "anullsrc=r=48000:cl=stereo"]
            chains.append(f"[{k}:a]anull[abase]")
            k += 1
        parts = ["[abase]"]
        for j, x in enumerate(sfx):                                 # sound effects (a whoosh on a title card): mixed into this take's sound
            args += ["-i", x["file"]]
            ms = int(max(0.0, float(x.get("at", 0))) * 1000)
            chains.append(f"[{k}:a]aresample=48000,aformat=channel_layouts=stereo,volume={sfx_gain(x['file']):.1f}dB,adelay={ms}|{ms}[sx{j}]")
            parts.append(f"[sx{j}]")
            k += 1
        chains.append("".join(parts) + f"amix=inputs={len(parts)}:normalize=0:duration=first[aout]" if len(parts) > 1 else "[abase]anull[aout]")
    for nv in (True, False):
        # The sound goes to its own WAV (no AAC priming padding per piece; render() cuts it to the picture's exact length and encodes once, the creator 2026-10-29: lips off the voice)
        cmd = [FFMPEG, "-nostdin", "-y", "-v", "error", *args, "-filter_complex", ";".join(chains), "-map", "[vout]",
               *encoder(nv, edit.get("quality", "half")), "-r", str(fps), "-an", "-t", f"{D:.3f}", str(out),
               *(["-map", "[aout]", "-c:a", "pcm_s16le", "-t", f"{D:.3f}", str(out.with_suffix(".wav"))] if with_audio else [])]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode == 0:
            return
        if not nv:
            raise RuntimeError(f"ffmpeg failed on {seg['id']}: {r.stderr.strip()[-400:]}")


def render(edit_path: Path, out_dir: Path | None = None, out_name: str = "preview-half.mp4") -> dict:
    edit = json.loads(edit_path.read_text(encoding="utf-8-sig"))
    out_dir = out_dir or edit_path.parent / "out"
    out_dir.mkdir(parents=True, exist_ok=True)
    tmp = out_dir / "segments"
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir()
    segs = edit.get("segments") or []
    if not segs:
        raise ValueError("no segments to render")
    parts, log, t0 = [], [], 0.0
    for i, seg in enumerate(segs):
        if not Path(seg["src"]).exists():
            raise ValueError(f"{seg['id']}: source not found: {seg['src']}")
        a_in, a_out = float(seg["in"]), float(seg["out"])
        s_in, s_out = (snap(seg["src"], a_in), snap(seg["src"], a_out)) if edit.get("snap", True) else (a_in, a_out)
        if s_out - s_in < 0.3:                                    # never snap a short take away
            s_in, s_out = a_in, a_out
        brolls = [b for b in edit.get("broll", []) if b["seg"] == seg["id"]]
        overlays = [o for o in edit.get("overlays", []) if o["seg"] == seg["id"]]
        for x in brolls + overlays:
            if not Path(x["file"]).exists():
                raise ValueError(f"{seg['id']}: file not found: {x['file']}")
        brolls = [_stab(b, out_dir / "stab") if b.get("stabilize") else b for b in brolls]
        gain = 0.0
        if seg.get("gain_db") is not None:                       # the whole recording was measured once (loudness.py): every piece of it gets the same gain
            gain = float(seg["gain_db"])
        elif edit.get("audio", True) and edit.get("level", True) and s_out - s_in >= LEVEL_MIN_S and not seg.get("mute"):
            asrc = seg.get("audio_src") or seg["src"]
            lufs = measure_lufs(asrc, float(seg.get("audio_in", 0)) if seg.get("audio_src") else s_in, s_out - s_in)
            if lufs is not None and lufs > -60:
                gain = max(-12.0, min(12.0, LEVEL_TARGET - lufs))
        part = tmp / f"seg_{i:03d}.mp4"
        sfx = [x for x in edit.get("sfx", []) if x["seg"] == seg["id"] and Path(x["file"]).exists()]
        render_segment(edit, seg, s_in, s_out, part, brolls, overlays, gain, sfx)
        d = video_seconds(part, float(edit.get("fps", 30)))
        log.append({"id": seg["id"], "src": seg["src"], "in": s_in, "out": s_out, "nominal_in": a_in, "nominal_out": a_out,
                    "out_start": round(t0, 3), "out_dur": round(d, 3), "broll": len(brolls), "overlays": len(overlays), "zoom": seg.get("zoom", 1.0),
                    "cx": seg.get("cx", 0.5), "cy": seg.get("cy", 0.4), "gain_db": round(gain, 1), **({"mute": True} if seg.get("mute") else {}),
                    **({"audio_src": seg["audio_src"], "audio_in": seg.get("audio_in", 0)} if seg.get("audio_src") else {})})
        t0 += d
        parts.append(part)
        print(f"SEGMENT {seg['id']} {s_out - s_in:.1f}s ({a_in:.2f}->{s_in:.2f}, {a_out:.2f}->{s_out:.2f})", flush=True)
    lst = tmp / "list.txt"
    fps_n = float(edit.get("fps", 30))
    lst.write_text("".join(f"file '{p.as_posix()}'\nduration {video_seconds(p, fps_n):.6f}\n" for p in parts), encoding="utf-8")   # the picture joined by its exact frame count
    final = out_dir / out_name
    wavs = [p.with_suffix(".wav") for p in parts]
    sound = None
    if edit.get("audio", True) and all(w.exists() for w in wavs):
        sound = tmp / "sound.wav"
        join_sound(wavs, [video_seconds(p, fps_n) for p in parts], sound)
    cmd = [FFMPEG, "-nostdin", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(lst), *(["-i", str(sound)] if sound else []),
           "-map", "0:v", *(["-map", "1:a", "-c:a", "aac", "-b:a", "160k"] if sound else []), "-c:v", "copy", "-movflags", "+faststart", str(final)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError("join failed: " + r.stderr.strip()[-300:])
    shutil.rmtree(tmp)
    info = {"rendered": time.strftime("%Y-%m-%dT%H:%M:%S"), "file": str(final), "dur": round(t0, 3),
            "size": edit["size"], "fps": edit.get("fps", 30), "segments": log, "notes": edit.get("notes", [])}
    (out_dir / "render.json").write_text(json.dumps(info, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"DONE {info['dur']:.1f}s {final}", flush=True)
    return info


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("edit", type=Path)
    ap.add_argument("--out", type=Path)
    a = ap.parse_args()
    try:
        render(a.edit, a.out)
    except (ValueError, RuntimeError) as e:
        sys.exit(f"sectionrender: {e}")


if __name__ == "__main__":
    main()
