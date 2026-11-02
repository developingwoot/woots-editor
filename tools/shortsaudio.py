"""The sound of a short: a music bed under the voice and sound effects on the picture's moments.

  events(pieces, short, speed)          -> what the picture does, for sfxkit.place (a whoosh on each cut or zoom step, a hit when a graphic lands, a pop on a word
                                           that stands out, a ding on a number, a riser into the last line)
  plan(short, pieces, total_s, speed)   -> {"beds", "sfx", "missing", "track"}: the files and times to mix, and what is missing (never blocks a render)
  mix_into(video, plan)                 -> replaces the video file's sound with the voice + music + SFX, loudness -14 LUFS

The mix is audiomix.mix, the main video's recipe: the bed sits `music_below_speech_db` under the voice, `duck_db` further down while the host talks, and fades in and out.
short['music'] is '' (the app picks), 'none', or a track's name; short['sfx'] is '' / 'on' or 'off'. A track the catalog marks as having vocals is never used.
"""
import hashlib
import json
import tempfile
from pathlib import Path

import config
import sfxkit
import shorts as sh
import skillrules

BED_BPM = 110                      # the tempo the automatic choice leans towards: steady, not frantic


def catalog() -> dict:
    try:
        data = json.loads((config.EDITOR_DATA / "music_catalog.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {c["file"].lower(): c for c in data if isinstance(c, dict) and c.get("file")}


def tracks() -> list:
    """The music the host can choose from: [{"name", "file", "bpm", "note"}], vocals left out, steadiest first."""
    cat, d = catalog(), config.MUSIC_DIR
    out = []
    for f in sorted(d.iterdir()) if d.is_dir() else []:
        if f.suffix.lower() not in sfxkit.AUDIO_EXT:
            continue
        c = cat.get(f.name.lower(), {})
        if c.get("vocals") == "yes":
            continue
        out.append({"name": f.stem, "file": str(f), "bpm": c.get("bpm"), "swing": c.get("swing_db"),
                    "note": "vocals unclear: listen once" if c.get("vocals") == "maybe" else ""})
    return sorted(out, key=lambda t: (t["swing"] if t["swing"] is not None else 99, abs((t["bpm"] or BED_BPM) - BED_BPM), t["name"].lower()))


def choose_track(short: dict):
    """(the track, why not). The host's choice, or an automatic one that differs from short to short."""
    want = (short.get("music") or "").strip()
    if want.lower() == "none":
        return None, "music is switched off"
    have = tracks()
    if not have:
        return None, "there is no music in the Music folder"
    if want:
        t = next((t for t in have if t["name"].lower() == want.lower()), None)
        return (t, "") if t else (None, f"the track '{want}' was not found, or it has vocals")
    pick = int(hashlib.md5(str(short.get("id", "")).encode()).hexdigest(), 16) % min(3, len(have))
    return have[pick], ""


def events(pieces: list, short: dict, speed: float = 1.0) -> list:
    r = skillrules.shorts()
    lead = r["sfx_cut_lead_s"]
    ev = []
    for i, pc in enumerate(pieces):
        if i:
            ev.append({"t": (pc["t0"] - lead) / speed, "role": "whoosh"})
        if pc.get("layout") == "graphic":
            ev.append({"t": pc["t0"] / speed, "role": "hit"})
    for e in sh.emphasis(pieces, short):
        pc = pieces[e["i"]]
        first = not pc["cont"] and pc["words"] and pc["words"][0]["s"] == e["s"]
        ev.append({"t": e["t"] / speed, "role": "ding" if e["num"] else "pop", "first": bool(first)})
    if len(pieces) > 1:
        ev.append({"t": (pieces[-1]["t0"] - 1.0) / speed, "role": "riser"})
    return ev


def plan(short: dict, pieces: list, total_s: float, speed: float = 1.0) -> dict:
    out = {"beds": [], "sfx": [], "missing": [], "track": ""}
    track, why = choose_track(short)
    if track:
        out["beds"] = [{"file": track["file"], "start": 0.0, "end": total_s}]
        out["track"] = track["name"]
    elif why and why != "music is switched off":
        out["missing"].append(why)
    if (short.get("sfx") or "on") != "off":
        k = sfxkit.kit()
        if not sfxkit.files():
            out["missing"].append("there are no sound effects in the SFX folder")
        else:
            out["sfx"] = sfxkit.place(events(pieces, short, speed), k, total_s)
            out["missing"] += [f"no '{role}' sound in the kit" for role, fs in k.items() if not fs]
    return out


def mix_into(video: Path, mixplan: dict, st: dict | None = None):
    """Replace the sound of `video` (voice only, already at -14 LUFS) with voice + music + SFX at -14 LUFS."""
    import audiomix
    import soundfile as sf
    video = Path(video)
    st = st or {"duck_db": skillrules.shorts()["duck_db"], "music_below_speech_db": skillrules.shorts()["music_below_speech_db"]}
    with tempfile.TemporaryDirectory(prefix="shortmix_") as d:
        tmp = Path(d)
        r = audiomix.ff("-i", video, "-vn", "-ac", 2, "-ar", audiomix.SR, "-c:a", "pcm_f32le", tmp / "voice.wav")
        if r.returncode != 0:
            raise RuntimeError("could not read the short's sound: " + r.stderr.strip()[-200:])
        voice, _ = sf.read(str(tmp / "voice.wav"), dtype="float32", always_2d=True)
        mixed, _ = audiomix.mix(voice, mixplan, st, tmp)
        sf.write(str(tmp / "mixed.wav"), mixed, audiomix.SR, subtype="FLOAT")
        out = video.with_name(video.stem + ".mixed.mp4")         # on the same drive as the video, so the swap is one rename
        r = audiomix.ff("-i", video, "-i", tmp / "mixed.wav", "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-af", "loudnorm=I=-14:TP=-1.5:LRA=11",
                        "-c:a", "aac", "-b:a", "256k", "-movflags", "+faststart", out)
        if r.returncode != 0:
            raise RuntimeError("could not put the sound back: " + r.stderr.strip()[-200:])
        try:
            config.replace_retry(out, video)
        finally:
            out.unlink(missing_ok=True)
