import json
import shutil
import subprocess

import pytest

import shorts
import shortsgfx
import shortsgfxbuild as gb

needs_ffmpeg = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not installed")


def pieces_6s():
    return [{"a": 0.0, "b": 6.0, "dur": 6.0, "t0": 0.0, "src": "a", "cont": False, "layout": "live", "zoom": 1.0, "cx": 0.5, "cy": 0.5, "sw": 640, "sh": 360,
             "words": [{"w": "w", "s": 0.3 + 0.4 * i, "e": 0.6 + 0.4 * i, "src": "a"} for i in range(14)]}]


def gfx(**kw):
    base = {"id": "g1", "t0": 1.0, "t1": 5.0, "look": "ui", "place": "top", "text": "HOW IT WORKS\nfirst the gear\nthen the shaft\nthen the pin", "status": "ok"}
    return dict(base, **kw)


def short_with(*gs, ranges=None):
    return {"id": "s1", "ranges": ranges or [[0.0, 6.0]], "gfx": {"graphics": list(gs)}}


def test_every_graphic_the_host_has_not_cut_is_built_and_only_for_one_recording():
    s = short_with(gfx(), gfx(id="g2", status="cut"), gfx(id="g3", status="change", look="kinetic"), gfx(id="g4", status=""))
    assert [g["id"] for g in gb.wanted(s)] == ["g1", "g3", "g4"]
    mixed = short_with(gfx(), ranges=[{"src": "a", "a": 0, "b": 3}, {"src": "b", "a": 0, "b": 3}])
    assert gb.wanted(mixed) == [] and gb.wanted(short_with(gfx(), ranges=[{"src": "a", "a": 0, "b": 3}])) != []
    assert gb.wanted({}) == []


def test_a_cards_lines_are_its_headline_then_up_to_four_items():
    assert gb.lines_of(gfx()) == ["HOW IT WORKS", "first the gear", "then the shaft", "then the pin"]
    assert len(gb.lines_of(gfx(text="a\nb\nc\nd\ne\nf\ng"))) == 5
    assert gb.lines_of(gfx(text="", what="It shows the gear")) == ["It shows the gear"]
    assert gb.lines_of(gfx(text="", what="")) == []


