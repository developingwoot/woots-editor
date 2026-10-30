"""Render an edit plan (from roughcut.py) to video.

Usage:
    python render.py <edit.json> <video> <out.mp4> [--final]

<video> is usually the low-res proxy for previews, or the original file with
--final. Cut points are snapped to the frame grid so audio and video cut on the
same instant; audio pieces get a short crossfade so cuts don't click.
"""
import argparse
import json
import subprocess
import sys
import tempfile
from fractions import Fraction
from pathlib import Path

import numpy as np
import soundfile as sf

SR = 48000
FADE = 0.008  # seconds of crossfade at each audio join


def probe_fps(video: Path) -> Fraction:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
         "stream=avg_frame_rate", "-of", "default=nw=1:nk=1", str(video)],
        check=True, capture_output=True, text=True,
    ).stdout.split()
    return Fraction(out[0])  # some files list the stream twice (stream groups)


def probe_size(video: Path) -> tuple[int, int]:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
         "stream=width,height", "-of", "csv=p=0", str(video)],
        check=True, capture_output=True, text=True,
    ).stdout.split()[0]
    w, h = out.split(",")[:2]
    return int(w), int(h)


def probe_duration(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(path)],
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    return float(out)


def to_output_time(src_t: float, frames, fps: Fraction):
    """Map a source-footage time to its time in the cut, or None if it was cut."""
    f = src_t * fps
    # Half-open first: a time on the boundary between two pieces belongs to the piece that STARTS
    # there (with re-ordered blocks the piece that ends there can be somewhere else entirely).
    for inclusive_end in (False, True):
        elapsed = 0
        for a, b in frames:
            if a <= f < b or (inclusive_end and f == b):
                return float((elapsed + (f - a)) / fps)
            elapsed += b - a
    # Rounding: frame numbers are rounded, so a boundary time can fall half a frame outside.
    for a, b in frames:
        if abs(f - a) <= 0.5:
            return to_output_time(a / fps, frames, fps)
    return None


def _starts(frames):
    out, el = [], 0
    for a, b in frames:
        out.append(el)
        el += b - a
    return out


def to_output_clamped(src_t: float, frames, fps: Fraction) -> float:
    """Like to_output_time, but a start time inside a cut snaps forward to the next kept source
    piece. Works when pieces are re-ordered (not in source order)."""
    t = to_output_time(src_t, frames, fps)
    if t is not None:
        return t
    f = src_t * fps
    nxt = [(a, st) for (a, b), st in zip(frames, _starts(frames)) if a > f]
    return float(min(nxt)[1] / fps) if nxt else float(sum(b - a for a, b in frames) / fps)


def to_output_clamped_end(src_t: float, frames, fps: Fraction) -> float:
    """End-time version: a time inside a cut snaps back to the end of the previous kept piece."""
    f = src_t * fps
    for (a, b), st in zip(frames, _starts(frames)):
        if abs(f - b) <= 0.5:                     # exactly a piece's end: that piece, not the next one
            return float((st + b - a) / fps)
    t = to_output_time(src_t, frames, fps)
    if t is not None:
        return t
    f = src_t * fps
    prev = [(b, st + b - a) for (a, b), st in zip(frames, _starts(frames)) if b < f]
    return float(max(prev)[1] / fps) if prev else 0.0


