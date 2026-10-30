"""Label who is speaking in each transcript segment (for editing decisions, never shown on screen).

Usage:
    python speakers.py <transcript.json> --ref "The host=<solo clip of the host>" [--names the host,the co-host]

Embeds every transcript segment with NVIDIA TitaNet (speaker verification), splits them
into len(--names) voices, and names the voice closest to the reference clip after it.
Writes <name>.speakers.json: [{start, end, speaker, score, text}] and prints a summary.
"""
import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
import soundfile as sf

MODEL = "nvidia/speakerverification_en_titanet_large"
SR = 16000
MIN_SEG = 0.8  # shorter segments ("Yeah.") get a padded window for a usable voiceprint


def load_audio(src: Path, seconds: float | None = None) -> np.ndarray:
    with tempfile.TemporaryDirectory() as tmp:
        wav = Path(tmp) / "a.wav"
        cmd = ["ffmpeg", "-y", "-v", "error", "-i", str(src)]
        if seconds:
            cmd += ["-t", str(seconds)]
        subprocess.run(cmd + ["-map", "0:a:0", "-ac", "1", "-ar", str(SR), str(wav)], check=True)
        audio, _ = sf.read(str(wav), dtype="float32")
    return audio


def embed(model, audio: np.ndarray) -> np.ndarray:
    import torch
    with torch.no_grad():
        sig = torch.tensor(audio, device=model.device).unsqueeze(0)
        length = torch.tensor([sig.shape[1]], device=model.device)
        _, emb = model.forward(input_signal=sig, input_signal_length=length)
    e = emb.squeeze(0).cpu().numpy()
    return e / np.linalg.norm(e)


def kmeans_cos(x: np.ndarray, k: int, iters: int = 50) -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(0)
    cent = x[rng.choice(len(x), k, replace=False)]
    for _ in range(iters):
        lab = (x @ cent.T).argmax(1)
        new = np.stack([x[lab == j].mean(0) if (lab == j).any() else cent[j] for j in range(k)])
        new /= np.linalg.norm(new, axis=1, keepdims=True)
        if np.allclose(new, cent):
            break
        cent = new
    return lab, cent


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("transcript", type=Path)
    ap.add_argument("--ref", required=True, help='"Name=path" to a clip where only that person talks')
    ap.add_argument("--names", default=None, help="everyone (default: the channel profile) who talks, comma separated")
    ap.add_argument("--ref-seconds", type=float, default=120)
    args = ap.parse_args()

    import nemo.collections.asr as nemo_asr
    model = nemo_asr.models.EncDecSpeakerLabelModel.from_pretrained(MODEL).cuda().eval()

    t = json.loads(args.transcript.read_text(encoding="utf-8"))
    audio = load_audio(Path(t["source"]))
    import channel
    names = args.names.split(",") if args.names else channel.people()
    ref_name, ref_path = args.ref.split("=", 1)

    # Reference voiceprint: average over 6 s windows of the solo clip.
    ref_audio = load_audio(Path(ref_path), args.ref_seconds)
    win = 6 * SR
    ref = np.mean([embed(model, ref_audio[i:i + win]) for i in range(0, len(ref_audio) - win, win)], axis=0)
    ref /= np.linalg.norm(ref)

    embs = []
    for s in t["segments"]:
        a, b = s["start"], s["end"]
        if b - a < MIN_SEG:
            mid = (a + b) / 2
            a, b = max(0, mid - MIN_SEG / 2), mid + MIN_SEG / 2
        embs.append(embed(model, audio[int(a * SR):int(b * SR)]))
    embs = np.stack(embs)

    lab, cent = kmeans_cos(embs, len(names))
    ref_cluster = int((cent @ ref).argmax())
    others = iter(n for n in names if n != ref_name)
    cluster_name = {j: (ref_name if j == ref_cluster else next(others)) for j in range(len(names))}

    out = []
    for s, e, l in zip(t["segments"], embs, lab):
        sims = e @ cent.T
        margin = float(np.sort(sims)[-1] - np.sort(sims)[-2])
        out.append({"start": s["start"], "end": s["end"], "speaker": cluster_name[int(l)],
                    "score": round(margin, 3), "text": s["text"]})

    path = args.transcript.with_name(args.transcript.name.replace(".transcript.json", ".speakers.json"))
    path.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")

    for n in names:
        secs = sum(o["end"] - o["start"] for o in out if o["speaker"] == n)
        print(f"{n}: {sum(o['speaker'] == n for o in out)} segments, {secs/60:.1f} min")
    print(f"reference similarity per voice: " +
          ", ".join(f"{cluster_name[j]} {float(cent[j] @ ref):.2f}" for j in range(len(names))))
    print(f"low-confidence segments (margin < 0.05): {sum(o['score'] < 0.05 for o in out)}")
    print(f"-> {path}")


if __name__ == "__main__":
    sys.exit(main())
