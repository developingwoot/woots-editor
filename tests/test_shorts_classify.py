import numpy as np

import facedet
import mpfaces
import shorts


def test_a_frame_with_a_speaker_is_never_a_card_whatever_colour_its_corners_are(monkeypatch):
    frame = np.zeros((720, 1280, 3), dtype="uint8")
    monkeypatch.setattr(mpfaces, "available", lambda: True)
    monkeypatch.setattr(mpfaces, "faces", lambda fr: [(0.5, 0.3, 0.2, 0.9)])
    assert shorts.has_big_face(frame, 1280)
    monkeypatch.setattr(mpfaces, "faces", lambda fr: [(0.5, 0.3, 0.05, 0.9)])                       # a small face on a prop is not the speaker
    assert not shorts.has_big_face(frame, 1280)
    monkeypatch.setattr(mpfaces, "available", lambda: False)
    monkeypatch.setattr(facedet, "faces", lambda fr, s: [(100, 100, 200, 200)])
    assert shorts.has_big_face(frame, 1280)
    monkeypatch.setattr(facedet, "faces", lambda fr, s: [])
    assert not shorts.has_big_face(frame, 1280)
