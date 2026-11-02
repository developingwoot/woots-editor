import json
import re
import shutil
import subprocess

import pytest

import audiomix
import channel
import config
import finalrender
import sfxkit
import shortsaudio
import shorts

needs_ffmpeg = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not installed")


def piece(i, a, b, t0, words, cont=False, layout="live"):
    return {"a": a, "b": b, "dur": b - a, "t0": t0, "src": "a", "cont": cont, "layout": layout, "zoom": 1.0, "cx": 0.5, "cy": 0.5, "sw": 640, "sh": 360,
            "words": [{"w": w, "s": s, "e": s + 0.3, "src": "a"} for w, s in words]}


def story():
    return [piece(0, 0, 4, 0.0, [("so", 0.3), ("it", 0.7), ("cost", 1.1), ("40", 1.6), ("dollars", 2.0)]),
            piece(1, 4, 8, 4.0, [("and", 4.3), ("Bambu", 5.0), ("printed", 5.5), ("it", 6.0)], cont=True),
            piece(2, 10, 14, 8.0, [("then", 10.3), ("42", 11.0), ("more", 11.5), ("sped", 12.0)])]


# ----------------------------------------------------------------------------- the shared mix
def test_the_final_render_and_shorts_use_the_same_mix():
    assert finalrender.mix is audiomix.mix and finalrender.decode is audiomix.decode and finalrender.SR == audiomix.SR == 48000


def test_the_music_sits_under_the_voice_and_dips_while_it_talks(tmp_path):
    import numpy as np
    import soundfile as sf
    sr = audiomix.SR
    t = np.arange(sr * 12) / sr
    voice = (0.2 * np.sin(2 * np.pi * 220 * t) * (t < 6))[:, None].repeat(2, 1).astype("float32")           # talks for 6 s, then silence
    sf.write(str(tmp_path / "m.wav"), (0.3 * np.sin(2 * np.pi * 330 * np.arange(sr * 12) / sr))[:, None].repeat(2, 1).astype("float32"), sr)
    out, _ = audiomix.mix(voice, {"beds": [{"file": str(tmp_path / "m.wav"), "start": 0.0, "end": 12.0}], "sfx": []}, {"duck_db": 9, "music_below_speech_db": 26}, tmp_path)
    music = out - voice
    talk, quiet = np.abs(music[sr * 2: sr * 4]).mean(), np.abs(music[sr * 8: sr * 10]).mean()
    assert quiet > talk * 1.5 and talk > 0                                       # louder where nobody talks


# ----------------------------------------------------------------------------- captions
def ass_events(short, pieces):
    return [l for l in shorts.make_ass(short, pieces).splitlines() if l.startswith("Dialogue: 1")]


def test_numbers_terms_and_marked_words_stand_out_no_more_than_one_per_gap(monkeypatch):
    monkeypatch.setattr(channel, "spellings", lambda p=None: ["Bambu"])
    got = shorts.emphasis(story(), {"emphasis": ["sped"]})
    assert [e["w"] for e in got] == ["40", "Bambu", "42", "sped"] or [e["w"] for e in got] == ["40", "Bambu", "sped"]
    assert all(b["t"] - a["t"] >= 3.0 for a, b in zip(got, got[1:]))
    assert next(e for e in got if e["w"] == "40")["num"] is True
    assert shorts.emphasis(story(), {}) != [] and shorts.emphasis([], {}) == []


def test_each_caption_style_marks_the_spoken_word_its_own_way():
    pcs = story()
    pop = "\n".join(ass_events({"caption_style": "pop"}, pcs))
    box = "\n".join(ass_events({"caption_style": "box"}, pcs))
    bounce = "\n".join(ass_events({"caption_style": "bounce"}, pcs))
    plain = "\n".join(ass_events({"caption_style": "plain"}, pcs))
    assert "\\t(0,110" in pop and "\\bord16" not in pop
    assert "\\bord16" in box and "\\t(0,110" not in box
    assert "\\move(" in bounce and "\\move(" not in plain and "\\bord16" not in plain
    assert shorts.caption_style({"caption_style": "nonsense"}) == "pop" and shorts.caption_style({}) == "pop"


