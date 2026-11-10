"""Transcribe several clips with ONE model load (transcribe.py reloads the model per call and writes
<stem>.transcript.json, which collides for takes with the same file name in different folders).

Usage:
    python analyze_takes.py <manifest.json>
manifest = [{"src": "<video>", "out": "<transcript.json to write>"}, ...]
Prints one line per finished clip ("DONE <n>/<total> <src>").
"""
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import transcribe


def probe(src: Path, entries: str, stream: str = "") -> str:
    cmd = ["ffprobe", "-v", "error", *(["-select_streams", stream] if stream else []), "-show_entries", entries, "-of", "default=nw=1:nk=1", str(src)]
    return subprocess.run(cmd, capture_output=True, text=True).stdout.strip()


def silent_transcript(src: Path):
    """A transcript with no words for a clip that has no sound track at all (screen captures, camera clips, b-roll), or None when it has sound."""
    if probe(src, "stream=codec_type", "a:0"):
        return None
    try:
        duration = float(probe(src, "format=duration"))
    except ValueError:
        duration = 0.0
    return {"duration": duration, "text": "", "words": [], "segments": []}


def main():
    items = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    model = transcribe.load_model()
    for i, it in enumerate(items, 1):
        t0 = time.time()
        src, out = Path(it["src"]), Path(it["out"])
        data = silent_transcript(src)
        if data is not None:                                     # nothing to read: one bad clip must not stop the rest
            duration, n = data["duration"], 0
        else:
            with tempfile.TemporaryDirectory() as tmp:
                path, duration, n = transcribe.transcribe(model, src, Path(tmp), 0)
                data = json.loads(Path(path).read_text(encoding="utf-8"))
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        print(f"DONE {i}/{len(items)} {src.name}: {duration:.0f}s audio, {n} words, {time.time() - t0:.1f}s", flush=True)


if __name__ == "__main__":
    sys.exit(main())
