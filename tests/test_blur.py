"""Blur a part of the picture (blur.py): a box drawn on the paused rough cut, followed through the clip, drawn by the render; and music asked for in a note."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures"))
import make_project  # noqa: E402
import blur  # noqa: E402
import cutview  # noqa: E402
import noteactions  # noqa: E402
import reviewnotes  # noqa: E402
import sections  # noqa: E402
import sectionrender  # noqa: E402
import views  # noqa: E402

needs_ffmpeg = pytest.mark.skipif(not make_project.have_ffmpeg(), reason="ffmpeg missing")


def plan(r) -> dict:
    return json.loads((r["dir"] / f"{r['name']}.beatmap.json").read_text(encoding="utf-8"))


def beat(r, bid) -> dict:
    return {b["id"]: b for b in plan(r)["beats"]}[bid]


def moving_square(path: Path, secs: float = 3.0):
    """A white square that slides right across a grey picture at 64 px a second (320 x 180, 30 fps)."""
    subprocess.run([sectionrender.FFMPEG, "-v", "error", "-y", "-f", "lavfi", "-i", f"color=c=0x404040:s=320x180:r=30:d={secs}",
                    "-f", "lavfi", "-i", f"color=c=white:s=40x40:r=30:d={secs}",
                    "-filter_complex", "[0:v]drawbox=x=0:y=150:w=320:h=30:color=0x2060c0:t=fill,drawgrid=w=16:h=16:t=1:c=0x606060[bg];"
                                       "[1:v]drawbox=x=8:y=8:w=8:h=24:color=black:t=fill[sq];[bg][sq]overlay=x='20+64*t':y=60",
                    "-pix_fmt", "yuv420p", str(path)], check=True)


def fake_follow(video, t0, t1, box, step=2):
    """The box moves right by 0.1 of the picture a second (no video needed)."""
    out, t = [], t0
    while t < t1 - 1e-6:
        out.append([round(t, 3), round(box[0] + 0.1 * (t - t0), 4), box[1], box[2], box[3]])
        t += 0.5
    out.append([round(t1, 3), round(box[0] + 0.1 * (t1 - t0), 4), box[1], box[2], box[3]])
    return out


@needs_ffmpeg
def test_the_box_follows_what_it_covers(tmp_path):
    src = tmp_path / "sq.mp4"
    moving_square(src)
    tr = blur.follow(str(src), 0.5, 2.5, [52 / 320, 60 / 180, 40 / 320, 40 / 180])
    assert tr[0][0] == 0.5 and abs(tr[-1][0] - 2.5) < 0.05
    x_end = tr[-1][1] * 320
    assert abs(x_end - (20 + 64 * 2.5)) < 10 and abs(tr[-1][2] * 180 - 60) < 8          # it went right with the square, not down


def test_a_still_path_is_two_boxes_and_a_box_between_them_is_in_a_straight_line():
    still = [[i / 10, 0.2, 0.3, 0.1, 0.1] for i in range(40)]
    assert blur.simplify(still) == [still[0], still[-1]]
    moving = [[i / 10, 0.2 + 0.01 * i, 0.3, 0.1, 0.1] for i in range(40)] + [[4.0 + i / 10, 0.6, 0.3, 0.1, 0.1] for i in range(1, 20)]
    keys = blur.simplify(moving)
    assert [k[0] for k in keys] == [0.0, 3.9, 4.1, 5.9]                                 # where it starts, the two ends of the turn, the end
    assert blur.box_at(keys, 1.0)[0] == pytest.approx(0.3, abs=0.01) and blur.box_at(keys, 9.0)[0] == 0.6
    many = [[i / 30, (i * 7919 % 101) / 101 * 0.8, 0.1, 0.05, 0.05] for i in range(900)]         # a jittery path never makes too long a command
    assert len(blur.simplify(many)) <= blur.MAX_KEYS


def test_a_blur_is_added_fixed_ended_and_removed_on_the_clip(tmp_path):
    beats = [{"id": "B01", "dur": 4.0, "aroll": {"rel": "a.mp4", "in": 0, "out": 4}, "on_screen": {"broll": []}},
             {"id": "B02", "dur": 6.0, "aroll": {"rel": "a.mp4", "in": 4, "out": 10}, "on_screen": {"broll": []}}]
    times = {"B01": (0.0, 4.0), "B02": (4.0, 6.0)}
    e = blur.add(beats, times, "v.mp4", 5.0, [0.1, 0.2, 0.2, 0.1], "blur", "my  username", fake_follow)
    assert (e["at"], e["dur"], e["what"]) == (1.0, 5.0, "my username") and beats[1]["on_screen"]["blur"] == [e] and e["id"].startswith("bl")
    bid = e["id"]
    assert e["track"][0][:2] == [0.0, 0.1] and e["track"][-1][0] == 5.0
    blur.fix(beats, times, "v.mp4", bid, 7.0, [0.5, 0.2, 0.2, 0.1], fake_follow)               # drifted at 0:07: the path before is kept
    tr = beats[1]["on_screen"]["blur"][0]["track"]
    assert [p[0] for p in tr if p[0] < 2.0] == [0.0, 0.5, 1.0, 1.5] and next(p for p in tr if p[0] == 2.0)[1] == 0.5
    blur.set_end(beats, times, "v.mp4", bid, 8.0, fake_follow)
    assert beats[1]["on_screen"]["blur"][0]["dur"] == 3.0 and beats[1]["on_screen"]["blur"][0]["track"][-1][0] == 3.0
    blur.set_end(beats, times, "v.mp4", bid, 9.5, fake_follow)                                 # later again: followed on from its last box
    assert beats[1]["on_screen"]["blur"][0]["track"][-1][0] == 4.5
    blur.fix(beats, times, "v.mp4", bid, 4.5, [0.4, 0.4, 0.1, 0.1], fake_follow)               # before its start: it starts there
    e = beats[1]["on_screen"]["blur"][0]
    assert e["at"] == 0.5 and e["dur"] == 5.0 and e["track"][0][1:] == [0.4, 0.4, 0.1, 0.1]
    blur.set_style(beats, bid, "block")
    assert blur.rows(beats, times)[0] | {"track": None} == {"id": bid, "beat": "B02", "start": 4.5, "end": 9.5, "what": "my username", "style": "block",
                                                            "placed": True, "track": None}
    with pytest.raises(ValueError):
        blur.set_style(beats, bid, "pixelate")
    blur.remove(beats, bid)
    assert beats[1]["on_screen"]["blur"] == []
    with pytest.raises(ValueError):
        blur.remove(beats, bid)


def test_a_blur_goes_on_every_piece_of_a_trimmed_clip_in_that_pieces_time():
    b = {"id": "B07", "dur": 6.0, "aroll": {"rel": "t.mp4", "in": 0.0, "out": 8.0, "keep": [[0.0, 3.0], [5.0, 8.0]]},
         "on_screen": {"broll": [], "blur": [{"id": "bl1", "at": 2.0, "dur": 3.0, "style": "blur", "track": [[0.0, 0.1, 0.1, 0.1, 0.1], [3.0, 0.4, 0.1, 0.1, 0.1]]},
                                             {"id": "bl2", "at": 0.0, "dur": 2.0, "style": "blur", "track": []}]}}          # not placed yet: not drawn
    got = blur.edit_rows(b, sections._pieces(b))
    assert [(x["seg"], x["at"], x["dur"]) for x in got] == [("B07", 2.0, 1.0), ("B07.2", 0.0, 2.0)]
    assert got[0]["track"][-1][1] == pytest.approx(0.2) and got[1]["track"][0][1] == pytest.approx(0.2) and got[1]["track"][-1][1] == pytest.approx(0.4)
    edit = sections.baseline_edit([b], "F:/footage")
    assert [x["seg"] for x in edit["blurs"]] == ["B07", "B07.2"]


@needs_ffmpeg
def test_the_render_blurs_the_box_and_follows_it(tmp_path):
    import numpy as np
    src = tmp_path / "sq.mp4"
    moving_square(src)
    tr = [[0.0, 20 / 320, 60 / 180, 40 / 320, 40 / 180], [3.0, (20 + 192) / 320, 60 / 180, 40 / 320, 40 / 180]]
    for style in ("blur", "block"):
        edit = {"size": [320, 180], "fps": 30, "snap": False, "segments": [{"id": "B01", "src": str(src), "in": 0.0, "out": 3.0}], "broll": [], "overlays": [],
                "blurs": [{"seg": "B01", "at": 0.5, "dur": 2.0, "style": style, "track": [[0.0, *blur.box_at(tr, 0.5)], [2.0, *blur.box_at(tr, 2.5)]]}]}
        (tmp_path / "e.json").write_text(json.dumps(edit), encoding="utf-8")
        out = sectionrender.render(tmp_path / "e.json", tmp_path / f"out-{style}", "x.mp4")["file"]

        def frame(t, path=out):
            r = subprocess.run([sectionrender.FFMPEG, "-v", "error", "-ss", str(t), "-i", str(path), "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "gray", "-"], capture_output=True)
            return np.frombuffer(r.stdout, np.uint8).reshape(180, 320).astype(float)
        x = int(20 + 64 * 1.5)
        square = frame(1.5)[65:95, x + 5:x + 35]
        if style == "block":
            assert square.mean() < 30                                                   # blacked out where the square is at 1.5 s
        else:
            assert square.std() < 0.5 * frame(1.5, src)[65:95, x + 5:x + 35].std()         # blurred: the black bar on the white square is smeared away
        assert np.abs(frame(0.2)[60:100, 20:60] - frame(0.2, src)[60:100, 20:60]).mean() < 12   # not before it starts
        assert np.abs(frame(1.5)[150:180] - frame(1.5, src)[150:180]).mean() < 12               # the rest of the picture is left alone


def test_a_long_path_goes_to_ffmpeg_in_a_file():
    blurs = [{"at": 0.0, "dur": 30.0, "style": "blur", "track": [[i / 4, (i % 7) / 10, 0.2, 0.1, 0.1] for i in range(120)]}]
    chains, last = blur.chains(blurs, "v0", 1920, 1080)
    assert last == "vbl0" and len(";".join(chains)) > 8000                        # long: sectionrender writes it to a file (checked by the render test above for short ones)


def blurs_project(title):
    r = make_project.build(cut=True, title=title)
    reviewnotes.add_version(r["work"], r["name"], "cut", r["dir"] / "footage" / "take1.mp4", ["The first cut"],
                            [{"start": 0.0, "dur": 3.0, "ref": "B01"}, {"start": 3.0, "dur": 3.0, "ref": "B02"}])
    return r


def test_a_blur_is_a_clip_change_for_the_next_cut(monkeypatch):
    r = blurs_project("blur notes")
    w, n = r["work"], r["name"]
    e = blur.do(w, n, "add", t=4.0, box=[0.1, 0.1, 0.2, 0.2], what="the username", follow_fn=fake_follow)
    assert beat(r, "B02")["on_screen"]["blur"][0]["id"] == e["id"] and beat(r, "B02")["on_screen"]["blur"][0]["at"] == 1.0
    assert [x["text"] for x in reviewnotes.open_notes(w, n, "cut")] == ["Blur the username at 0:04"]
    blur.do(w, n, "style", e["id"], style="block")                                     # one open change per blur
    assert [x["text"] for x in reviewnotes.open_notes(w, n, "cut")] == ["Black box over the username at 0:04"]
    v = views.review(w, n, "cut")
    assert v["button"]["enabled"] and v["blurs"][0]["start"] == 4.0 and v["clips"][1]["pending"] is None
    done = cutview.apply_choices(w, n)
    assert done["changes"] == ["Put a black box over the username at 0:04"] and beat(r, "B02")["on_screen"]["blur"][0]["style"] == "block"
    j = reviewnotes.load(w, n)
    for x in j["cut"]:
        x["status"] = "done"
    reviewnotes.save(w, n, j)
    blur.do(w, n, "delete", e["id"])                                                  # in a cut: taking it out is a change
    assert [x["text"] for x in reviewnotes.open_notes(w, n, "cut")] == ["No black box at 0:04 any more"] and beat(r, "B02")["on_screen"]["blur"] == []
    e2 = blur.do(w, n, "add", t=1.0, box=[0.1, 0.1, 0.2, 0.2], follow_fn=fake_follow)
    blur.do(w, n, "delete", e2["id"])                                                 # never in a cut: nothing to do
    assert [x["text"] for x in reviewnotes.open_notes(w, n, "cut")] == ["No black box at 0:04 any more"]


def test_a_note_can_ask_for_a_blur_and_for_music(tmp_path, monkeypatch):
    import config
    import finalrender
    music = tmp_path / "Music"
    music.mkdir()
    (music / "Calm Workshop.mp3").write_bytes(b"x")
    monkeypatch.setattr(config, "MUSIC_DIR", music)
    monkeypatch.setattr(finalrender, "MUSIC_DIR", music)
    r = blurs_project("blur note")
    w, n = r["work"], r["name"]
    times = {"B01": (0.0, 3.0), "B02": (3.0, 3.0)}
    got = noteactions.parse({"edits": [{"note": 1, "do": "blur", "time": "0:04", "what": "the username"}, {"note": 2, "do": "music", "from": "0:00", "until": "", "track": "calm workshop"},
                                       {"note": 2, "do": "music", "track": ""}]}, {1, 2})
    assert [a["do"] for a in got] == ["blur", "music"]
    done = noteactions.run(w, n, got, {}, log=lambda s: None, times=times)
    assert not done["failed"]
    e = beat(r, "B02")["on_screen"]["blur"][0]
    assert e["track"] == [] and e["at"] == 1.0 and e["what"] == "the username"
    assert views.review(w, n, "cut")["blurs"][0]["placed"] is False
    assert [beat(r, b).get("audio", {}).get("music") for b in ("B01", "B02")] == ["Calm Workshop", "Calm Workshop"]
    blur.do(w, n, "fix", e["id"], t=4.0, box=[0.3, 0.3, 0.1, 0.1], follow_fn=fake_follow)      # the host places it
    assert beat(r, "B02")["on_screen"]["blur"][0]["track"][0][1:] == [0.3, 0.3, 0.1, 0.1]
    bad = noteactions.run(w, n, [{"note": 3, "do": "music", "from": "0:00", "track": "rock anthem"}], {}, log=lambda s: None, times=times)
    assert "could not be used" in bad["failed"][3]


def test_a_note_can_take_words_out_of_a_clip_marked_good():
    beats = [{"id": "B01", "dur": 3.0, "aroll": {"rel": "a.mp4", "in": 0.0, "out": 3.0, "keep": None,
                                               "words": [["Or,", 0.1, 0.3], ["at", 0.35, 0.5], ["least", 0.55, 0.8], ["not", 0.85, 1.0], ["now.", 1.05, 1.3],
                                                         ["The", 1.6, 1.8], ["printer", 1.85, 2.4], ["works", 2.45, 2.9]]}, "on_screen": {"broll": []}},
             {"id": "B02", "dur": 2.0, "aroll": {"rel": "a.mp4", "in": 5.0, "out": 7.0, "keep": None, "words": [["next", 5.1, 5.5]]}, "on_screen": {"broll": []}}]
    times = {"B01": (0.0, 3.0), "B02": (3.0, 2.0)}
    said = noteactions.cut_words(beats, 3.5, "or at least not now", times)              # the time is a little late: the clip before is looked at too
    a = beats[0]["aroll"]
    assert said == "Took out “Or, at least not now.” at 0:00" and (a["in"], a["out"], a["keep"]) == (1.45, 3.0, None) and beats[0]["dur"] == 1.55
    beats[0]["aroll"] = {**a, "in": 0.0, "keep": None}
    noteactions.cut_words(beats, 0.5, "least not", times)                                  # from the middle: two pieces
    assert beats[0]["aroll"]["keep"] == [[0.0, 0.525], [1.025, 3.0]]
    with pytest.raises(ValueError, match="not found"):
        noteactions.cut_words(beats, 0.5, "hello there", times)


def test_a_note_can_lay_a_silent_recording_over_a_clip():
    r = blurs_project("broll note")
    w, n = r["work"], r["name"]
    times = {"B01": (0.0, 3.0), "B02": (3.0, 3.0)}
    got = noteactions.parse({"edits": [{"note": 1, "do": "broll", "time": "0:04", "file": "take3.mp4", "seconds": 2, "speed": 4}]}, {1})
    done = noteactions.run(w, n, got, {}, log=lambda s: None, times=times)
    assert not done["failed"] and done["changes"] == ["Showed take3.mp4 over the clip at 0:04 for 2 seconds at 4x speed"]   # kept inside the 3 s clip
    ins = beat(r, "B02")["on_screen"]["broll"][-1]
    assert (ins["file"], ins["dur"], ins["at"], ins["speed"]) == ("take3.mp4", 2.0, 1.0, 4.0)
    bad = noteactions.run(w, n, [{"note": 2, "do": "broll", "time": "0:04", "file": "../elsewhere.mp4"}], {}, log=lambda s: None, times=times)
    assert "not found in this video's footage folder" in bad["failed"][2]
    assert "take3.mp4" in noteactions.recordings_list(w, n)


def test_the_music_beds_follow_the_clips_of_the_rough_cut():
    beats = [{"id": "B01", "audio": {"music": "Calm"}}, {"id": "B02", "audio": {"music": "Calm"}}, {"id": "B03"}, {"id": "B04", "audio": {"music": "Calm"}}]
    rows = [{"ref": "B01", "start": 0.0, "dur": 3.0}, {"ref": "B02", "start": 3.0, "dur": 2.0}, {"ref": "B03", "start": 5.0, "dur": 1.0}, {"ref": "B04", "start": 6.0, "dur": 2.0}]
    assert cutview.music_beds(beats, rows) == [{"name": "Calm", "start": 0.0, "end": 5.0}, {"name": "Calm", "start": 6.0, "end": 8.0}]


@needs_ffmpeg
def test_the_rough_cut_has_the_music_of_the_plan(tmp_path, monkeypatch):
    import config
    import finalrender
    import shortsaudio
    music = tmp_path / "Music"
    music.mkdir()
    subprocess.run([sectionrender.FFMPEG, "-v", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=330:duration=20", "-ac", "2", "-ar", "48000", str(music / "Calm Workshop.wav")], check=True)
    monkeypatch.setattr(config, "MUSIC_DIR", music)
    monkeypatch.setattr(finalrender, "MUSIC_DIR", music)
    r = make_project.build(cut=True, title="cut music")
    bm = plan(r)
    for b in bm["beats"]:
        if b["id"] in ("B01", "B02"):
            b.setdefault("audio", {})["music"] = "Calm Workshop"
    (r["dir"] / f"{r['name']}.beatmap.json").write_text(json.dumps(bm), encoding="utf-8")
    mixed = []
    real = shortsaudio.mix_into
    monkeypatch.setattr(shortsaudio, "mix_into", lambda v, p, st=None: (mixed.append(p), real(v, p, st)))
    video, rows = cutview.render(r["work"], r["name"])
    assert [(b["name"], b["start"], b["end"]) for b in mixed[0]["beds"]] == [("Calm Workshop", 0.0, 6.0)] and video.is_file()
    probe = subprocess.run([sectionrender.FFPROBE, "-v", "error", "-select_streams", "a:0", "-show_entries", "stream=codec_name", "-of", "csv=p=0", str(video)], capture_output=True, text=True)
    assert probe.stdout.strip() == "aac"


def test_the_rough_cut_has_the_sound_effects_and_the_graphics_built_already(tmp_path, monkeypatch):
    import config
    import finalrender
    sfx = tmp_path / "SFX"
    sfx.mkdir()
    (sfx / "Ding.wav").write_bytes(b"x")
    monkeypatch.setattr(config, "SFX_DIR", sfx)
    monkeypatch.setattr(finalrender, "SFX_DIR", sfx)
    mov = tmp_path / "g.mov"
    mov.write_bytes(b"x")
    beats = [{"id": "B01", "dur": 3.0, "aroll": {"rel": "a.mp4", "in": 0.0, "out": 3.0}, "on_screen": {"shot": "a-roll", "broll": []}, "audio": {"sfx": ["Ding @ 1.0"]},
              "graphic": {"kind": "callout", "idea": "the nozzle", "dur": 2.0, "at": 0.5}},
             {"id": "B02", "dur": 3.0, "aroll": {"rel": "a.mp4", "in": 3.0, "out": 6.0}, "on_screen": {"shot": "a-roll", "broll": []},
              "graphic": {"kind": "callout", "idea": "not built yet", "dur": 2.0}}]
    built = {"B01": {"file": str(mov), "sig": sections.gsig(beats[0]["graphic"])}, "B02": {"file": str(mov), "sig": "an old design"}}
    edit = cutview.edit_for({"beats": beats}, "F:/footage", built)
    assert [(o["seg"], o["file"]) for o in edit["overlays"]] == [("B01", str(mov))]                # the one built for this design; the other is left out
    assert [(x["seg"], Path(x["file"]).name) for x in edit["sfx"]] == [("B01", "Ding.wav")]


def test_claude_is_given_the_music_library(tmp_path, monkeypatch):
    import config
    import makeversion
    music = tmp_path / "Music"
    music.mkdir()
    (music / "Calm Workshop.mp3").write_bytes(b"x")
    monkeypatch.setattr(config, "MUSIC_DIR", music)
    r = blurs_project("blur brief")
    prompt = makeversion.brief(r["work"], r["name"], "cut", tmp_path / "fd")
    assert (tmp_path / "fd" / "music.txt").read_text(encoding="utf-8") == "Calm Workshop"
    assert '"do": "music"' in prompt and '"do": "blur"' in prompt and '"do": "cut"' in prompt and '"do": "broll"' in prompt
    assert "take1.mp4" in (tmp_path / "fd" / "recordings.txt").read_text(encoding="utf-8")
