"""The host: the song was added at the start of the final but not throughout. A trimmed beat plays as several pieces (B07, B07.2, ...): only the first one found the beat's music, so the bed stopped after it."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import finalrender  # noqa: E402
import selfreview  # noqa: E402


def test_a_music_bed_runs_over_every_piece_of_a_trimmed_beat(monkeypatch):
    segs = [{"id": "B01", "start": 0.0, "dur": 4.0}, {"id": "B01.2", "start": 4.0, "dur": 3.0}, {"id": "B01.3", "start": 7.0, "dur": 2.0},
            {"id": "B03", "start": 9.0, "dur": 5.0}, {"id": "B04", "start": 14.0, "dur": 5.0}]
    beats = {"beats": [{"id": "B01", "audio": {"music": "Song A"}}, {"id": "B03", "audio": {"music": "Song A"}}, {"id": "B04", "audio": {}}]}
    monkeypatch.setattr(selfreview, "timeline", lambda w, n: {"segments": segs, "overlays": [], "broll": [], "stitch": {"dur": 19.0}})
    monkeypatch.setattr(finalrender, "read_json", lambda p, d=None: beats)
    monkeypatch.setattr(finalrender, "resolve_music", lambda name: (Path("song.mp3"), ""))
    monkeypatch.setattr(finalrender, "transition_sounds", lambda b, kit=None: [])
    plan = finalrender.audio_plan("w", "n")
    assert [(b["start"], b["end"]) for b in plan["beds"]] == [(0.0, 14.0)]       # all four pieces, not just the first
