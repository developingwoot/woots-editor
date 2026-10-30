"""Music audition list (Build tab): hear another track in place of a music bed, in the picture, before anything is re-stitched or rendered.

A "bed" is a run of consecutive beats that share the same audio.music name (builder.music_beds). For each bed the app offers the music library, and
"Hear it" renders a short clip of the stitched preview (the bed's own stretch, about 35 s) with the chosen track mixed under the speech exactly as the
stitch and the final render do (finalrender.mix). "Use it" writes the track's name into audio.music of every beat in the bed (an amendment on the approved beat map);
the next stitch then carries it. Needs a stitch made with this version (it keeps the sound without music in sections/<name>/musiccache/speech.wav).

Usage:  python musicaudition.py <work> <name>      # prints the beds and the tracks
Python needs numpy + soundfile (the app's venv).
"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

TOOLS = Path(os.path.abspath(__file__)).parent
sys.path.insert(0, str(TOOLS))
import builder  # noqa: E402
import config  # noqa: E402

CLIP_S = 35.0


def _stitch(work, name):
    return builder.read_json(builder.WORK / work / f"{name}.stitch.json", None)


def _speech(work, name) -> Path:
    return builder.WORK / work / "sections" / name / "musiccache" / "speech.wav"


def tracks() -> list:
    import finalrender as fr
    cat = {c["file"].lower(): c for c in (builder.read_json(config.EDITOR_DATA / "music_catalog.json", []) or [])}
    out = []
    for f in sorted(fr.MUSIC_DIR.iterdir()) if fr.MUSIC_DIR.exists() else []:
        if f.suffix.lower() not in fr.AUDIO_EXT:
            continue
        c = cat.get(f.name.lower(), {})
        if c.get("vocals") == "yes":                              # never under dialogue
            continue
        out.append({"name": f.stem, "bpm": c.get("bpm"), "bright": c.get("brightness_hz"), "dur": c.get("duration"), "vocals": c.get("vocals", ""),
                    "note": "vocals unclear: listen once" if c.get("vocals") == "maybe" else ""})
    return out


def beds(work, name) -> list:
    sj = _stitch(work, name)
    if not sj:
        return []
    secs = [{"beats": s["beats"], "dur": s.get("dur")} for s in sj["sections"]]
    return [{"i": i, "name": b["name"], "start": round(b["start"], 1), "end": round(b["end"], 1), "beats": b["beats"]} for i, b in enumerate(builder.music_beds(work, name, secs))]


def state(work, name) -> dict:
    sj = _stitch(work, name)
    return {"stitched": bool(sj), "ready": _speech(work, name).exists(), "beds": beds(work, name), "tracks": tracks() if sj else [],
            "note": "" if (sj and _speech(work, name).exists()) else "Stitch the preview once more (this version keeps the sound without music, which the audition needs)."}


def audition(work, name, i: int, track: str) -> dict:
    import finalrender as fr
    import numpy as np
    import soundfile as sf
    bl = beds(work, name)
    if not (0 <= i < len(bl)):
        raise ValueError("no such music bed (the beat map changed: stitch again)")
    if not _speech(work, name).exists():
        raise ValueError("stitch the preview once more first: the audition needs the sound without music")
    f, why = fr.resolve_music(track)
    if not f:
        raise ValueError(f"cannot use that track: {why}")
    bed = bl[i]
    length = min(CLIP_S, bed["end"] - bed["start"])
    a = bed["start"] + min(4.0, max(0.0, (bed["end"] - bed["start"] - length) / 2))
    cache = builder.WORK / work / "sections" / name / "musiccache"
    info = sf.info(str(_speech(work, name)))
    lo = max(0, int((a - 2.0) * fr.SR))                         # 2 s of lead-in so the music's fade-in and the ducking settle before the part you judge
    hi = min(info.frames, int((a + length) * fr.SR))
    speech, _ = sf.read(str(_speech(work, name)), start=lo, stop=hi, dtype="float32", always_2d=True)
    t0 = lo / fr.SR
    mixed, _ = fr.mix(speech, {"beds": [{"file": str(f), "start": 0.0, "end": len(speech) / fr.SR}], "sfx": []}, builder.settings_of(work, name), cache)
    peak = float(np.abs(mixed).max() or 1.0)
    if peak > 0.95:
        mixed = mixed * (0.95 / peak)
    wav = cache / "audition.wav"
    sf.write(str(wav), mixed, fr.SR, subtype="PCM_16")
    ff = builder.tool_env()
    exe = shutil.which("ffmpeg", path=ff["PATH"]) or "ffmpeg"
    out = builder.WORK / work / f"{name}.audition.mp4"
    tmp = out.with_name(out.stem + ".part.mp4")
    src = builder.WORK / work / _stitch(work, name)["file"]
    r = subprocess.run([exe, "-nostdin", "-y", "-v", "error", "-ss", f"{t0:.3f}", "-t", f"{len(speech) / fr.SR:.3f}", "-i", str(src), "-i", str(wav), "-map", "0:v", "-map", "1:a",
                        "-c:v", "libx264", "-preset", "veryfast", "-crf", "30", "-c:a", "aac", "-b:a", "160k", "-shortest", "-movflags", "+faststart", str(tmp)],
                       capture_output=True, text=True, env=ff)
    if r.returncode != 0:
        raise ValueError("could not make the clip: " + r.stderr.strip()[-200:])
    for k in range(8):
        try:
            os.replace(tmp, out)
            break
        except PermissionError:
            import time
            time.sleep(0.1 * (k + 1))
    return {"file": out.name, "bed": i, "track": f.stem, "from": round(t0, 1), "to": round(t0 + len(speech) / fr.SR, 1), "lead_in": 2.0}


def use(work, name, i: int, track: str) -> dict:
    import beatmap
    import finalrender as fr
    bl = beds(work, name)
    if not (0 <= i < len(bl)):
        raise ValueError("no such music bed (the beat map changed: stitch again)")
    f, why = fr.resolve_music(track)
    if not f:
        raise ValueError(f"cannot use that track: {why}")
    for bid in bl[i]["beats"]:
        beatmap.apply_edit(work, name, {"beat": bid, "set": {"audio.music": f.stem}, "why": f"The host: music audition, bed {i + 1} now {f.stem}"})
    return {"bed": i, "track": f.stem, "beats": bl[i]["beats"]}


if __name__ == "__main__":
    w, n = sys.argv[1], sys.argv[2]
    print(json.dumps({"beds": beds(w, n), "tracks": [t["name"] for t in tracks()]}, indent=1))
