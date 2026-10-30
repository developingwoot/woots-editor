"""Face detection shared by the storyboard, lipsync.py and the self-review (OpenCV Haar, free, local).

The editor venv's OpenCV 5 ships WITHOUT the cascade files (cv2.data is empty), so the file lives in
_editor\\models\\haarcascade_frontalface_default.xml (downloaded once from github.com/opencv/opencv, 930 KB).

    from facedet import faces
    boxes = faces(bgr_or_gray_image)        # [(x, y, w, h), ...] in pixels, biggest first; [] if none
    available()                              # False when the model file is missing: callers must say "face check unavailable"
"""
import os
from pathlib import Path

HERE = Path(os.path.abspath(__file__)).parent
MODEL = HERE.parent / "models" / "haarcascade_frontalface_default.xml"
_cas = None


def cascade_path() -> str | None:
    """The cascade file: the editor's models folder first, then whatever OpenCV ships."""
    if MODEL.exists():
        return str(MODEL)
    try:
        import cv2
        p = Path(cv2.data.haarcascades) / "haarcascade_frontalface_default.xml"
        return str(p) if p.exists() else None
    except ImportError:
        return None


def load():
    """A cv2.CascadeClassifier, or None when the model file is missing."""
    global _cas
    if _cas is None:
        import cv2
        p = cascade_path()
        c = cv2.CascadeClassifier(p) if p else None
        _cas = c if c is not None and not c.empty() else False
    return _cas or None


def available() -> bool:
    return load() is not None


def faces(img, min_frac: float = 0.06) -> list[tuple[int, int, int, int]]:
    """Faces in an image, biggest first. min_frac = smallest face width as a share of the image width."""
    import cv2
    cas = load()
    if cas is None:
        return []
    g = img if img.ndim == 2 else cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    m = max(24, int(g.shape[1] * min_frac))
    found = cas.detectMultiScale(g, 1.1, 5, minSize=(m, m))
    return sorted((tuple(int(v) for v in f) for f in found), key=lambda f: -f[2] * f[3])