def test_a_short_line_stays_centred_and_a_wide_one_moves_left_of_the_buttons():
    assert shorts.caption_pos("live", 9)[0] == 540
    x, y = shorts.caption_pos("live", 14)
    assert x < 540 and x + 14 * shorts.CHAR_PX / 2 <= 1080 - 150
    assert shorts.caption_size(9) == 122 and shorts.caption_size(17) < 122 and 17 * shorts.CHAR_PX * shorts.caption_size(17) / 122 <= 1080 - 150      # a line too wide shrinks to fit
    assert shorts.caption_pos("graphic", 9)[1] <= 1920 - 380 - 90 and shorts.caption_pos("live", 9)[1] >= 1050


def test_no_caption_or_hook_leaves_the_safe_zone_and_no_two_lines_overlap():
    pcs = story() + [piece(3, 14, 18, 12.0, [("graphic", 14.3), ("words", 15.0), ("here", 16.0)], layout="graphic")]
    text = shorts.make_ass({"hook": "WHY IT BROKE|40 DOLLARS"}, pcs)
    caps = [l for l in text.splitlines() if l.startswith("Dialogue: 1")]
    for l in text.splitlines():
        m = re.search(r"\\pos\((\d+),(\d+)\)", l) or re.search(r"\\move\(\d+,\d+,(\d+),(\d+)", l)
        if m and l.startswith("Dialogue: 1"):
            assert 1050 <= int(m.group(2)) <= 1920 - 380 - 90 and int(m.group(1)) <= 1080 - 150
    hook = next(l for l in text.splitlines() if "Hook," in l and l.startswith("Dialogue"))
    assert int(re.search(r"\\pos\((\d+),", hook).group(1)) <= 1080 - 150

    def secs(t):
        h, m, s = t.split(":")
        return int(h) * 3600 + int(m) * 60 + float(s)
    times = sorted((secs(l.split(",")[1]), secs(l.split(",")[2])) for l in caps)
    assert all(b0 >= a1 - 1e-6 for (a0, a1), (b0, b1) in zip(times, times[1:]))


# ----------------------------------------------------------------------------- the sound effect kit
def sound_folder(tmp_path, names):
    d = tmp_path / "SFX"
    (d / "sub").mkdir(parents=True)
    for n in names:
        (d / n).write_bytes(b"x")
    return d


def test_the_kit_is_guessed_from_file_names_and_the_users_choice_wins(tmp_path, monkeypatch):
    d = sound_folder(tmp_path, ["Whoosh_01.wav", "sub/swoosh fast.wav", "Pop 2.wav", "bell ding.mp3", "big boom.wav", "Riser long.wav", "birds.wav", "notes.txt"])
    monkeypatch.setattr(config, "SFX_DIR", d)
    monkeypatch.setattr(sfxkit, "KIT_FILE", tmp_path / "kit.json")
    k = sfxkit.kit()
    assert sorted(f.name for f in k["whoosh"]) == ["Whoosh_01.wav", "swoosh fast.wav"] and [f.name for f in k["ding"]] == ["bell ding.mp3"]
    assert [f.name for f in k["hit"]] == ["big boom.wav"] and [f.name for f in k["riser"]] == ["Riser long.wav"]
    assert "birds.wav" not in {f.name for fs in k.values() for f in fs}
    sfxkit.save_kit({"whoosh": ["sub/swoosh fast.wav"], "pop": [], "nonsense": ["x"]})
    k = sfxkit.kit()
    assert [f.name for f in k["whoosh"]] == ["swoosh fast.wav"] and k["pop"] == [] and [f.name for f in k["ding"]] == ["bell ding.mp3"]
    v = sfxkit.view()
    assert v["has_folder"] and "sub/swoosh fast.wav" in v["all"] and [r["role"] for r in v["roles"]] == sfxkit.PRIORITY


