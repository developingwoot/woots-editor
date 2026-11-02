"""Mixing audio: the shared recipe of the main video's final render and of shorts.

  mix(speech, plan, st, cache) -> (speech + music + SFX, the speech's loudness)
      plan = {"beds": [{"file", "start", "end"}], "sfx": [{"file", "t"}]} in seconds on the output timeline;
      st = {"duck_db", "music_below_speech_db"}: each bed sits `music_below_speech_db` LU under the speech, a further `duck_db` down while the host talks (fast attack, slow
      release), beds cross-fade over 1.5 s and loop when the track is shorter than its stretch; SFX are scaled to the speech peak (-12 dB).
Arrays are float32 stereo at SR (48 kHz). Needs numpy, soundfile, pyloudnorm (the app's venv).
"""
import hashlib
import subprocess
from pathlib import Path

SR = 48000
AUDIO_EXT = {".mp3", ".wav", ".ogg", ".flac", ".m4a", ".aac"}


def _np():
    import numpy as np
    import soundfile as sf
    return np, sf


def ff(*a):
    import sectionrender
    return subprocess.run([sectionrender.FFMPEG, "-nostdin", "-y", "-v", "error", *map(str, a)], capture_output=True, text=True)


def decode(path: Path, cache: Path):
    np, sf = _np()
    key = hashlib.sha1(f"{path}|{path.stat().st_size}|{int(path.stat().st_mtime)}".encode()).hexdigest()[:12]
    wav = cache / f"dec_{key}.wav"
    if not wav.exists():
        r = ff("-i", path, "-ac", 2, "-ar", SR, "-c:a", "pcm_f32le", wav)
        if r.returncode != 0:
            raise RuntimeError(f"could not decode {path.name}: {r.stderr.strip()[-200:]}")
    a, _ = sf.read(str(wav), dtype="float32", always_2d=True)
    return a


def mix(speech, plan: dict, st: dict, cache: Path):
    """Music beds (-26 LU under the speech, ducked 9 dB while the host talks, crossfaded) + SFX. The recipe is render.mix_audio's."""
    import pyloudnorm as pyln
    np, _ = _np()
    n = len(speech)
    meter = pyln.Meter(SR)
    speech_lufs = meter.integrated_loudness(speech)
    hop = SR // 100
    mono = speech.mean(axis=1)
    rms = np.sqrt(np.convolve((mono[: n // hop * hop].reshape(-1, hop) ** 2).mean(1), np.ones(5) / 5, "same"))
    db = 20 * np.log10(rms + 1e-9)
    active = db > np.percentile(db, 90) - 25
    duck_db = float(st["duck_db"])
    duck = np.zeros(len(active), np.float32)
    g = 0.0
    for i, on in enumerate(active):
        target = -duck_db if on else 0.0
        g += (target - g) * (0.35 if target < g else 0.03)           # attack ~30 ms, release ~350 ms
        duck[i] = g
    duck = np.repeat(10 ** (duck / 20), hop)
    duck = np.pad(duck, (0, max(0, n - len(duck))), constant_values=1.0)[:n, None]
    music = np.zeros_like(speech)
    xf = int(1.5 * SR)
    beds = plan["beds"]
    for k, bed in enumerate(beds):
        a, b = int(bed["start"] * SR), min(n, int(bed["end"] * SR))
        if k > 0 and bed["start"] - beds[k - 1]["end"] < 1.5:
            a = max(0, a - xf // 2)
        if k < len(beds) - 1 and beds[k + 1]["start"] - bed["end"] < 1.5:
            b = min(n, b + xf // 2)
        if b - a < SR:
            continue
        track = decode(Path(bed["file"]), cache)
        loud = meter.integrated_loudness(track[: min(len(track), 60 * SR)])
        track = track * 10 ** ((speech_lufs - float(st["music_below_speech_db"]) - loud) / 20)
        need = b - a
        out = track[:need].copy()
        while len(out) < need:                                        # short track: loop with a crossfade
            nxt = track[: need - len(out) + xf]
            ramp = np.linspace(0, 1, min(xf, len(nxt), len(out)), dtype=np.float32)[:, None]
            m_ = len(ramp)
            out[-m_:] = out[-m_:] * (1 - ramp) + nxt[:m_] * ramp
            out = np.concatenate([out, nxt[m_:]])
        out = out[:need]
        fin = np.linspace(0, 1, min(xf, need), dtype=np.float32)[:, None]
        out[: len(fin)] *= fin
        out[-len(fin):] *= fin[::-1]
        music[a:b] += out
    music *= duck
    sfx = np.zeros_like(speech)
    speech_peak = np.percentile(np.abs(speech), 99.9)
    for s in plan["sfx"]:
        clip = decode(Path(s["file"]), cache)
        peak = np.abs(clip).max() or 1.0
        clip = clip * (speech_peak / peak) * 10 ** (-12 / 20)          # -4 dB under the speech peak was too loud (the creator, 2026-10-25)
        a = int(s["t"] * SR)
        e = min(n, a + len(clip))
        if a < n:
            sfx[a:e] += clip[: e - a]
    return speech + music + sfx, speech_lufs
