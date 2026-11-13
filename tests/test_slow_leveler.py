"""The host's voice drifts 6-10 dB over tens of seconds (leans in, speaks softer). A slow, speech-only curve evens that out; it never works inside a sentence."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures"))
import make_project  # noqa: E402
import loudness  # noqa: E402
import sectionrender  # noqa: E402

needs_ffmpeg = pytest.mark.skipif(not make_project.have_ffmpeg(), reason="ffmpeg missing")
SR = 16000


def voice(seconds, level_db_at):
    """A talking-like tone (a pause every 3 s) whose level follows level_db_at(t)."""
    import numpy as np
    t = np.arange(int(seconds * SR)) / SR
    x = np.sin(2 * np.pi * 200 * t) * (np.sin(2 * np.pi * 0.33 * t) > -0.6)
    lvl = np.array([level_db_at(v) for v in t[::SR // 10]])
    g = 10 ** (np.interp(t, t[::SR // 10], lvl) / 20)
    return (x * g).astype(np.float32)


def rms_db(a):
    import numpy as np
    return 20 * np.log10(np.sqrt(np.mean(a.astype(float) ** 2)) + 1e-12)


def test_a_voice_that_fades_by_12_db_over_a_minute_is_brought_back_level():
    x = voice(60, lambda t: -20 - 12 * t / 60)
    dev = loudness.deviation(x, SR)
    fixed = loudness.apply_curve(x[:, None], SR, dev)[:, 0]
    a, b = rms_db(fixed[5 * SR:15 * SR]), rms_db(fixed[45 * SR:55 * SR])
    assert abs(a - b) < 3.5                                              # was about 9 dB apart
    assert max(abs(v) for v in dev) <= loudness.MAX_DEV_DB


def test_a_steady_voice_is_left_alone_and_silence_has_no_curve():
    import numpy as np
    x = voice(40, lambda t: -22)
    assert max(abs(v) for v in loudness.deviation(x, SR)) < 2.0                 # the ends of the recording only
    assert set(loudness.deviation(np.zeros(SR * 20, np.float32), SR)) == {0.0}
    assert loudness.deviation(np.zeros(100, np.float32), SR) == [0.0]


def test_the_curve_does_not_move_inside_a_sentence():
    x = voice(60, lambda t: -20 - 12 * t / 60)
    dev = loudness.deviation(x, SR)
    assert max(abs(a - b) for a, b in zip(dev, dev[1:])) < 0.6           # per half second


@needs_ffmpeg
def test_the_gain_glides_over_a_piece_from_its_start_to_its_end(tmp_path):
    import numpy as np
    src = tmp_path / "talk.mp4"
    make_project.make_clip(src, 8, 440)
    seg = {"id": "P01", "src": str(src), "in": 0.0, "out": 6.0, "gain_db": -6.0, "gain_to_db": 6.0}
    glide = tmp_path / "g.json"
    glide.write_text(json.dumps({"size": [320, 180], "fps": 30, "snap": False, "level": False, "segments": [seg]}), encoding="utf-8")
    flat = tmp_path / "f.json"
    flat.write_text(json.dumps({"size": [320, 180], "fps": 30, "snap": False, "level": False, "segments": [{"id": "P01", "src": str(src), "in": 0.0, "out": 6.0}]}), encoding="utf-8")

    def levels(p, out):
        info = sectionrender.render(p, tmp_path / out, "cut.mp4")
        r = subprocess.run([sectionrender.FFMPEG, "-v", "error", "-i", info["file"], "-vn", "-ac", "1", "-ar", "16000", "-f", "f32le", "-"], capture_output=True)
        y = np.frombuffer(r.stdout, np.float32)
        return rms_db(y[int(0.5 * SR):int(1.5 * SR)]), rms_db(y[int(4.5 * SR):int(5.5 * SR)])
    f0, f1 = levels(flat, "flat")
    g0, g1 = levels(glide, "glide")
    assert 5.0 < (g1 - g0) - (f1 - f0) < 11.0                            # t=1 to t=5 of 6 s: the gain goes from -4 to +4 dB, 8 dB