def test_sounds_keep_their_distance_their_cap_and_their_priority(tmp_path):
    chosen = {r: [tmp_path / f"{r}{i}.wav" for i in (1, 2)] for r in sfxkit.ROLES}
    events = [{"t": 1.0, "role": "whoosh"}, {"t": 1.2, "role": "pop"}, {"t": 1.25, "role": "hit"}, {"t": 5.0, "role": "ding", "first": True},
              {"t": 6.0, "role": "ding"}, {"t": 6.5, "role": "whoosh"}, {"t": 99.0, "role": "pop"}]
    got = sfxkit.place(events, chosen, 20.0)
    assert [(s["t"], s["role"]) for s in got] == [(1.25, "hit"), (6.0, "ding"), (6.5, "whoosh")]           # the hit wins over its neighbours; nothing on a first word; nothing past the end
    many = [{"t": 0.5 * i, "role": "pop"} for i in range(40)]
    placed = sfxkit.place(many, chosen, 30.0)
    assert sfxkit.spaced([s["t"] for s in placed], 0.4, 6) and len(placed) >= 10
    a = sfxkit.place([{"t": 1.0, "role": "pop"}, {"t": 3.0, "role": "pop"}], chosen, 20.0)
    assert a[0]["file"] != a[1]["file"]                                                                      # not the same sound twice in a row
    assert sfxkit.place(events, {"hit": []}, 20.0) == []


# ----------------------------------------------------------------------------- the music and the plan
def music_folder(tmp_path, monkeypatch, names, catalog=None):
    d = tmp_path / "Music"
    d.mkdir()
    for n in names:
        (d / n).write_bytes(b"x")
    monkeypatch.setattr(config, "MUSIC_DIR", d)
    monkeypatch.setattr(config, "EDITOR_DATA", tmp_path / "ed")
    (tmp_path / "ed").mkdir()
    (tmp_path / "ed" / "music_catalog.json").write_text(json.dumps(catalog or []), encoding="utf-8")
    return d


def test_the_music_choice_never_picks_a_track_with_vocals_and_the_host_can_switch_it_off(tmp_path, monkeypatch):
    music_folder(tmp_path, monkeypatch, ["calm.mp3", "song.mp3", "maybe.mp3", "readme.txt"],
                 [{"file": "calm.mp3", "bpm": 100, "swing_db": 2, "vocals": "no"}, {"file": "song.mp3", "bpm": 100, "swing_db": 1, "vocals": "yes"},
                  {"file": "maybe.mp3", "bpm": 150, "swing_db": 6, "vocals": "maybe"}])
    names = [t["name"] for t in shortsaudio.tracks()]
    assert names == ["calm", "maybe"]                                                         # the vocal track and the text file are not offered; steadiest first
    assert all(shortsaudio.choose_track({"id": f"s{i}"})[0]["name"] in names for i in range(8))
    assert len({shortsaudio.choose_track({"id": f"s{i}"})[0]["name"] for i in range(8)}) == 2   # not the same bed under every short
    assert shortsaudio.choose_track({"music": "song"})[0] is None and "vocals" in shortsaudio.choose_track({"music": "song"})[1]
    assert shortsaudio.choose_track({"music": "maybe"})[0]["name"] == "maybe"
    assert shortsaudio.choose_track({"music": "none"}) == (None, "music is switched off")


def test_a_missing_music_or_sfx_folder_is_said_not_a_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "MUSIC_DIR", tmp_path / "nope")
    monkeypatch.setattr(config, "SFX_DIR", tmp_path / "nope2")
    p = shortsaudio.plan({"id": "s1"}, story(), 12.0)
    assert p["beds"] == [] and p["sfx"] == [] and any("Music folder" in m for m in p["missing"]) and any("SFX folder" in m for m in p["missing"])
    assert shortsaudio.plan({"id": "s1", "sfx": "off", "music": "none"}, story(), 12.0)["missing"] == []


def test_the_events_of_a_short_follow_its_cuts_numbers_and_graphics(tmp_path, monkeypatch):
    monkeypatch.setattr(channel, "spellings", lambda p=None: [])
    pcs = story() + [piece(3, 14, 18, 12.0, [("x", 14.3)], layout="graphic")]
    roles = [(round(e["t"], 2), e["role"]) for e in shortsaudio.events(pcs, {}, 1.0)]
    assert (3.92, "whoosh") in roles and (7.92, "whoosh") in roles and (12.0, "hit") in roles and (11.0, "riser") in roles
    assert any(r == "ding" for _, r in roles)
    fast = [(round(e["t"], 2), e["role"]) for e in shortsaudio.events(pcs, {}, 2.0)]
    assert (6.0, "hit") in fast                                                               # the short is played faster: the sounds follow


