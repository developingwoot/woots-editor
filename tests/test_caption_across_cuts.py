"""A caption or graphic that runs across jump cuts stays on screen through them (the host: the micro SD caption cut in and out at every cut)."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures"))
import make_project  # noqa: E402
import sectionrender  # noqa: E402
import sections  # noqa: E402

needs_ffmpeg = pytest.mark.skipif(not make_project.have_ffmpeg(), reason="ffmpeg missing")


def test_pieces_of_a_caption_say_which_one_goes_on_into_the_next():
    b = {"id": "B07", "aroll": {"keep": [[10, 11.5], [12, 13.2], [14, 16.1]]}}
    ps = sections._spread_overlay(b, "x.png", 0.2, 4.0)
    assert [(p["cont"], p["more"]) for p in ps] == [(False, True), (True, True), (True, False)]


def test_a_piece_that_goes_on_fills_to_the_cut_and_one_that_came_from_before_starts_at_the_cut():
    o = sectionrender.fill_cut({"at": 0.0, "dur": 1.18, "cont": True, "more": True}, 1.3)
    assert o["at"] == 0.0 and 1.3 <= o["dur"] <= 1.45
    o = sectionrender.fill_cut({"at": 0.12, "dur": 1.0, "cont": True, "more": False}, 1.5)
    assert (o["at"], o["dur"]) == (0.0, 1.12)                       # the last piece still ends where the caption ends
    o = sectionrender.fill_cut({"at": 0.2, "dur": 0.5, "cont": False, "more": True}, 3.0)
    assert o["dur"] == 0.5                                           # a long way from the cut: left as it is


@needs_ffmpeg
def test_a_caption_over_three_pieces_is_on_every_frame_of_them(tmp_path):
    import numpy as np
    src = tmp_path / "talk.mp4"
    make_project.make_clip(src, 12, 440)
    png = tmp_path / "card.png"
    subprocess.run([sectionrender.FFMPEG, "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=0xff00ff:s=320x180", "-frames:v", "1", str(png)], check=True)
    keep = [(1.0, 2.5), (4.0, 5.2), (7.0, 8.9)]
    b = {"id": "B07", "aroll": {"keep": [list(k) for k in keep]}}
    segs = [{"id": "B07" if i == 0 else f"B07.{i + 1}", "src": str(src), "in": k0 + 0.037 * i, "out": k1 + 0.041, "zoom": 1.0} for i, (k0, k1) in enumerate(keep)]
    ov = [{**p, "still": True, "card": True} for p in sections._spread_overlay(b, str(png), 0.0, 4.2)]
    ov[0]["fade_in"], ov[-1]["fade_out"] = False, False
    edit = tmp_path / "e.json"
    edit.write_text(json.dumps({"size": [320, 180], "fps": 30, "snap": False, "level": False, "segments": segs, "overlays": ov}), encoding="utf-8")
    info = sectionrender.render(edit, tmp_path / "out", "cut.mp4")
    r = subprocess.run([sectionrender.FFMPEG, "-v", "error", "-i", info["file"], "-vf", "scale=32:18", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True)
    frames = np.frombuffer(r.stdout, np.uint8).reshape(-1, 18, 32, 3).astype(int)
    magenta = [(f[..., 0].mean() > 200 and f[..., 1].mean() < 60) for f in frames]
    last = max(i for i, m in enumerate(magenta) if m)
    assert last > 100 and all(magenta[:last - 2])


@needs_ffmpeg
def test_a_blur_over_three_pieces_covers_every_frame_of_them(tmp_path):
    """The preview and the final showed the unblurred picture for a frame at the cuts. A black box over the whole picture makes any missed frame easy to see."""
    import numpy as np
    import blur
    src = tmp_path / "talk.mp4"
    make_project.make_clip(src, 12, 440)
    keep = [(1.0, 2.5), (4.0, 5.2), (7.0, 8.9)]
    b = {"id": "B07", "aroll": {"keep": [list(k) for k in keep]},
         "on_screen": {"blur": [{"id": "bl1", "at": 0.2, "dur": 4.0, "style": "block", "what": "x", "track": [[0.0, 0.0, 0.0, 1.0, 1.0], [4.0, 0.0, 0.0, 1.0, 1.0]]}]}}
    segs = [{"id": "B07" if i == 0 else f"B07.{i + 1}", "src": str(src), "in": k0 + 0.037 * i, "out": k1 + 0.041, "zoom": 1.0} for i, (k0, k1) in enumerate(keep)]
    rows = blur.edit_rows(b, sections._pieces(b))
    assert [(r["cont"], r["more"]) for r in rows] == [(False, True), (True, True), (True, False)]
    edit = tmp_path / "e.json"
    edit.write_text(json.dumps({"size": [320, 180], "fps": 30, "snap": False, "level": False, "segments": segs, "blurs": rows}), encoding="utf-8")
    info = sectionrender.render(edit, tmp_path / "out", "cut.mp4")
    r = subprocess.run([sectionrender.FFMPEG, "-v", "error", "-i", info["file"], "-vf", "scale=32:18", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True)
    frames = np.frombuffer(r.stdout, np.uint8).reshape(-1, 18, 32, 3).astype(int)
    black = [f.mean() < 12 for f in frames]
    first = black.index(True)
    last = max(i for i, m in enumerate(black) if m)
    assert last - first > 90 and all(black[first:last - 2])
