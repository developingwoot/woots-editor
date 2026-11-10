import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import analyze_takes  # noqa: E402

needs_ffmpeg = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not installed")


@needs_ffmpeg
def test_a_clip_without_a_sound_track_gets_an_empty_transcript_instead_of_stopping_the_run(tmp_path):
    silent, loud = tmp_path / "ipcam.mp4", tmp_path / "talk.mp4"
    base = ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=blue:size=320x240:rate=10:duration=3"]
    assert subprocess.run(base + ["-pix_fmt", "yuv420p", str(silent)]).returncode == 0
    assert subprocess.run(base + ["-f", "lavfi", "-i", "sine=frequency=300:duration=3", "-shortest", "-pix_fmt", "yuv420p", str(loud)]).returncode == 0
    t = analyze_takes.silent_transcript(silent)
    assert t["words"] == [] and t["segments"] == [] and 2.5 < t["duration"] < 3.5
    assert analyze_takes.silent_transcript(loud) is None                         # this one is read as usual
