"""Transcribe several clips with ONE model load (transcribe.py reloads the model per call and writes
<stem>.transcript.json, which collides for takes with the same file name in different folders).

Usage:
    python analyze_takes.py <manifest.json>
manifest = [{"src": "<video>", "out": "<transcript.json to write>"}, ...]
Prints one line per finished clip ("DONE <n>/<total> <src>").
"""
import json
import sys
import tempfile
import time
from pathlib import Path

import transcribe


def main():
    items = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    model = transcribe.load_model()
    for i, it in enumerate(items, 1):
        t0 = time.time()
        src, out = Path(it["src"]), Path(it["out"])
        with tempfile.TemporaryDirectory() as tmp:
            path, duration, n = transcribe.transcribe(model, src, Path(tmp), 0)
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        print(f"DONE {i}/{len(items)} {src.name}: {duration:.0f}s audio, {n} words, {time.time() - t0:.1f}s", flush=True)


if __name__ == "__main__":
    sys.exit(main())
