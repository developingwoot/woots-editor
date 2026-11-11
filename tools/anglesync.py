"""Line up two recordings of the same moment (two cameras) by their sound, so the picture of one can play over the sound of the other.

  offset(a, a_start, a_dur, b) -> (delta, score)   a moment t of recording a is at t + delta in recording b; score 0..1 says how sure (below MIN_SCORE: not lined up)

How: the loudness envelope of each sound (200 values a second) is compared at every shift (FFT cross-correlation); the best shift wins.
Speech has an uneven rhythm, so the envelopes of two microphones in the same room match at one shift only. Needs ffmpeg and numpy.
"""
import subprocess

import numpy as np

RATE = 8000                   # Hz: enough for the rhythm of speech
HOP = 40                      # samples per envelope value: 200 values a second (5 ms)
MAX_A_S = 30.0                # seconds of recording a that are compared (the beat's own words)
MIN_SCORE = 0.3


def pcm(path, start: float = 0.0, dur: float | None = None) -> np.ndarray:
    cmd = ["ffmpeg", "-v", "error", "-nostdin", *(["-ss", f"{start:.3f}"] if start > 0 else []), *(["-t", f"{dur:.3f}"] if dur else []),
           "-i", str(path), "-vn", "-ac", "1", "-ar", str(RATE), "-f", "s16le", "-"]
    r = subprocess.run(cmd, capture_output=True)
    if r.returncode != 0:
        raise ValueError(f"could not read the sound of {path}")
    return np.frombuffer(r.stdout, dtype=np.int16).astype(np.float32)


def envelope(x: np.ndarray) -> np.ndarray:
    """Loudness every 5 ms, on a log scale, with its slow drift taken out (so a louder microphone does not matter)."""
    n = len(x) // HOP
    if n < 4:
        return np.zeros(0, dtype=np.float32)
    e = np.log1p(np.sqrt((x[:n * HOP].reshape(n, HOP) ** 2).mean(axis=1)))
    k = 40                                                       # 0.2 s running mean
    slow = np.convolve(e, np.ones(k) / k, mode="same")
    d = e - slow
    return ((d - d.mean()) / (d.std() + 1e-9)).astype(np.float32)


def best_shift(a: np.ndarray, b: np.ndarray) -> tuple[int, float]:
    """(shift, score): a lines up with b[shift:shift+len(a)]."""
    if len(a) == 0 or len(b) < len(a):
        return 0, 0.0
    size = 1 << int(np.ceil(np.log2(len(a) + len(b))))
    corr = np.fft.irfft(np.fft.rfft(b, size) * np.conj(np.fft.rfft(a, size)), size)[: len(b) - len(a) + 1]
    i = int(np.argmax(corr))
    seg = b[i:i + len(a)]
    score = float(np.dot(a, seg) / (np.linalg.norm(a) * np.linalg.norm(seg) + 1e-9))
    return i, score


def duration(path) -> float:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)], capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except ValueError:
        raise ValueError(f"could not read {path}") from None


def locate(clip, rec, lo: float, hi: float) -> tuple[float, float]:
    """Where recording `clip` starts in recording `rec`, searching rec between lo and hi seconds: (seconds into rec, score).
    The shorter of the two is looked for in the other, at most MAX_A_S of it."""
    lo = max(0.0, lo)
    cd = duration(clip)
    if cd <= hi - lo:
        i, score = best_shift(envelope(pcm(clip, 0, min(cd, MAX_A_S))), envelope(pcm(rec, lo, hi - lo)))
        return round(lo + i * HOP / RATE, 3), round(score, 3)
    i, score = best_shift(envelope(pcm(rec, lo, min(hi - lo, MAX_A_S))), envelope(pcm(clip)))
    return round(lo - i * HOP / RATE, 3), round(score, 3)


def offset(a, a_start: float, a_dur: float, b) -> tuple[float, float]:
    """Where the stretch [a_start, a_start + a_dur] of recording a is in recording b: (delta, score), b time = a time + delta."""
    ea = envelope(pcm(a, a_start, min(a_dur, MAX_A_S)))
    eb = envelope(pcm(b))
    i, score = best_shift(ea, eb)
    return round(i * HOP / RATE - a_start, 3), round(score, 3)
