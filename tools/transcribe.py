"""Transcribe a video/audio file with NVIDIA Parakeet and write word-level timestamps.

Usage:
    python transcribe.py <input> [<input> ...] [--out DIR] [--audio-track N]

Writes <name>.transcript.json (words + segments) and <name>.srt next to the
input, or into --out if given.
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import engines  # noqa: E402

MODEL_NAME = engines.chosen("speech")["repo"]          # Parakeet unless the user picked another built model in Settings
# Full attention runs out of memory on a 12 GB card somewhere past ~13 min, so
# longer files use local attention (supports up to ~3 hours per the model card).
LONG_AUDIO_SECONDS = 10 * 60


def extract_audio(src: Path, dst: Path, track: int) -> float:
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-i", str(src), "-map", f"0:a:{track}",
         "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(dst)],
        check=True,
    )
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(dst)],
        check=True, capture_output=True, text=True,
    )
    return float(out.stdout.strip())


def compute_type(device: str, vram_gb: float) -> str:
    """How faster-whisper holds the model: 8-bit weights on a card under 8 GB (large-v3 in float16 needs about 4 GB before it has read a word), 8-bit on the processor."""
    if device != "cuda":
        return "int8"
    return "float16" if vram_gb >= 8 else "int8_float16"


class Whisper:
    """The Whisper family (faster-whisper): runs on an Nvidia card or on the CPU, gives a time for every word. Same job as Parakeet for computers without Parakeet's requirements."""
    is_whisper = True

    def __init__(self, repo: str, device: str | None = None):
        try:                                                     # ctranslate2 finds the CUDA libraries that ship with torch
            import torch
            lib = Path(torch.__file__).parent / "lib"
            if lib.is_dir() and hasattr(os, "add_dll_directory"):
                os.add_dll_directory(str(lib))
        except ImportError:
            pass
        try:                                                     # a CPU build of torch has no CUDA libraries: use the pip ones (nvidia-cublas-cu12, nvidia-cudnn-cu12)
            import nvidia
            for d in Path(list(nvidia.__path__)[0]).glob("*/bin"):
                if hasattr(os, "add_dll_directory"):
                    os.add_dll_directory(str(d))
        except ImportError:
            pass
        from faster_whisper import WhisperModel
        import hardware
        gpus = hardware.gpus()
        device = device or ("cuda" if gpus else "cpu")
        self.repo, self.device = repo, device
        self.model = WhisperModel(repo, device=device, compute_type=compute_type(device, max((g["vram_gb"] for g in gpus), default=0)))

    def transcribe(self, wav: str, prompt: str = ""):
        import soundfile as sf                                   # the 16 kHz mono file we made: no need for faster-whisper's own decoder (it needs a newer `av`)
        audio, _ = sf.read(wav, dtype="float32")
        segs, _info = self.model.transcribe(audio, word_timestamps=True, vad_filter=False, condition_on_previous_text=False,
                                            initial_prompt=prompt or None)
        return words_from(segs)


def words_from(segs):
    """(words, segments, text) in the transcript format, from faster-whisper segments (words keep their punctuation, like Parakeet's)."""
    words, segments = [], []
    for s in segs:
        segments.append({"text": s.text.strip(), "start": round(s.start, 3), "end": round(s.end, 3)})
        for w in s.words or []:
            if not w.word.strip():
                continue
            if words and not w.word[:1].isspace() and w.word.strip()[:1] in "-'’" and words[-1]["end"] <= w.start + 0.05:
                words[-1]["word"] += w.word.strip()                    # "G" + "-code", "top" + "-down", "it" + "'s": one word, like Parakeet's
                words[-1]["end"] = round(w.end, 3)
                continue
            words.append({"word": w.word.strip(), "start": round(w.start, 3), "end": round(w.end, 3)})
    return words, segments, " ".join(s["text"] for s in segments)


def _parakeet_unavailable() -> str:
    """Why Parakeet cannot run here ('' when it can): no Nvidia card, or the NeMo packages are not installed."""
    import hardware
    if not hardware.gpus():
        return "there is no Nvidia graphics card"
    try:
        import nemo.collections.asr  # noqa: F401
    except ImportError:
        return "the speech packages are not installed (requirements-speech.txt)"
    return ""


def load_model():
    e = engines.chosen("speech")
    if e.get("runner") != "whisper":
        why = _parakeet_unavailable()
        if why:                                                  # Parakeet cannot run on this computer: use the Whisper family instead of failing
            import hardware
            e = engines.by_id("whisper-large-v3" if hardware.gpus() else "whisper-small")
            print(f"Parakeet is not available ({why}); reading with {e['name']} instead.", flush=True)
    if e.get("runner") == "whisper":
        return Whisper(e["repo"])
    import nemo.collections.asr as nemo_asr
    model = nemo_asr.models.ASRModel.from_pretrained(MODEL_NAME)
    return model.cuda().eval()


def srt_time(t: float) -> str:
    ms = int(round(t * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02}:{m:02}:{s:02},{ms:03}"


def write_srt(segments, path: Path):
    lines = []
    for i, seg in enumerate(segments, 1):
        lines += [str(i), f"{srt_time(seg['start'])} --> {srt_time(seg['end'])}", seg["text"], ""]
    path.write_text("\n".join(lines), encoding="utf-8")


def transcribe(model, src: Path, out_dir: Path, track: int):
    with tempfile.TemporaryDirectory() as tmp:
        wav = Path(tmp) / "audio.wav"
        duration = extract_audio(src, wav, track)
        if getattr(model, "is_whisper", False):
            words, segments, text = model.transcribe(str(wav))
        else:
            if duration > LONG_AUDIO_SECONDS:
                model.change_attention_model("rel_pos_local_attn", [256, 256])
                model.change_subsampling_conv_chunking_factor(1)
            elif model.cfg.encoder.self_attention_model != "rel_pos":
                model.change_attention_model("rel_pos")
            # Pass samples rather than a path: with a path NeMo writes a temp
            # manifest it never closes, which crashes cleanup on Windows.
            import soundfile as sf
            audio, _ = sf.read(str(wav), dtype="float32")
            result = model.transcribe([audio], timestamps=True, verbose=False)[0]
            text = result.text
            words = [{"word": w["word"], "start": round(w["start"], 3), "end": round(w["end"], 3)}
                     for w in result.timestamp["word"]]
            segments = [{"text": s["segment"], "start": round(s["start"], 3), "end": round(s["end"], 3)}
                        for s in result.timestamp["segment"]]

    out_dir.mkdir(parents=True, exist_ok=True)
    stem = src.stem
    data = {"source": str(src), "model": getattr(model, "repo", MODEL_NAME), "duration": round(duration, 3),
            "text": text, "segments": segments, "words": words}
    json_path = out_dir / f"{stem}.transcript.json"
    json_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    write_srt(segments, out_dir / f"{stem}.srt")
    return json_path, duration, len(words)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("inputs", nargs="+", type=Path)
    ap.add_argument("--out", type=Path, help="output folder (default: next to each input)")
    ap.add_argument("--audio-track", type=int, default=0, help="audio stream index (OBS multi-track)")
    args = ap.parse_args()

    model = load_model()
    for src in args.inputs:
        import time
        t0 = time.time()
        path, duration, n = transcribe(model, src, args.out or src.parent, args.audio_track)
        print(f"{src.name}: {duration/60:.1f} min audio, {n} words, "
              f"{time.time()-t0:.1f}s -> {path}", flush=True)


if __name__ == "__main__":
    sys.exit(main())
