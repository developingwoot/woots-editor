"""Sam 2026-10-29: the rough cut's voice and lips were off. Every piece used to be encoded to AAC alone (a few ms of padding each) and the pieces joined by stream copy."""
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures"))
import make_project  # noqa: E402
import sectionrender  # noqa: E402


def _seconds(path, stream):
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", stream, "-show_entries", "stream=duration", "-of", "csv=p=0", str(path)], capture_output=True, text=True)
    return float(r.stdout.strip())


def test_sound_and_picture_end_together_after_many_short_pieces(tmp_path):
    src = tmp_path / "talk.mp4"
    make_project.make_clip(src, 12, 440)
    segs = [{"id": f"P{i:02d}", "src": str(src), "in": 0.1 + i * 0.37, "out": 0.1 + i * 0.37 + 0.31 + (i % 3) * 0.013} for i in range(24)]
    edit = tmp_path / "e.json"
    edit.write_text(json.dumps({"size": [320, 180], "fps": 30, "snap": False, "level": False, "segments": segs}), encoding="utf-8")
    info = sectionrender.render(edit, tmp_path / "out", "cut.mp4")
    out = Path(info["file"])
    assert abs(_seconds(out, "a:0") - _seconds(out, "v:0")) < 0.05      # 24 pieces: the old way was 0.1-0.5 s apart