@needs_ffmpeg
def test_a_rendered_short_gets_its_music_and_sound_effects(tmp_path, monkeypatch):
    import numpy as np
    import soundfile as sf
    sr = 48000
    d = music_folder(tmp_path, monkeypatch, [])
    sf.write(str(d / "calm.wav"), (0.3 * np.sin(2 * np.pi * 330 * np.arange(sr * 5) / sr))[:, None].repeat(2, 1).astype("float32"), sr)
    s = tmp_path / "SFX"
    s.mkdir()
    sf.write(str(s / "whoosh 1.wav"), (0.5 * np.sin(2 * np.pi * 900 * np.arange(sr // 4) / sr))[:, None].repeat(2, 1).astype("float32"), sr)
    monkeypatch.setattr(config, "SFX_DIR", s)
    monkeypatch.setattr(sfxkit, "KIT_FILE", tmp_path / "kit.json")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=red:size=640x360:rate=30:duration=10", "-f", "lavfi", "-i", "sine=frequency=220:duration=10",
                    "-shortest", "-pix_fmt", "yuv420p", str(tmp_path / "v.mp4")], check=True)
    words = [{"word": w, "start": 0.2 + 0.4 * i, "end": 0.5 + 0.4 * i} for i, w in enumerate("this is a test of the sound and it has 42 words in it".split())]
    (tmp_path / "t.json").write_text(json.dumps({"duration": 10, "words": words, "segments": [{"start": 0.2, "end": 6.0, "text": "x"}]}), encoding="utf-8")
    cfg_path = tmp_path / "c.shorts.json"
    short = {"id": "s1", "ranges": [[0.0, 3.0], [3.0, 7.0]], "music": "calm"}
    cfg_path.write_text(json.dumps({"source": str(tmp_path / "v.mp4"), "transcript": str(tmp_path / "t.json"), "shorts": [short]}), encoding="utf-8")
    cfg = shorts.load(cfg_path)
    cfg["_short"] = cfg["shorts"][0]
    pieces = shorts.classify(cfg, shorts.build_pieces(cfg, cfg["shorts"][0]))

    def audio_level(path):
        r = subprocess.run(["ffmpeg", "-v", "info", "-i", str(path), "-vn", "-af", "volumedetect", "-f", "null", "-"], capture_output=True, text=True)
        return float(re.search(r"mean_volume: (-?[\d.]+) dB", r.stderr).group(1))
    plain = {}
    shorts.render(cfg, dict(cfg["shorts"][0], music="none", sfx="off"), str(tmp_path / "plain.mp4"), pieces, "preview", plain)
    full = {}
    shorts.render(cfg, cfg["shorts"][0], str(tmp_path / "full.mp4"), pieces, "preview", full)
    assert plain["audio"] == {"track": "", "sfx": 0, "missing": []}
    assert full["audio"]["track"] == "calm" and full["audio"]["sfx"] >= 1
    assert audio_level(tmp_path / "full.mp4") != pytest.approx(audio_level(tmp_path / "plain.mp4"), abs=0.05)
    assert shorts.probe_size(tmp_path / "full.mp4") == (540, 960)
    loud = subprocess.run(["ffmpeg", "-v", "info", "-i", str(tmp_path / "full.mp4"), "-vn", "-af", "ebur128=peak=true", "-f", "null", "-"], capture_output=True, text=True).stderr
    lufs = float(re.findall(r"I:\s+(-?[\d.]+) LUFS", loud)[-1])
    assert -16.5 < lufs < -12.5                                                               # about -14 LUFS, as for the voice alone


def test_a_line_too_wide_gets_its_own_smaller_style_that_the_file_defines():
    wide = [piece(0, 0, 3, 0.0, [("incomprehensibilities", 0.3), ("extraordinary", 1.0)])]
    text = shorts.make_ass({}, wide)
    used = {l.split(",")[3] for l in text.splitlines() if l.startswith("Dialogue: 1")}
    defined = {l.split(":")[1].split(",")[0].strip() for l in text.splitlines() if l.startswith("Style:")}
    assert used and used <= defined and any(u != "Cap" for u in used)
