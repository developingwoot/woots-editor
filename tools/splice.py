"""Assemble the full video: intro + title card + main (with mid-video inserts) + outro.

Usage:
    python splice.py <splice.json> <main.mp4> <edit.json> <out.mp4> [--quality final|preview]

splice.json:
{
  "folder": "<footage folder>",
  "intro":  {"file": "<rel>", "in": s, "out": s, "chain": "<ffmpeg voice chain>"},
  "title_card": {"file": "<abs mp4>", "sfx": [{"file": ..., "at": s, "gain_db": 0}]},
  "inserts": [{"file": "<rel>", "in": s, "out": s, "chain": ..., "before_section": "<sections id>",
               "label": "subscribe"}],
  "outro":  {"file": "<rel>", "in": s, "out": s, "chain": ...},
  "bridge": {"fade": 0.3, "whoosh": "<abs sfx file>", "whoosh_db": -2}
}

assemble.py adds bookends to an untouched main by stream copy. An insert in the MIDDLE needs the main
split, so this tool re-encodes the picture once (main cut on exact frames at a block join, found from
edit.json's sections) and builds the soundtrack sample-exact from the pieces: each take gets its own
voice chain (matched to the processed interview), loudness -14 LUFS, fades through navy and a whoosh at
each join; the main's own mix is kept and only faded for 40 ms at the splice.
Writes <out>.assembly.json with every piece's place (for mapping review notes back to the plan).
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

import assemble
import render

SR = render.SR
NAVY = assemble.NAVY


def venc(quality):
    return (["-c:v", "h264_nvenc", "-preset", "p6", "-rc", "vbr", "-cq", "17", "-b:v", "0"] if quality == "final"
            else ["-c:v", "h264_nvenc", "-preset", "p3", "-cq", "28"])


def take_piece(name, spec, folder, fps, size, br, tmp, fade_in, fade_out, whoosh_at):
    """Trim a take frame-exact, voice chain + loudness to -14, fades through navy. -> (video mp4, audio, frames)"""
    clip = Path(folder) / spec["file"]
    cfps = render.probe_fps(clip)
    # A take may be several segments of one recording (fluff cut out); "punch" zooms each segment
    # (e.g. [1.0, 1.12]) so the cut between them reads as a deliberate punch-in, not a jump.
    segs = spec.get("segments") or [[spec["in"], spec["out"]]]
    punch = spec.get("punch") or [1.0] * len(segs)
    seg_n = [round((b - a) * float(fps)) for a, b in segs]
    n = sum(seg_n)
    dur = n / float(fps)
    raw = tmp / f"{name}.raw.wav"
    # "audio_delay_ms": the recording's sound arrives EARLY (OBS/camera capture latency), so the sound heard at
    # output time t is taken from source time t - delay. Picture is untouched; only the audio window moves.
    delay = float(spec.get("audio_delay_ms", 0)) / 1000
    render.build_audio(clip, [(round((a - delay) * cfps), round((b - delay) * cfps)) for a, b in segs], cfps, raw,
                       spec.get("chain"))
    audio, _ = sf.read(str(raw), dtype="float32", always_2d=True)
    want = round(n * SR / float(fps))
    audio = np.vstack([audio, np.zeros((max(0, want - len(audio)), 2), np.float32)])[:want]
    f = float(br["fade"])
    f_out = float(spec.get("fade_out", f))              # a take can use a shorter fade-out so it never
    k, k_out = int(f * SR), int(f_out * SR)             # overlaps the last word (voice-end, not ASR end)
    if fade_in:
        audio[:k] *= np.linspace(0, 1, k, dtype=np.float32)[:, None]
    if fade_out:
        audio[-k_out:] *= np.linspace(1, 0, k_out, dtype=np.float32)[:, None]
    black = spec.get("fade_to_black_at")           # source time (e.g. on "Until next time")
    if black is not None:
        ka = int(0.35 * SR)                         # the words stay audible; only the tail fades
        audio[-ka:] *= np.linspace(1, 0, ka, dtype=np.float32)[:, None]
    mixed, norm = tmp / f"{name}.mix.wav", tmp / f"{name}.norm.wav"
    sf.write(str(mixed), audio, SR, subtype="FLOAT")
    assemble.loudnorm(mixed, norm)
    audio, _ = sf.read(str(norm), dtype="float32", always_2d=True)
    audio = np.vstack([audio, np.zeros((max(0, want - len(audio)), 2), np.float32)])[:want]
    if br.get("whoosh"):
        w = render.decode(Path(br["whoosh"]), tmp)
        peak = np.percentile(np.abs(audio), 99.9) or 0.1
        w = w * (peak / (np.abs(w).max() or 1.0)) * 10 ** ((br.get("whoosh_db", -2) - 4) / 20)
        for at in whoosh_at:
            a = max(0, int((dur - 0.35 if at == "end" else 0.0) * SR))
            e = min(len(audio), a + len(w))
            audio[a:e] += w[: e - a]
    W, H = size
    cx, cy = spec.get("punch_center", [0.5, 0.42])     # where the punch-in centres (frame fractions)
    inputs, fc = [], []
    for i, ((a, b), z, sn) in enumerate(zip(segs, punch, seg_n)):
        inputs += ["-ss", f"{a:.3f}", "-t", f"{b - a + 0.5:.3f}", "-i", clip]
        zoom = (f",crop=iw/{z}:ih/{z}:(iw-iw/{z})*{cx}:(ih-ih/{z})*{cy}" if z and z != 1.0 else "")
        fc.append(f"[{i}:v]fps={fps}{zoom},scale={W}:{H}:force_original_aspect_ratio=decrease,"
                  f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color={NAVY},setsar=1,format=yuv420p,"
                  f"trim=end_frame={sn},setpts=PTS-STARTPTS[s{i}]")
    post = []
    if fade_in:
        post.append(f"fade=t=in:st=0:d={f}:color={NAVY}")
    if fade_out:
        post.append(f"fade=t=out:st={max(0.0, dur - f_out):.3f}:d={f_out}:color={NAVY}")
    if black is not None:
        st = max(0.0, sum(min(black, b) - a for a, b in segs if black > a))   # source time -> take time
        post.append(f"fade=t=out:st={st:.3f}:d={max(0.1, dur - st):.3f}:color=black")
    post.append("format=yuv420p")
    fc.append("".join(f"[s{i}]" for i in range(len(segs))) + f"concat=n={len(segs)}:v=1:a=0," + ",".join(post) + "[v]")
    fcf = tmp / f"{name}.fc.txt"
    fcf.write_text(";".join(fc), encoding="utf-8")
    out = tmp / f"{name}.mp4"
    assemble.ff(*inputs, "-/filter_complex", fcf, "-map", "[v]", "-an", "-frames:v", n, "-c:v", "libx264",
                "-preset", "veryfast", "-crf", "10", out)                    # near-lossless intermediate
    got = assemble.packets(out)
    if not n - 2 <= got <= n:
        raise ValueError(f"{name}: {got} frames, expected {n}")
    return out, audio[: round(got * SR / float(fps))], got


def add_intro_music(spec, pieces, tmp, fps):
    """A building-suspense bed under the intro + title card, landing its peak on the title.

    spec: {"file": <abs>, "peak_db": -6, "land_after_title_start": 0.25, "fade_out": 1.4, "duck_db": 4,
           "impact": {"file": <abs>, "gain_db": -9}}
    The track's loudest second is found, then the track is placed so that peak arrives
    `land_after_title_start` s after the title card begins (the build runs under the host's voice and breaks
    on the title). Level is set relative to the host's speech (peak_db under it); the bed ducks a little under
    speech, fades out over the rest of the title card. Modifies the intro/title_card audio in `pieces`.
    """
    import librosa
    ii = next(i for i, p in enumerate(pieces) if p[0] == "intro")
    ti = next(i for i, p in enumerate(pieces) if p[0] == "title_card")
    intro, card = pieces[ii][3], pieces[ti][3]
    both = np.vstack([intro, card])
    n, t_title = len(both), len(intro) / SR
    y, sr = librosa.load(spec["file"], sr=SR, mono=False)
    y = y if y.ndim == 2 else np.stack([y, y])
    y = y.T.astype(np.float32)
    # Optional excerpt: "from" (track s) + "length" (s) picks a natural build inside a longer track;
    # "peak_at" (excerpt s) says where its climax is (else the loudest second); "fade_in" softens the entry.
    frm = int(float(spec.get("from", 0)) * SR)
    y = y[frm: frm + int(float(spec["length"]) * SR)] if spec.get("length") else y[frm:]
    if spec.get("fade_in"):
        k = int(float(spec["fade_in"]) * SR)
        y[:k] *= np.linspace(0, 1, k, dtype=np.float32)[:, None]
    mono = y.mean(1)
    hop = SR // 10
    env = np.array([np.sqrt(np.mean(mono[i:i + hop] ** 2)) for i in range(0, len(mono) - hop, hop)])
    if spec.get("peak_at") is not None:
        peak_i = int(float(spec["peak_at"]) * SR / hop)
    else:
        peak_i = int(np.argmax(np.convolve(env, np.ones(10) / 10, "same")))   # centre of the loudest second
    peak_t = peak_i * hop / SR
    land = t_title + spec.get("land_after_title_start", 0.25)
    start = int((land - peak_t) * SR)                                       # where track sample 0 goes
    bed = np.zeros_like(both)
    a, b = max(0, start), min(n, start + len(y))
    bed[a:b] = y[a - start: b - start]
    # level: the loudest second sits peak_db under the creator's voice (RMS of his speech frames)
    sp = both[: len(intro)].mean(1)
    fr = np.array([np.sqrt(np.mean(sp[i:i + hop] ** 2)) for i in range(0, len(sp) - hop, hop)])
    speech_rms = np.percentile(fr, 85)
    peak_rms = env[max(0, peak_i - 5): peak_i + 5].mean() or 1e-6
    bed *= speech_rms / peak_rms * 10 ** (spec.get("peak_db", -6) / 20)
    # duck under speech (fast attack, slow release), then fade out across the rest of the title card
    act = np.repeat(fr > speech_rms * 0.35, hop)
    act = np.pad(act, (0, max(0, n - len(act))))[:n]
    g, duck = 0.0, np.zeros(n, np.float32)
    for i in range(0, n, 480):
        tgt = -spec.get("duck_db", 4) if act[i] else 0.0
        g += (tgt - g) * (0.3 if tgt < g else 0.04)
        duck[i:i + 480] = g
    bed *= (10 ** (duck / 20))[:, None]
    fo = int(spec.get("fade_out", 1.4) * SR)
    t0 = int(land * SR)
    tail = np.ones(n, np.float32)
    seg = n - t0
    tail[t0:] = np.linspace(1, 0, seg, dtype=np.float32) ** 1.5 if seg > 0 else 1
    bed *= tail[:, None]
    mix = both + bed
    imp = spec.get("impact")
    if imp:
        x = render.decode(Path(imp["file"]), tmp)
        x = x * (np.percentile(np.abs(both[: len(intro)]), 99.9) / (np.abs(x).max() or 1)) * 10 ** (imp.get("gain_db", -9) / 20)
        p0 = int(t_title * SR)
        e = min(n, p0 + len(x))
        mix[p0:e] += x[: e - p0]
    # Look-ahead limiter at -1.5 dBFS: the music rides on top of speech that is already at the loudnorm
    # ceiling, so a voice peak plus the bed overshot (-0.5 dBFS). Only those peaks are pulled down.
    from scipy.ndimage import maximum_filter1d, minimum_filter1d
    ceil = 10 ** (-1.5 / 20)
    pk = maximum_filter1d(np.abs(mix).max(axis=1), size=480)                    # 10 ms look-ahead
    gain = np.minimum(1.0, ceil / (pk + 1e-9))
    gain = np.convolve(minimum_filter1d(gain, size=960), np.ones(480) / 480, "same")   # smooth attack/release
    mix = mix * np.minimum(gain, 1.0)[:, None]
    mix = np.clip(mix, -1, 1)
    pieces[ii] = (*pieces[ii][:3], mix[: len(intro)], *pieces[ii][4:])
    pieces[ti] = (*pieces[ti][:3], mix[len(intro):], *pieces[ti][4:])
    print(f"  intro music: {Path(spec['file']).name}, peak at track {peak_t:.1f}s lands {land:.2f}s "
          f"(title card starts {t_title:.2f}s), starts at {max(0, start) / SR:.2f}s, peak {spec.get('peak_db', -6)} dB under speech")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cfg", type=Path)
    ap.add_argument("main", type=Path)
    ap.add_argument("plan", type=Path)
    ap.add_argument("out", type=Path)
    ap.add_argument("--quality", choices=["final", "preview"], default="final")
    args = ap.parse_args()
    cfg = json.loads(args.cfg.read_text(encoding="utf-8"))
    br = {"fade": 0.3, "whoosh_db": -2, **(cfg.get("bridge") or {})}
    fps, size = render.probe_fps(args.main), render.probe_size(args.main)
    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    frames = [(round(s * fps), round(e * fps)) for s, e in plan["keeps"]]
    frames = [(a, b) for a, b in frames if b > a]
    starts = render._starts(frames)
    main_frames = assemble.packets(args.main)
    if main_frames != starts[-1] + frames[-1][1] - frames[-1][0]:
        sys.exit(f"{args.main.name} has {main_frames} frames but edit.json describes "
                 f"{starts[-1] + frames[-1][1] - frames[-1][0]}: render and plan don't match")

    # Split points: the first frame of the named block (always an edit join, so the cut is invisible).
    splits = []
    for ins in cfg.get("inserts", []):
        sec = next(s for s in plan["sections"] if s["id"] == ins["before_section"])
        j = render.frame_of(render.to_output_time(sec["src"][0] + 0.001, frames, fps), frames, fps, snap=4)
        if j not in starts:
            sys.exit(f"insert before '{ins['before_section']}': frame {j} is not an edit join")
        splits.append((j, ins))
    splits.sort(key=lambda x: x[0])

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        # main soundtrack, sample-exact
        mwav = tmp / "main.wav"
        assemble.ff("-i", args.main, "-vn", "-ac", 2, "-ar", SR, "-c:a", "pcm_f32le", mwav)
        main_audio, _ = sf.read(str(mwav), dtype="float32", always_2d=True)
        main_audio = np.vstack([main_audio, np.zeros((max(0, round(main_frames * SR / float(fps)) - len(main_audio)), 2),
                                                     np.float32)])[: round(main_frames * SR / float(fps))]
        pieces = []           # (kind, video input args, trim filter, audio array, frames, info)
        if cfg.get("intro"):
            v, a, n = take_piece("intro", cfg["intro"], cfg["folder"], fps, size, br, tmp, False, True, ["end"])
            pieces.append(("intro", ["-i", v], "", a, n, {"file": cfg["intro"]["file"]}))
        if cfg.get("title_card"):
            tc = cfg["title_card"]
            n = assemble.packets(Path(tc["file"]))
            a = np.zeros((round(n * SR / float(fps)), 2), np.float32)
            for s in tc.get("sfx", []):
                x = render.decode(Path(s["file"]), tmp)
                x = x * (0.25 / (np.abs(x).max() or 1)) * 10 ** (s.get("gain_db", 0) / 20)
                p0 = int(s["at"] * SR)
                e = min(len(a), p0 + len(x))
                a[p0:e] += x[: e - p0]
            pieces.append(("title_card", ["-i", tc["file"]],
                           f"fps={fps},scale={size[0]}:{size[1]},setsar=1,format=yuv420p", a, n, {"file": tc["file"]}))
        if cfg.get("intro_music"):
            add_intro_music(cfg["intro_music"], pieces, tmp, fps)
        prev = 0
        k40 = int(0.04 * SR)
        for idx, (j, ins) in enumerate(splits + [(main_frames, None)]):
            a = main_audio[round(prev * SR / float(fps)): round(j * SR / float(fps))].copy()
            if prev > 0:
                a[:k40] *= np.linspace(0, 1, k40, dtype=np.float32)[:, None]
            if ins is not None:
                a[-k40:] *= np.linspace(1, 0, k40, dtype=np.float32)[:, None]
            pieces.append(("main", ["-i", str(args.main)], f"trim=start_frame={prev}:end_frame={j},setpts=PTS-STARTPTS",
                           a, j - prev, {"main_from": prev, "main_to": j}))
            if ins is not None:
                v, ia, n = take_piece(f"insert{idx}", ins, cfg["folder"], fps, size, br, tmp, True, True, ["start", "end"])
                pieces.append(("insert", ["-i", v], "", ia, n,
                               {"file": ins["file"], "label": ins.get("label"), "before_section": ins["before_section"]}))
            prev = j
        if cfg.get("outro"):
            v, a, n = take_piece("outro", cfg["outro"], cfg["folder"], fps, size, br, tmp, True, False, ["start"])
            pieces.append(("outro", ["-i", v], "", a, n, {"file": cfg["outro"]["file"]}))

        # picture: one concat, exact frame counts per piece
        inputs, fc, labels = [], [], []
        for i, (_, inp, trim, _, n, _) in enumerate(pieces):
            inputs += inp
            chain = (trim + "," if trim else "") + f"trim=end_frame={n},setpts=PTS-STARTPTS"
            fc.append(f"[{i}:v]{chain}[p{i}]")
            labels.append(f"[p{i}]")
        fc.append(f"{''.join(labels)}concat=n={len(pieces)}:v=1:a=0,setpts=N/({fps}*TB)[v]")
        fcf = tmp / "fc.txt"
        fcf.write_text(";".join(fc), encoding="utf-8")
        # soundtrack
        audio = np.concatenate([p[3] for p in pieces])
        wav = tmp / "all.wav"
        sf.write(str(wav), np.clip(audio, -1, 1), SR, subtype="FLOAT")
        total_frames = sum(p[4] for p in pieces)
        print(f"  {len(pieces)} pieces, {total_frames} frames ({total_frames / float(fps):.2f}s)")
        args.out.parent.mkdir(parents=True, exist_ok=True)
        assemble.ff(*inputs, "-i", wav, "-/filter_complex", fcf, "-map", "[v]", "-map", f"{len(pieces)}:a:0",
                    *venc(args.quality), "-c:a", "aac", "-b:a", "320k" if args.quality == "final" else "160k",
                    "-frames:v", total_frames, "-movflags", "+faststart", args.out)

    got = assemble.packets(args.out)
    if got != total_frames:
        sys.exit(f"output has {got} frames, expected {total_frames}")
    t, layout = 0.0, []
    for kind, _, _, _, n, info in pieces:
        layout.append({"kind": kind, "out_start": round(t, 4), "dur": round(n / float(fps), 4), "frames": n, **info})
        t += n / float(fps)
    side = {"made": datetime.now().isoformat(timespec="seconds"), "tool": "splice.py", "main": str(args.main),
            "fps": float(fps), "pieces": layout, "total_dur": round(t, 4),
            "intro": next(({"dur": sum(p["dur"] for p in layout[:2] if p["kind"] in ("intro", "title_card"))}
                           for _ in [0]), None)}
    args.out.with_name(args.out.stem + ".assembly.json").write_text(json.dumps(side, indent=1), encoding="utf-8")
    for p in layout:
        print(f"  {p['out_start']:8.2f}s  {p['kind']:10} {p['dur']:6.2f}s  {p.get('file', '')}{p.get('main_from', '')}")
    print(f"-> {args.out}")


if __name__ == "__main__":
    sys.exit(main())
