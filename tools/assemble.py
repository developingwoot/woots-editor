"""Add the chosen intro and/or outro takes (from <name>.footage.json) to a finished render.

Usage:
    python assemble.py <footage.json> <main.mp4> <out.mp4> [--audio audio.json] [--quality final|preview]

The main render is NOT re-rendered: the intro and outro are encoded to match it (size, fps, encoder)
and joined, by stream copy when the streams are compatible (verified; otherwise one re-encode).
  * each take is trimmed to its in/out, frame-exact at the main render's fps;
  * its audio gets the voice chain only if footage.json says so (the chain was tuned for the interview
    lavs; a stand-mic intro often sounds better without), then loudness-matched to -14 LUFS like the main;
  * the bridge: the intro fades out to navy at its end, the outro fades in from navy at its start, with a
    whoosh from the SFX folder (the one the graphics already use) on each side;
  * writes <out>.assembly.json (which main it was built from, bookend lengths, a config hash) so the
    review app can map times in the assembled video back to the plan (output time = intro length + main).
Output time in the assembled video = intro length + output time of the main render.
"""
import argparse
import json
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

import numpy as np
import soundfile as sf

import footage_cfg
import render

NAVY = "0x142C44"
SR = render.SR


def ff(*args):
    subprocess.run(["ffmpeg", "-nostdin", "-y", "-v", "error", *map(str, args)], check=True)


def stream(path: Path, kind: str) -> dict:
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", kind, "-show_entries",
                          "stream=codec_name,profile,level,pix_fmt,width,height,r_frame_rate,time_base,sample_rate,"
                          "channels,bit_rate", "-of", "json", str(path)], capture_output=True, text=True, check=True).stdout
    s = json.loads(out).get("streams") or []
    if not s:
        raise ValueError(f"{path.name} has no {'video' if kind == 'v:0' else 'audio'} stream")
    return s[0]


def packets(path: Path) -> int:
    out = subprocess.run(["ffprobe", "-v", "error", "-count_packets", "-select_streams", "v:0", "-show_entries",
                          "stream=nb_read_packets", "-of", "csv=p=0", str(path)], capture_output=True, text=True).stdout
    return int(out.split()[0])


def loudnorm(src: Path, dst: Path):
    """Two-pass loudnorm to YouTube's -14 LUFS / -1.5 dBTP (same target as the main render's mix)."""
    p1 = subprocess.run(["ffmpeg", "-nostdin", "-hide_banner", "-i", str(src), "-af",
                         "loudnorm=I=-14:TP=-1.5:LRA=11:print_format=json", "-f", "null", "-"],
                        capture_output=True, text=True).stderr
    meas = json.loads(p1[p1.rindex("{"): p1.rindex("}") + 1])
    af = (f"loudnorm=I=-14:TP=-1.5:LRA=11:measured_I={meas['input_i']}:measured_TP={meas['input_tp']}:"
          f"measured_LRA={meas['input_lra']}:measured_thresh={meas['input_thresh']}:"
          f"offset={meas['target_offset']}:linear=true")
    ff("-i", src, "-af", af, "-ar", SR, "-c:a", "pcm_s16le", dst)


def find_whoosh(audio_cfg: dict, br: dict):
    if br.get("whoosh_file"):
        return br["whoosh_file"]
    for s in audio_cfg.get("sfx", []):
        if "woosh" in s["file"].lower() or "whoosh" in s["file"].lower():
            return s["file"]
    return None


