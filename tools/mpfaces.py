"""Face finder for the shorts (and anything else that needs to know where people are): MediaPipe BlazeFace, free and local.

    from mpfaces import faces, available
    faces(bgr_frame)   # [(cx, cy, width, score), ...] as fractions of the frame, best first; [] when none or the model is missing

The model file lives in _editor/models/blaze_face_short_range.tflite (229 KB, from Google's MediaPipe model storage; the host approved the download 2026-10-23).
A wide 1920x1080 shot has faces only ~3.5 to 4.5 % of the frame wide, too small for one pass, so the frame is searched in three overlapping 1080-wide squares
and duplicates are merged. Beards lower the score (the host ~0.5 to 0.7, the co-host ~0.9): the threshold is 0.4.
"""
import os
from pathlib import Path

MODEL = Path(os.path.abspath(__file__)).parent.parent / "models" / "blaze_face_short_range.tflite"
_det = None


def available() -> bool:
    return MODEL.exists()


def _detector():
    global _det
    if _det is None:
        from mediapipe.tasks import python as mpt
        from mediapipe.tasks.python import vision
        _det = vision.FaceDetector.create_from_options(vision.FaceDetectorOptions(
            base_options=mpt.BaseOptions(model_asset_path=str(MODEL)), min_detection_confidence=0.4))
    return _det


def faces(frame, min_score: float = 0.4):
    if not available():
        return []
    import cv2
    import mediapipe as mp
    det = _detector()
    h, w = frame.shape[:2]
    side = min(h, w)
    xs = [0] if w <= side else sorted({int(round(i * (w - side) / 2)) for i in range(3)})
    out = []
    for x0 in xs:
        tile = cv2.cvtColor(frame[:, x0:x0 + side], cv2.COLOR_BGR2RGB)
        for d in det.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=tile)).detections:
            b, s = d.bounding_box, d.categories[0].score
            if s >= min_score:
                out.append(((x0 + b.origin_x + b.width / 2) / w, (b.origin_y + b.height / 2) / h, b.width / w, float(s)))
    out.sort(key=lambda f: -f[3])
    keep = []
    for f in out:
        if all(abs(f[0] - k[0]) > 0.03 or abs(f[1] - k[1]) > 0.05 for k in keep):
            keep.append(f)
    return keep
