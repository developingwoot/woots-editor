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


def test_a_long_sound_effect_stops_where_its_piece_ends(tmp_path):
    """The host: the whoosh of the web page played over and over after the page was gone. Its file is 22 s long; the preview cut it at the end of the piece, the final did not."""
    import numpy as np
    import soundfile as sf
    import audiomix
    sr = audiomix.SR
    sf.write(str(tmp_path / "long.wav"), (np.random.RandomState(1).randn(22 * sr, 2) * 0.2).astype(np.float32), sr)
    t = np.arange(30 * sr) / sr
    speech = np.stack([np.sin(2 * np.pi * 200 * t) * 0.1] * 2, axis=1).astype(np.float32)
    plan = {"beds": [], "sfx": [{"file": str(tmp_path / "long.wav"), "t": 5.0, "max": 2.0}]}
    out, _ = audiomix.mix(speech, plan, {"duck_db": 9, "music_below_speech_db": 26}, tmp_path)
    extra = np.abs(out - speech).max(axis=1)
    assert extra[int(5.5 * sr):int(6.9 * sr)].max() > 0.01          # it plays for its piece
    assert extra[int(7.1 * sr):].max() < 1e-4                       # and then not at all