def build_piece(which, spec, br, fps, size, quality, chain, whoosh, tmp: Path) -> tuple[Path, int]:
    """Encode one take to <tmp>/<which>.mp4 matching the main render. Returns (path, frames)."""
    clip = Path(spec["file"])
    W, H = size
    cfps = render.probe_fps(clip)
    n = round((spec["out"] - spec["in"]) * float(fps))
    if n < 1:
        raise ValueError(f"{which}: trim is shorter than one frame")
    dur = n / float(fps)
    # audio: the take's own sound over exactly the trimmed range
    raw = tmp / f"{which}.raw.wav"
    render.build_audio(clip, [(round(spec["in"] * cfps), round(spec["out"] * cfps))], cfps, raw, chain)
    audio, _ = sf.read(str(raw), dtype="float32", always_2d=True)
    want = round(n * SR / float(fps))
    audio = np.vstack([audio, np.zeros((max(0, want - len(audio)), audio.shape[1]), np.float32)])[:want]
    if whoosh:
        w = render.decode(Path(whoosh), tmp)
        speech_peak = np.percentile(np.abs(audio), 99.9) or 0.1
        w = w * (speech_peak / (np.abs(w).max() or 1.0)) * 10 ** ((br["whoosh_db"] - 4) / 20)
        a = max(0, int((dur - 0.35 if which == "intro" else 0.0) * SR))     # intro: just before the join
        e = min(len(audio), a + len(w))
        audio[a:e] += w[: e - a]
    mixed = tmp / f"{which}.mix.wav"
    sf.write(str(mixed), audio, SR, subtype="FLOAT")
    norm = tmp / f"{which}.norm.wav"
    loudnorm(mixed, norm)
    # picture: fit to the main frame (pad with navy), conform fps, fade through navy at the join
    vf = (f"fps={fps},scale={W}:{H}:force_original_aspect_ratio=decrease,"
          f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color={NAVY},setsar=1,format=yuv420p")
    f = float(br["fade"])
    if f > 0 and which == "intro":
        vf += f",fade=t=out:st={max(0.0, dur - f):.3f}:d={f}:color={NAVY}"
    if f > 0 and which == "outro":
        vf += f",fade=t=in:st=0:d={f}:color={NAVY}"
    vf += ",format=yuv420p"                      # fade with a colour converts to RGB (4:4:4) otherwise
    venc = (["-c:v", "h264_nvenc", "-preset", "p6", "-rc", "vbr", "-cq", "19", "-b:v", "0"] if quality == "final"
            else ["-c:v", "h264_nvenc", "-preset", "p3", "-cq", "28"])
    abr = "320k" if quality == "final" else "160k"
    out = tmp / f"{which}.mp4"
    ff("-ss", f"{spec['in']:.3f}", "-i", clip, "-i", norm, "-vf", vf, "-map", "0:v:0", "-map", "1:a:0",
       "-frames:v", n, *venc, "-c:a", "aac", "-b:a", abr, "-ar", SR, "-ac", 2, "-shortest", out)
    got = packets(out)
    if got != n:
        # A trim that ends on the clip's last frame can come up a frame short (frame-boundary rounding).
        if n - 2 <= got < n:
            print(f"  {which}: the clip ends {n - got} frame(s) before the trim out point; using {got} frames")
        else:
            raise ValueError(f"{which}: encoded {got} frames, expected {n} (is the trim past the end of the clip?)")
    return out, got


def same_params(a: dict, b: dict) -> bool:
    keys = ("codec_name", "profile", "level", "pix_fmt", "width", "height", "r_frame_rate", "time_base",
            "sample_rate", "channels")
    return all(a.get(k) == b.get(k) for k in keys)


def join(parts: list[Path], out: Path, quality: str, tmp: Path) -> str:
    """Concatenate [intro, main, outro] by stream copy when the streams match, else re-encode."""
    ref_v, ref_a = stream(parts[0], "v:0"), stream(parts[0], "a:0")
    ok = all(same_params(ref_v, stream(p, "v:0")) and same_params(ref_a, stream(p, "a:0")) for p in parts[1:])
    if ok:
        lst = tmp / "concat.txt"
        lst.write_text("".join(f"file '{p.as_posix()}'\n" for p in parts), encoding="utf-8")
        tmpout = out.with_name(out.stem + ".part.mp4")
        ff("-f", "concat", "-safe", 0, "-i", lst, "-c", "copy", "-movflags", "+faststart", tmpout)
        want = sum(packets(p) for p in parts)
        total = sum(render.probe_duration(p) for p in parts)
        if packets(tmpout) == want and abs(render.probe_duration(tmpout) - total) < 0.15:
            tmpout.replace(out)
            return "copy"
        tmpout.unlink(missing_ok=True)
        print("  stream-copy join did not verify; re-encoding instead", file=sys.stderr)
    else:
        print("  streams differ between main and bookends; re-encoding the join", file=sys.stderr)
    inputs = [x for p in parts for x in ("-i", p)]
    fc = "".join(f"[{i}:v][{i}:a]" for i in range(len(parts))) + f"concat=n={len(parts)}:v=1:a=1[v][a]"
    venc = (["-c:v", "h264_nvenc", "-preset", "p6", "-rc", "vbr", "-cq", "19", "-b:v", "0"] if quality == "final"
            else ["-c:v", "h264_nvenc", "-preset", "p3", "-cq", "28"])
    ff(*inputs, "-filter_complex", fc, "-map", "[v]", "-map", "[a]", *venc, "-c:a", "aac",
       "-b:a", "320k" if quality == "final" else "160k", "-movflags", "+faststart", out)
    return "re-encode"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("footage", type=Path)
    ap.add_argument("main", type=Path)
    ap.add_argument("out", type=Path)
    ap.add_argument("--audio", type=Path, help="audio.json (voice chain + the whoosh SFX file)")
    ap.add_argument("--quality", choices=["final", "preview"], help="default: preview if the name says so")
    args = ap.parse_args()

    cfg = footage_cfg.load(args.footage)
    rb = footage_cfg.resolved_bookends(cfg)
    if "intro" not in rb and "outro" not in rb:
        sys.exit("footage.json has no intro or outro take chosen")
    if args.main.with_name(args.main.stem + ".assembly.json").exists():
        sys.exit(f"{args.main.name} already has an intro/outro; give the main render, not an assembled video")
    if args.out.resolve() == args.main.resolve():
        sys.exit("out must be a new file")
    quality = args.quality or ("preview" if "preview" in args.main.name.lower() else "final")
    br = rb["bridge"]
    audio_cfg = json.loads(args.audio.read_text(encoding="utf-8")) if args.audio and args.audio.exists() else {}
    chain = audio_cfg.get("voice_chain") if br.get("voice_chain") else None
    whoosh = find_whoosh(audio_cfg, br) if br.get("whoosh") else None
    if br.get("whoosh") and not whoosh:
        print("  note: no whoosh SFX found in audio.json; the bridge is the fade only")

    fps = render.probe_fps(args.main)
    size = render.probe_size(args.main)
    main_dur = render.probe_duration(args.main)
    print(f"main: {main_dur:.2f}s {size[0]}x{size[1]} @ {float(fps):g} fps, {quality}")
    info = {}
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        parts = []
        for which in ("intro", "main", "outro"):
            if which == "main":
                parts.append(args.main)
                continue
            if which not in rb:
                continue
            print(f"{which}: {Path(rb[which]['file']).name} {rb[which]['in']}-{rb[which]['out']}s")
            p, n = build_piece(which, rb[which], br, fps, size, quality, chain, whoosh, tmp)
            parts.append(p)
            info[which] = {"file": rb[which]["rel"], "in": rb[which]["in"], "out": rb[which]["out"],
                           "frames": n, "dur": n / float(fps)}
        args.out.parent.mkdir(parents=True, exist_ok=True)
        how = join(parts, args.out, quality, tmp)

    try:
        main_ref = str(args.main.resolve().relative_to(args.out.parent.resolve()))
    except ValueError:
        main_ref = str(args.main)
    side = {"made": datetime.now().isoformat(timespec="seconds"), "main": main_ref, "main_dur": main_dur,
            "fps": float(fps), "config_hash": footage_cfg.bookends_hash(rb), "join": how, **info,
            "total_dur": render.probe_duration(args.out)}
    args.out.with_name(args.out.stem + ".assembly.json").write_text(json.dumps(side, indent=1), encoding="utf-8")
    print(f"assembled ({how}): {side['total_dur']:.2f}s = "
          f"{info.get('intro', {}).get('dur', 0):.2f} intro + {main_dur:.2f} main + {info.get('outro', {}).get('dur', 0):.2f} outro"
          f"\n-> {args.out}")


if __name__ == "__main__":
    sys.exit(main())