def intermediate(video: Path, frames, fps: Fraction, cache: Path, final: bool) -> Path:
    """All kept frames in source order, every frame a keyframe (exact seeking). Cached."""
    import hashlib
    cache.mkdir(parents=True, exist_ok=True)
    key = hashlib.md5(f"{video}|{frames}|{fps}|{final}|v1".encode()).hexdigest()[:12]
    out = cache / f"base_{key}.mp4"
    if out.exists():
        return out
    select = "+".join(f"between(n,{a},{b - 1})" for a, b in frames)
    vf = cache / f"base_{key}.vf.txt"
    vf.write_text(f"fps={fps},select='{select}',setpts=N/({fps}*TB)", encoding="utf-8")
    tmp = out.with_suffix(".part.mp4")                 # only a verified file gets the cache name
    subprocess.run(["ffmpeg", "-nostdin", "-y", "-v", "error", "-i", str(video), "-/vf", str(vf), "-an",
                    "-c:v", "h264_nvenc", "-bf", "0", "-forced-idr", "1", "-force_key_frames", "expr:1",
                    "-cq", "15" if final else "22", str(tmp)], check=True)  # NVENC rejects -g 1
    want = sum(b - a for a, b in frames)
    got = int(subprocess.run(["ffprobe", "-v", "error", "-count_packets", "-select_streams", "v:0", "-show_entries",
                              "stream=nb_read_packets", "-of", "csv=p=0", str(tmp)],
                             capture_output=True, text=True).stdout.split()[0])
    if got != want:
        raise RuntimeError(f"intermediate has {got} frames, expected {want}")
    tmp.replace(out)
    return out


def frame_of(t: float, frames, fps: Fraction, snap: int = 4) -> int:
    """Output time -> output frame number, snapped onto an edit join within `snap` frames, so
    overlays, punch-ins and joins meant to coincide land on the SAME frame (1-frame offsets
    from rounding showed up as flicker / double cuts)."""
    n = round(t * float(fps))
    joins = _starts(frames)[1:]
    near = min(joins, key=lambda j: abs(j - n), default=None)
    return near if near is not None and abs(near - n) <= snap else n


def in_source_order(frames) -> bool:
    return all(b0 <= a1 for (_, b0), (a1, _) in zip(frames, frames[1:]))


def zoom_filter(path: Path, frames, fps: Fraction, width: int, height: int) -> str:
    """zoompan expression for instant punch-ins; crops are frame fractions (x, y, w, h)."""
    zooms = json.loads(path.read_text(encoding="utf-8"))["zooms"]
    z_expr, x_expr, y_expr = "1", "0", "0"
    for zm in reversed(zooms):
        a = frame_of(to_output_clamped(zm["src_start"], frames, fps), frames, fps)
        b = frame_of(to_output_clamped_end(zm["src_end"], frames, fps), frames, fps)
        x, y, w, _ = zm["crop"]
        # Frame numbers, not time: 'it' rounding put zoom changes a frame off edit joins and
        # overlay edges, which read as double cuts.
        cond = f"between(in,{a},{b - 1})"
        z_expr = f"if({cond},{1 / w:.4f},{z_expr})"
        x_expr = f"if({cond},{x * width:.1f},{x_expr})"
        y_expr = f"if({cond},{y * height:.1f},{y_expr})"
    return f"zoompan=z='{z_expr}':x='{x_expr}':y='{y_expr}':d=1:s={width}x{height}:fps={fps}"


