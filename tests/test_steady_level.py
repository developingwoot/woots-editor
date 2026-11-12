"""The voice is never turned up and down along the video: the sound is brought to its loudness by one gain, and only the odd peak is limited."""
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures"))
import make_project  # noqa: E402
import audiomix  # noqa: E402
import finalrender  # noqa: E402
import sectionrender  # noqa: E402
import shortsaudio  # noqa: E402

needs_ffmpeg = pytest.mark.skipif(not make_project.have_ffmpeg(), reason="ffmpeg missing")


def rms_db(a):
    import numpy as np
    return 20 * np.log10(np.sqrt(np.mean(a.astype(float) ** 2)) + 1e-12)


@needs_ffmpeg
def test_a_quiet_stretch_stays_as_much_quieter_after_the_mix(tmp_path):
    import numpy as np
    import soundfile as sf
    t = np.arange(20 * audiomix.SR) / audiomix.SR
    tone = np.sin(2 * np.pi * 220 * t) * (1 + 0.5 * np.sin(2 * np.pi * 3 * t))               # a voice-ish wobble
    level = np.where(t < 10, 10 ** (-30 / 20), 10 ** (-18 / 20))                               # 12 dB louder in the second half
    voice = np.stack([tone * level] * 2, axis=1).astype(np.float32)
    sf.write(str(tmp_path / "v.wav"), voice, audiomix.SR)
    video = tmp_path / "cut.mp4"
    subprocess.run([sectionrender.FFMPEG, "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=black:s=64x36:r=30:d=20", "-i", str(tmp_path / "v.wav"),
                    "-c:v", "libx264", "-c:a", "aac", "-shortest", str(video)], check=True)
    shortsaudio.mix_into(video, {"beds": [], "sfx": []}, {"duck_db": 9, "music_below_speech_db": 26})
    r = subprocess.run([sectionrender.FFMPEG, "-v", "error", "-i", str(video), "-vn", "-ac", "1", "-ar", "48000", "-f", "f32le", "-"], capture_output=True)
    out = np.frombuffer(r.stdout, np.float32)
    a, b = out[2 * 48000:8 * 48000], out[12 * 48000:18 * 48000]
    assert abs((rms_db(b) - rms_db(a)) - 12.0) < 1.0                                         # one-pass loudnorm squeezed this to a few dB


def test_the_preview_and_the_final_use_one_gain():
    af = finalrender.steady_gain({"input_i": "-24.0"})
    assert af == "volume=10.00dB,alimiter=limit=0.89:level=disabled" and "loudnorm" not in af
    assert finalrender.steady_gain({"input_i": "-70"}).startswith("volume=20.00dB")          # never more than 20 dB
