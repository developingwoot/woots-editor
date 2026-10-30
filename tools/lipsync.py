"""Estimate audio/video lip-sync offset of a talking-head recording (OpenCV + numpy only).

Usage:
    python lipsync.py <video> <start_s> <dur_s>

Method: find the face (OpenCV Haar), take the lower-face band (jaw/mouth), measure its vertical
optical-flow magnitude at the source frame rate, band-pass both it and the voice's loudness envelope to
the syllable range (2-10 Hz), and cross-correlate within +-0.4 s. Positive lag = the picture moves AFTER
the sound (audio EARLY / video LATE). A single window is noisy (+-100 ms); use several 15-20 s windows
and trust the median only when they agree. The delivered render's own offset vs its source should be
checked separately (exact picture/audio match), because this measures the RECORDING.
"""
import argparse
import subprocess
import sys

import cv2
import numpy as np


def bandpass(x, fps, lo=2.0, hi=10.0):
    f = np.fft.rfft(x - x.mean())
    fr = np.fft.rfftfreq(len(x), 1 / fps)
    f[(fr < lo) | (fr > hi)] = 0
    return np.fft.irfft(f, len(x))


def measure(video, start, dur):
    info = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=r_frame_rate",
                           "-of", "csv=p=0", video], capture_output=True, text=True).stdout.split()[0]
    n_, d_ = info.split("/")
    fps = float(n_) / float(d_)
    W, H = 480, 270
    raw = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-ss", str(start), "-t", str(dur), "-i", video,
                          "-vf", f"scale={W}:{H},format=gray", "-f", "rawvideo", "-"], capture_output=True).stdout
    v = np.frombuffer(raw, np.uint8).reshape(-1, H, W)
    import os
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import facedet                       # OpenCV 5 ships no cascade files: facedet finds _editor\models\...xml
    cas = facedet.load()
    if cas is None:
        raise SystemExit("lipsync: no face model (expected models\\haarcascade_frontalface_default.xml in the editor folder)")
    boxes = []
    for i in range(0, len(v), max(1, int(fps // 4))):
        f = cas.detectMultiScale(v[i], 1.1, 5, minSize=(60, 60))
        if len(f):
            boxes.append(max(f, key=lambda b: b[2] * b[3]))
    if len(boxes) < 5:
        return None
    x, y, w, h = np.median(np.array(boxes), axis=0).astype(int)
    y0, y1 = y + int(h * 0.55), min(H, y + int(h * 1.05))                       # mouth + jaw band
    x0, x1 = x + int(w * 0.15), x + int(w * 0.85)
    mot = []
    prev = v[0][y0:y1, x0:x1]
    for i in range(1, len(v)):
        cur = v[i][y0:y1, x0:x1]
        fl = cv2.calcOpticalFlowFarneback(prev, cur, None, 0.5, 2, 15, 2, 5, 1.1, 0)
        mot.append(np.mean(np.abs(fl[..., 1])))                                   # vertical motion (jaw)
        prev = cur
    mot = np.array(mot)
    ar = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-ss", str(start), "-t", str(dur), "-i", video,
                         "-vn", "-ac", "1", "-ar", "16000", "-f", "f32le", "-"], capture_output=True).stdout
    a = np.frombuffer(ar, np.float32)
    n = min(len(mot), int(len(a) / 16000 * fps))
    env = np.array([np.sqrt(np.mean(a[int(i * 16000 / fps):int((i + 1) * 16000 / fps)] ** 2)) for i in range(n)])
    env = np.log10(env + 1e-5)
    m, e = bandpass(mot[:n], fps), bandpass(env, fps)
    m, e = m / (m.std() + 1e-9), e / (e.std() + 1e-9)
    K = int(0.4 * fps)
    cc = []
    for lag in range(-K, K + 1):
        xx, yy = (e[: n - lag], m[lag:]) if lag >= 0 else (e[-lag:], m[: n + lag])
        cc.append(float(np.mean(xx * yy)))
    cc = np.array(cc)
    i = int(np.argmax(cc))
    frac = 0.0
    if 0 < i < len(cc) - 1:
        d = cc[i - 1] - 2 * cc[i] + cc[i + 1]
        frac = 0.5 * (cc[i - 1] - cc[i + 1]) / d if d else 0.0
    return 1000 * (i - K + frac) / fps, float(cc[i]), fps


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("video"); ap.add_argument("start", type=float); ap.add_argument("dur", type=float)
    a = ap.parse_args()
    r = measure(a.video, a.start, a.dur)
    print("no face found" if r is None else f"{a.video.split('/')[-1][:34]:34} {a.start:6.1f}s +{a.dur:.0f}s lag {r[0]:+6.0f} ms (corr {r[1]:.2f}, {r[2]:.0f} fps)")


if __name__ == "__main__":
    sys.exit(main())