def chain_latency(chain: str) -> int:
    """Samples of delay an FFmpeg audio chain adds (afftdn adds 1200 = 25 ms at 48 kHz). Measured
    with a noise burst so the voice chain can be compensated and stays in lip-sync."""
    rng = np.random.default_rng(1)
    x = np.zeros(SR * 3, np.float32)
    x[SR:SR + SR // 10] = rng.normal(0, 0.2, SR // 10)
    with tempfile.TemporaryDirectory() as tmp:
        src, dst = Path(tmp) / "b.wav", Path(tmp) / "o.wav"
        sf.write(str(src), np.stack([x, x], 1), SR)
        subprocess.run(["ffmpeg", "-nostdin", "-y", "-v", "error", "-i", str(src), "-af", chain, str(dst)], check=True)
        y, _ = sf.read(str(dst), dtype="float32", always_2d=True)
    y = np.abs(y.mean(1)[:len(x)])
    ref = np.abs(x[SR - SR // 20:SR + SR // 7])
    return max(0, int(np.argmax(np.correlate(y, ref, "valid"))) - (SR - SR // 20))


def build_audio(video: Path, frames, fps: Fraction, dst: Path, voice_chain: str | None = None):
    raw = dst.with_suffix(".src.wav")
    # Optional voice processing (EQ / compression / light denoise), run on the CONTINUOUS source
    # audio before any cuts, so the compressor and denoiser never see an edit point.
    af = ["-af", voice_chain] if voice_chain else []
    subprocess.run(["ffmpeg", "-nostdin", "-y", "-v", "error", "-i", str(video), "-map", "0:a:0", *af,
                    "-ac", "2", "-ar", str(SR), "-c:a", "pcm_f32le", str(raw)], check=True)
    audio, _ = sf.read(str(raw), dtype="float32", always_2d=True)
    raw.unlink()
    if voice_chain:
        lat = chain_latency(voice_chain)
        if lat:                                           # shift back into sync with the picture
            audio = np.vstack([audio[lat:], np.zeros((lat, audio.shape[1]), np.float32)])
            print(f"  voice chain: compensated {lat} samples ({lat / SR * 1000:.1f} ms) of filter delay")

    n_fade = int(FADE * SR)
    ramp = np.linspace(0.0, 1.0, n_fade, dtype=np.float32)[:, None]
    pieces = []
    for f0, f1 in frames:
        # Sample positions derived from frame numbers, so length matches video exactly.
        a, b = round(f0 / fps * SR), round(f1 / fps * SR)
        p = audio[a:b].copy()
        if len(p) < b - a:
            p = np.vstack([p, np.zeros((b - a - len(p), audio.shape[1]), np.float32)])
        if len(p) > 2 * n_fade:
            p[:n_fade] *= ramp
            p[-n_fade:] *= ramp[::-1]
        pieces.append(p)
    sf.write(str(dst), np.concatenate(pieces), SR, subtype="FLOAT")


def stabilized(src: Path, start: float, dur: float, cache: Path) -> Path:
    """Gently stabilize one B-roll insert (vidstab, two passes) and cache the result.

    Light settings on purpose (user: "a little bit of stabilization", don't make good footage
    worse): moderate smoothing, a fixed 3% crop to hide edge wobble, slight sharpening.
    """
    import hashlib
    cache.mkdir(parents=True, exist_ok=True)
    key = hashlib.md5(f"{src}|{start:.3f}|{dur:.3f}|v1".encode()).hexdigest()[:12]
    out = cache / f"stab_{key}.mp4"
    if out.exists():
        return out
    trim = ["-ss", f"{start:.3f}", "-t", f"{dur + 0.5:.3f}", "-i", str(src)]
    # The .trf path goes inside a filter string, so run in the cache dir with a bare file name.
    subprocess.run(["ffmpeg", "-nostdin", "-y", "-v", "error", *trim, "-an", "-vf",
                    "vidstabdetect=shakiness=5:accuracy=15:result=t.trf", "-f", "null", "-"],
                   check=True, cwd=cache)
    subprocess.run(["ffmpeg", "-nostdin", "-y", "-v", "error", *trim, "-an", "-vf",
                    "vidstabtransform=input=t.trf:smoothing=12:optzoom=0:zoom=3,unsharp=5:5:0.5",
                    "-c:v", "h264_nvenc", "-cq", "16", out.name], check=True, cwd=cache)
    return out


def decode(path: Path, tmp: Path) -> np.ndarray:
    """Any audio file -> float32 stereo at SR."""
    wav = tmp / f"dec_{abs(hash(str(path)))}.wav"
    if not wav.exists():
        subprocess.run(["ffmpeg", "-nostdin", "-y", "-v", "error", "-i", str(path), "-ac", "2", "-ar", str(SR),
                        "-c:a", "pcm_f32le", str(wav)], check=True)
    a, _ = sf.read(str(wav), dtype="float32", always_2d=True)
    return a


def snap_ranges(ranges, blocks, tol=0.5):
    """Snap music range edges onto question-block edges (edit.json "sections", already snapped to
    camera cuts). A start only snaps to a block START and an end to a block END: a bed written as
    566.6 when its block begins at 566.67 otherwise starts two frames inside the PREVIOUS block, which
    after re-ordering sits minutes away, and the bed came out negative-length and was skipped (v4-v7)."""
    starts = [b["src"][0] for b in blocks or []]
    ends = [b["src"][1] for b in blocks or []]
    near = lambda t, edges: min(edges, key=lambda e: abs(e - t)) if edges and min(abs(e - t) for e in edges) <= tol else t
    return [[near(r0, starts), near(r1, ends)] for r0, r1 in ranges]


def mix_audio(speech_wav: Path, plan_path: Path, frames, fps: Fraction, dst: Path, tmp: Path, blocks=None):
    """Music beds (crossfaded per section, ducked under speech) + SFX, then loudness to -14 LUFS.
    blocks = edit.json "sections" (re-ordered question blocks), used to snap bed edges onto them."""
    import pyloudnorm as pyln
    cfg = json.loads(plan_path.read_text(encoding="utf-8"))
    speech, _ = sf.read(str(speech_wav), dtype="float32", always_2d=True)
    n = len(speech)
    meter = pyln.Meter(SR)
    speech_lufs = meter.integrated_loudness(speech)

    # Speech activity per 10 ms -> smoothed duck gain (fast attack, slow release).
    hop = SR // 100
    mono = speech.mean(axis=1)
    rms = np.sqrt(np.convolve(mono[: n // hop * hop].reshape(-1, hop).__pow__(2).mean(1), np.ones(5) / 5, "same"))
    db = 20 * np.log10(rms + 1e-9)
    active = db > np.percentile(db, 90) - 25
    duck = np.zeros(len(active), np.float32)
    g = 0.0
    for i, on in enumerate(active):
        target = -cfg.get("duck_db", 6) if on else 0.0
        g += (target - g) * (0.35 if target < g else 0.03)   # attack ~30 ms, release ~350 ms
        duck[i] = g
    duck = np.repeat(10 ** (duck / 20), hop)
    duck = np.pad(duck, (0, max(0, n - len(duck))), constant_values=1.0)[:n, None]

    music = np.zeros_like(speech)
    xf = int(1.5 * SR)
    sections = cfg.get("music", [])
    for k, m in enumerate(sections):
        # A bed covers one source range, or several "src_ranges" that sit back to back in the
        # output (re-ordered question blocks), so one track plays across them without restarting.
        ranges = snap_ranges(m.get("src_ranges") or [[m["src_start"], m["src_end"]]], blocks)
        a = int(min(to_output_clamped(r[0], frames, fps) for r in ranges) * SR)
        b = int(max(to_output_clamped_end(r[1], frames, fps) for r in ranges) * SR)
        b = min(b, n)
        if k > 0:
            a = max(0, a - xf // 2)                                     # overlap for the crossfade
        if k < len(sections) - 1:
            b = min(n, b + xf // 2)
        if b - a < SR:
            print(f"  WARNING: music bed {Path(m['file']).stem!r} ({m.get('why', '')}) maps to "
                  f"{a / SR:.2f}-{b / SR:.2f}s in the cut and is SKIPPED: check its src ranges against the blocks",
                  file=sys.stderr)
            continue
        track = decode(Path(m["file"]), tmp)
        loud = meter.integrated_loudness(track[: min(len(track), 60 * SR)])
        track *= 10 ** ((speech_lufs - cfg.get("music_below_speech_db", 20) - loud) / 20)
        need = b - a
        out = track[:need].copy()
        while len(out) < need:                                          # loop with a crossfade
            nxt = track[: need - len(out) + xf]
            ramp = np.linspace(0, 1, min(xf, len(nxt), len(out)), dtype=np.float32)[:, None]
            m_ = len(ramp)
            out[-m_:] = out[-m_:] * (1 - ramp) + nxt[:m_] * ramp
            out = np.concatenate([out, nxt[m_:]])
        out = out[:need]
        fin = np.linspace(0, 1, min(xf, need), dtype=np.float32)[:, None]
        out[: len(fin)] *= fin                                          # crossfade in (first bed: fade in)
        out[-len(fin):] *= fin[::-1]                                    # crossfade / fade out
        music[a:b] += out
    music *= duck

    sfx = np.zeros_like(speech)
    speech_peak = np.percentile(np.abs(speech), 99.9)
    for s in cfg.get("sfx", []):
        t = to_output_time(s["src_t"], frames, fps)
        if t is None:
            continue
        clip = decode(Path(s["file"]), tmp)
        peak = np.abs(clip).max() or 1.0
        clip = clip * (speech_peak / peak) * 10 ** ((s.get("gain_db", 0) - 4) / 20)
        a = int(t * SR)
        e = min(n, a + len(clip))
        sfx[a:e] += clip[: e - a]

    mix = speech + music + sfx
    raw = tmp / "mix.wav"
    sf.write(str(raw), mix, SR, subtype="FLOAT")
    # Two-pass loudnorm to YouTube's -14 LUFS with a -1.5 dBTP ceiling.
    p1 = subprocess.run(["ffmpeg", "-nostdin", "-hide_banner", "-i", str(raw), "-af",
                         "loudnorm=I=-14:TP=-1.5:LRA=11:print_format=json", "-f", "null", "-"],
                        capture_output=True, text=True).stderr
    meas = json.loads(p1[p1.rindex("{"): p1.rindex("}") + 1])
    af = (f"loudnorm=I=-14:TP=-1.5:LRA=11:measured_I={meas['input_i']}:measured_TP={meas['input_tp']}:"
          f"measured_LRA={meas['input_lra']}:measured_thresh={meas['input_thresh']}:"
          f"offset={meas['target_offset']}:linear=true")
    subprocess.run(["ffmpeg", "-nostdin", "-y", "-v", "error", "-i", str(raw), "-af", af, "-ar", str(SR),
                    "-c:a", "pcm_s16le", str(dst)], check=True)
    print(f"  audio: speech {speech_lufs:.1f} LUFS, {len(sections)} music beds, "
          f"{sum(1 for s in cfg.get('sfx', []) if to_output_time(s['src_t'], frames, fps) is not None)} SFX "
          f"-> -14 LUFS")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("plan", type=Path)
    ap.add_argument("video", type=Path)
    ap.add_argument("out", type=Path)
    ap.add_argument("--final", action="store_true", help="full-quality encode")
    ap.add_argument("--zooms", type=Path, help="punch-in plan from punchins.py")
    ap.add_argument("--graphics", type=Path,
                    help='JSON list of {"file": ..., "src_start": <source seconds>, '
                         '"show": [[a, b], ...] (optional, graphic-local seconds)} overlays')
    ap.add_argument("--broll", type=Path,
                    help='JSON list of {"file": <relative to --broll-root>, "in": s, "dur": s, "src_start": s}')
    ap.add_argument("--broll-root", type=Path, default=Path("."))
    ap.add_argument("--audio", type=Path, help="music + SFX plan (mixed and loudness-normalized)")
    args = ap.parse_args()

    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    fps = probe_fps(args.video)
    frames = [(round(s * fps), round(e * fps)) for s, e in plan["keeps"]]
    frames = [(a, b) for a, b in frames if b > a]
    width, height = probe_size(args.video)

    # Overlays: graphics (whole file, optional show windows) and B-roll (trimmed from the source).
    overlays = []
    for g in (json.loads(args.graphics.read_text(encoding="utf-8")) if args.graphics else []):
        dur = probe_duration(Path(g["file"]))
        overlays.append({"file": g["file"], "src_start": g["src_start"], "dur": dur, "in": None,
                         "show": g.get("show") or [[0, dur]], "label": Path(g["file"]).name})
    for b in (json.loads(args.broll.read_text(encoding="utf-8")) if args.broll else []):
        src, start = args.broll_root / b["file"], b["in"]
        if b.get("stabilize"):
            src, start = stabilized(src, b["in"], b["dur"], args.plan.parent / "cache"), 0.0
        overlays.append({"file": str(src), "src_start": b["src_start"], "dur": b["dur"], "broll": True,
                         "in": start, "show": [[0, b["dur"]]], "label": f"B-roll {Path(b['file']).stem}",
                         "move": b.get("move")})

    piece_inputs = []
    if in_source_order(frames):
        # Constant-frame-rate first, then keep frames by number: exact and drift-free.
        select = "+".join(f"between(n,{a},{b - 1})" for a, b in frames)
        graph = [f"[0:v]fps={fps},select='{select}',setpts=N/({fps}*TB)[cut]"]
    else:
        # Re-ordered edit. Per-piece seeks on long-GOP video are not frame-exact (pieces came out a
        # few frames long/short, so joins drifted off the plan: double cuts, slight A/V slip).
        # So: render every kept frame once IN SOURCE ORDER with the exact select path into an
        # all-keyframe intermediate, then cut pieces from it, where every seek is exact.
        src_order = sorted(range(len(frames)), key=lambda k: frames[k][0])
        inter_at, acc = {}, 0
        for k in src_order:
            inter_at[k] = acc
            acc += frames[k][1] - frames[k][0]
        base = intermediate(args.video, [frames[k] for k in src_order], fps, args.plan.parent / "cache",
                            final=args.final)
        graph, labels = [], []
        for k, (a, b) in enumerate(frames):
            n = b - a
            piece_inputs += ["-ss", f"{max(0.0, (inter_at[k] - 0.25) / float(fps)):.6f}", "-i", str(base)]
            labels.append(f"[p{k}]")
            graph.append(f"[{{PIECE{k}}}:v]trim=end_frame={n},setpts=PTS-STARTPTS[p{k}]")
        graph.append(f"{''.join(labels)}concat=n={len(frames)}:v=1:a=0,setpts=N/({fps}*TB)[cut]")
    graph.append(f"[cut]{zoom_filter(args.zooms, frames, fps, width, height)}[base]"
                 if args.zooms else "[cut]null[base]")
    last = "base"
    ov_inputs = []
    # B-roll first, graphics after: later overlays draw on top, so callouts sit above their B-roll.
    for i, o in enumerate(sorted(overlays, key=lambda o: (not o.get("broll"), o["src_start"]))):
        out_t = to_output_time(o["src_start"], frames, fps)
        if out_t is None:
            print(f"  skip {o['label']}: anchor {o['src_start']}s was cut", file=sys.stderr)
            continue
        on_screen = max(b for _, b in o["show"])          # only the visible part has to stay in sync
        end_t = to_output_clamped_end(o["src_start"] + on_screen, frames, fps)   # end time: the piece that ENDS there
        # B-roll may deliberately span a cut (it hides the jump); graphics must not drift from speech.
        if not o.get("broll") and (end_t is None or abs(end_t - (out_t + on_screen)) > 0.05):
            print(f"  warning: a cut falls inside {o['label']}; it will drift from the speech", file=sys.stderr)
        # Snap the overlay's own start onto the frame grid / a nearby join too, not just its enable
        # window: otherwise the window opens on the join but the content arrives a frame later,
        # leaving one frame of whatever is underneath (seen as a flash before the sphere graphic).
        out_t = frame_of(out_t, frames, fps) / float(fps)
        trim = ["-ss", f"{o['in']:.3f}", "-t", f"{o['dur'] + 0.5:.3f}"] if o["in"] is not None else []
        n = 2 + ov_inputs.count("-i")  # inputs: 0 video, 1 audio, then overlays, then re-ordered pieces
        ov_inputs += [*trim, "-i", o["file"]]
        move = ""
        if o.get("move"):
            # Slow push/pan on a static shot: zoom z0->z1 while the window centre glides from
            # "from" to "to" (fractions of the available pan range). Upscaled 2x first so the
            # integer zoompan offsets don't make slow moves judder.
            mv, nf = o["move"], max(1, int(o["dur"] * float(fps)))
            (z0, z1), (fx0, fy0), (fx1, fy1) = mv["zoom"], mv["from"], mv["to"]
            pr = f"(on/{nf})"
            move = (f"scale={width * 2}:{height * 2},zoompan=z='{z0}+({z1 - z0})*{pr}':"
                    f"x='(iw-iw/zoom)*({fx0}+({fx1 - fx0})*{pr})':y='(ih-ih/zoom)*({fy0}+({fy1 - fy0})*{pr})':"
                    f"d=1:s={width}x{height}:fps={fps},")
        graph.append(f"[{n}:v]fps={fps},scale={width}:{height}:force_original_aspect_ratio=increase,"
                     f"crop={width}:{height},{move}format=yuva420p,setpts=PTS-STARTPTS+{out_t:.4f}/TB[o{i}]")
        # The overlay keeps running in sync but is only on screen inside its show windows.
        # Frame numbers (n), snapped to joins; between() is inclusive, so end on the frame before.
        enable = "+".join(f"between(n,{frame_of(out_t + a, frames, fps)},{frame_of(out_t + b, frames, fps) - 1})"
                          for a, b in o["show"])
        graph.append(f"[{last}][o{i}]overlay=eof_action=pass:enable='{enable}'[v{i}]")
        last = f"v{i}"
    print(f"  {len(overlays)} overlays ({sum(o.get('broll', False) for o in overlays)} B-roll)")
    first_piece = 2 + ov_inputs.count("-i")
    vf = ";".join(graph)
    for k in range(len(frames)):
        vf = vf.replace(f"{{PIECE{k}}}", str(first_piece + k))

    if args.final:
        venc = ["-c:v", "h264_nvenc", "-preset", "p6", "-rc", "vbr", "-cq", "19", "-b:v", "0"]
        aenc = ["-c:a", "aac", "-b:a", "320k"]
    else:
        venc = ["-c:v", "h264_nvenc", "-preset", "p3", "-cq", "28"]
        aenc = ["-c:a", "aac", "-b:a", "160k"]

    with tempfile.TemporaryDirectory() as tmp:
        wav = Path(tmp) / "audio.wav"
        chain = json.loads(args.audio.read_text(encoding="utf-8")).get("voice_chain") if args.audio else None
        build_audio(args.video, frames, fps, wav, chain)
        if args.audio:
            mixed = Path(tmp) / "mixed.wav"
            mix_audio(wav, args.audio, frames, fps, mixed, Path(tmp), blocks=plan.get("sections"))
            wav = mixed
        vf_file = Path(tmp) / "vf.txt"
        vf_file.write_text(vf, encoding="utf-8")
        args.out.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["ffmpeg", "-nostdin", "-y", "-v", "error", "-stats", "-i", str(args.video), "-i", str(wav),
                        *ov_inputs, *piece_inputs, "-/filter_complex", str(vf_file), "-map", f"[{last}]", "-map", "1:a:0",
                        *venc, *aenc, "-shortest", "-movflags", "+faststart", str(args.out)],
                       check=True)

    total = sum(b - a for a, b in frames) / fps
    print(f"rendered {len(frames)} pieces, {float(total)/60:.2f} min -> {args.out}")


if __name__ == "__main__":
    sys.exit(main())