def test_the_card_is_the_size_of_its_region_in_the_brand_colours_and_shows_more_items_as_it_goes():
    for place in ("top", "full", "bottom"):
        x0, y0, x1, y1 = shortsgfx.REGIONS[place]
        im = gb.draw_card(gfx(place=place), 0, 1.0)
        assert im.size == (x1 - x0, y1 - y0) and im.mode == "RGBA"
    half = gb.draw_card(gfx(), 0, 0.5)
    assert half.size == (492, 285)
    assert half.getpixel((0, 0))[3] == 0                                             # the rounded corner is see-through
    assert gb.draw_card(gfx(place="full"), 0, 0.5).getpixel((half.width // 2, 5))[3] == 255            # a full-frame card hides what is behind it

    def lit(im):
        import numpy as np
        a = np.asarray(im)
        return int(((a[..., 3] > 0) & (a[..., :3] != a[half.height // 2, half.width - 20, :3]).any(axis=2)).sum())
    assert lit(gb.draw_card(gfx(), 3, 0.5)) > lit(gb.draw_card(gfx(), 1, 0.5)) > lit(gb.draw_card(gfx(), 0, 0.5))
    assert gb.draw_card(gfx(text="", what=""), 0, 0.5).getbbox() is not None          # nothing to say: an empty panel, not a crash


def test_a_card_is_shown_in_steps_one_per_line_and_all_of_it_for_the_last_part(tmp_path):
    out = gb.cards(short_with(gfx()), pieces_6s(), 1.0, tmp_path, 0.5)
    assert len(out) == 4 and [c["first"] for c in out] == [True, False, False, False] and [c["last"] for c in out] == [False, False, False, True]
    assert out[0]["t0"] == 1.0 and out[-1]["t1"] == 5.0
    assert all(a["t1"] == b["t0"] for a, b in zip(out, out[1:]))
    assert out[-1]["t1"] - out[-1]["t0"] >= 0.3 * 4.0 / 4                           # the finished card stays up for a while
    assert (out[0]["x"], out[0]["y"]) == (24, 75) and all((tmp_path / f"gfx_0_{k}.png").is_file() for k in range(4))
    one = gb.cards(short_with(gfx(text="BIG IDEA")), pieces_6s(), 1.0, tmp_path, 0.5)
    assert len(one) == 1 and one[0]["first"] and one[0]["last"] and (one[0]["t0"], one[0]["t1"]) == (1.0, 5.0)
    assert gb.cards(short_with(gfx(look="kinetic")), pieces_6s(), 1.0, tmp_path, 0.5) == []
    assert gb.cards(short_with(gfx(t0=1.0, t1=1.2)), pieces_6s(), 1.0, tmp_path, 0.5) == []


def test_a_key_word_pops_in_the_accent_colour_inside_its_region_and_the_sounds_follow():
    s = short_with(gfx(look="kinetic", text="FORTY\nDOLLARS", t0=2.0, t1=3.0, place="bottom"), gfx(id="g2", t0=4.0, t1=5.5))
    ev = gb.kinetic_events(s, pieces_6s(), 1.0)
    assert len(ev) == 1 and (ev[0][0], ev[0][1]) == (2.0, 3.0)
    x0, y0, x1, y1 = shortsgfx.REGIONS["bottom"]
    assert f"\\pos({(x0 + x1) // 2},{(y0 + y1) // 2})" in ev[0][2] and "FORTY\\NDOLLARS" in ev[0][2] and "\\t(0,140" in ev[0][2]
    assert gb.kinetic_events(s, pieces_6s(), 2.0)[0][0] == 1.0                      # played at double speed: the pop comes earlier in the finished short
    assert [(e["t"], e["role"]) for e in gb.sound_events(s, pieces_6s(), 1.0)] == [(2.0, "pop"), (4.0, "hit")]
    assert "Dialogue: 3," in shorts.make_ass(s, pieces_6s()) and "Dialogue: 3," not in shorts.make_ass(short_with(gfx()), pieces_6s())


@needs_ffmpeg
def test_a_rendered_short_shows_the_card_over_the_video_only_while_it_is_up(tmp_path):
    import cv2
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=red:size=640x360:rate=30:duration=8", "-f", "lavfi", "-i", "sine=frequency=220:duration=8",
                    "-shortest", "-pix_fmt", "yuv420p", str(tmp_path / "v.mp4")], check=True)
    words = [{"word": "word", "start": 0.2 + 0.4 * i, "end": 0.5 + 0.4 * i} for i in range(18)]
    (tmp_path / "t.json").write_text(json.dumps({"duration": 8, "words": words, "segments": [{"start": 0.2, "end": 7.0, "text": "x"}]}), encoding="utf-8")
    short = {"id": "s1", "ranges": [[0.0, 7.0]], "music": "none", "sfx": "off",
             "gfx": {"graphics": [gfx(t0=2.0, t1=5.0, place="full", text="BIG IDEA"), gfx(id="g2", t0=5.5, t1=6.5, look="kinetic", text="WOW", place="bottom")]}}
    (tmp_path / "c.shorts.json").write_text(json.dumps({"source": str(tmp_path / "v.mp4"), "transcript": str(tmp_path / "t.json"), "shorts": [short]}), encoding="utf-8")
    cfg = shorts.load(tmp_path / "c.shorts.json")
    cfg["_short"] = cfg["shorts"][0]
    pieces = shorts.classify(cfg, shorts.build_pieces(cfg, cfg["shorts"][0]))
    out = tmp_path / "s1.mp4"
    total, _ = shorts.render(cfg, cfg["shorts"][0], str(out), pieces, "preview")
    assert shorts.probe_size(out) == (540, 960) and total > 5.6

    def at(t, x, y):
        cap = cv2.VideoCapture(str(out))
        cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
        ok, fr = cap.read()
        assert ok
        b, g, r = fr[y - 6:y + 6, x - 6:x + 6].reshape(-1, 3).mean(axis=0)
        return "red" if r > 150 and g < 90 else "dark" if r < 70 and g < 70 and b < 70 else "other"
    assert at(0.8, 40, 300) == "red"                                                  # before the card: the video
    assert at(3.5, 40, 300) == "dark"                                                 # the full-frame card is up (brand primary, opaque)
    assert at(total - 0.3, 40, 300) == "red"                                                  # after it: the video again
