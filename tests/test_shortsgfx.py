import io
import json
import shutil
import subprocess

import pytest

import shortsapp
import shortsgfx as gx

RANGES = [[10.0, 30.0], [100.0, 115.0]]            # a 35 s short made of two clips of the main video


def good(t0=12.0, t1=17.0, **kw):
    g = {"t0": t0, "t1": t1, "words": "the gears turn", "what": "a gear train with the idler lit", "how": "the idler lights up on the word idler",
         "look": "ui", "place": "top", "text": "IDLER GEAR", "beats": [{"t": t0 + 0.5, "what": "on screen"}, {"t": (t0 + t1) / 2, "what": "idler lights"}, {"t": t1 - 0.3, "what": "all lit"}]}
    g.update(kw)
    return g


def test_how_many_graphics_a_short_may_have():
    assert gx.max_graphics([[0, 30]]) == 6                      # one per 6 s, plus one
    assert gx.max_graphics([[0, 5]]) == 2
    assert gx.max_graphics([[0, 1]]) == 1


def test_a_good_plan_is_kept_with_ids_and_defaults():
    kept, skipped = gx.validate_plan([good(12, 17), good(105, 110, look="nonsense", place="middle")], RANGES)
    assert skipped == [] and [g["id"] for g in kept] == ["g1", "g2"]
    assert kept[1]["look"] == "" and kept[1]["place"] == "top" and kept[0]["status"] == ""
    assert len(kept[0]["beats"]) == 3


def test_graphics_that_break_the_rules_are_left_out_with_a_reason():
    plan = [good(12, 12.4),                                      # too short
            good(12, 25),                                        # too long (13 s)
            good(40, 44),                                        # between the clips
            good(11, 15), good(13, 17),                          # the second overlaps the first
            good(20, 23, what=""),                               # says nothing
            {"t0": "x", "t1": 3}]
    kept, skipped = gx.validate_plan(plan, RANGES)
    assert [g["t0"] for g in kept] == [11.0]
    why = " | ".join(skipped)
    for part in ("outside 1 to 8 s", "not inside one of the short's clips", "overlaps an earlier graphic", "what it shows and how it moves", "no start and end time"):
        assert part in why, part


def test_too_many_graphics_for_the_length_are_trimmed():
    many = [good(10 + i * 2.1, 12 + i * 2.1) for i in range(9)]
    kept, skipped = gx.validate_plan(many, [[10.0, 30.0]])
    assert len(kept) == gx.max_graphics([[10.0, 30.0]]) == 4 and any("more than the 4 planned" in s for s in skipped)


def test_beats_outside_the_graphic_are_dropped():
    kept, _ = gx.validate_plan([good(12, 17, beats=[{"t": 13, "what": "ok"}, {"t": 50, "what": "far away"}, {"what": "no time"}])], RANGES)
    assert kept[0]["beats"] == [{"t": 13.0, "what": "ok"}]


def test_three_to_five_stills_per_graphic():
    g = {"t0": 10.0, "t1": 14.0, "beats": []}
    m = gx.key_moments(g)
    assert len(m) == 3 and m[0]["t"] < m[1]["t"] < m[2]["t"] and all(10 <= x["t"] <= 14 for x in m)
    five = {"t0": 10.0, "t1": 16.0, "beats": [{"t": 10.5 + i, "what": str(i)} for i in range(8)]}
    assert len(gx.key_moments(five)) == 5
    assert [x["what"] for x in gx.key_moments({"t0": 10, "t1": 14, "beats": [{"t": 11, "what": "a"}, {"t": 12, "what": "b"}, {"t": 13, "what": "c"}]})] == ["a", "b", "c"]


def test_marks_only_accept_known_statuses_and_graphics():
    short = {"ranges": RANGES}
    gx.import_plan(short, {"note": "n", "graphics": [good()]})
    assert short["gfx"]["graphics"][0]["id"] == "g1"
    g = gx.mark(short, "g1", "change", "make the idler orange")
    assert g["status"] == "change" and g["note"] == "make the idler orange"
    with pytest.raises(ValueError):
        gx.mark(short, "g1", "approved")
    with pytest.raises(ValueError):
        gx.mark(short, "g9", "ok")
    gx.import_plan(short, {"graphics": [good(), good(105, 110)]})            # a new plan replaces the old one and its marks
    assert short["gfx"]["graphics"][0]["status"] == ""


PIECES = [{"a": 10.0, "b": 20.0, "t0": 0.0, "dur": 10.0, "layout": "live", "cx": 0.5, "cy": 0.5, "zoom": 1.0},
          {"a": 20.0, "b": 30.0, "t0": 10.0, "dur": 10.0, "layout": "live", "cx": 0.5, "cy": 0.5, "zoom": 1.0},
          {"a": 100.0, "b": 115.0, "t0": 20.0, "dur": 15.0, "layout": "live", "cx": 0.5, "cy": 0.5, "zoom": 1.0}]


def test_main_video_time_maps_onto_the_short():
    assert gx.to_short(PIECES, 1.0, 12.0) == 2.0
    assert gx.to_short(PIECES, 1.0, 105.0) == 25.0
    assert gx.to_short(PIECES, 2.0, 105.0) == 12.5                  # a faster pace shortens the short
    assert gx.to_short(PIECES, 1.0, 60.0) in (20.0, 20.0 + 0.0)      # inside the cut between the clips: snaps to the nearest kept edge
    assert gx.piece_at(PIECES, 105.0)["a"] == 100.0


def test_the_strip_places_each_graphic_over_its_words():
    cfg = {"_tr": {"words": [{"word": "hello", "start": 12.0, "end": 12.5}, {"word": "idler", "start": 13.0, "end": 13.6},
                              {"word": "gear", "start": 105.0, "end": 105.4}], "segments": []}}
    short = {"ranges": RANGES}
    gx.import_plan(short, {"graphics": [good(12.8, 15.0), good(104.5, 108.0)]})
    v = gx.view(cfg, short, PIECES, "s1")
    assert v["total"] == 35.0 and v["cuts"] == [0.0, 10.0, 20.0] and v["planned"] is True
    assert [(w["w"], w["s"]) for w in v["words"]] == [("hello", 2.0), ("idler", 3.0), ("gear", 25.0)]
    g1, g2 = v["graphics"]
    assert (g1["ts0"], g1["ts1"]) == (2.8, 5.0) and (g2["ts0"], g2["ts1"]) == (24.5, 28.0)
    assert len(g1["moments"]) == 3 and g1["moments"][0]["ts"] >= g1["ts0"]


def test_the_prompt_carries_the_rules_the_words_and_the_main_videos_own_graphics():
    short = {"title": "Idler gear", "hook": "ONE GEAR|FIXES IT", "ranges": RANGES, "why": "clear fix", "thought": {"setup": "a", "point": "b", "payoff": "c"}}
    words = [{"w": "so", "s": 12.0, "e": 12.2}, {"w": "idler", "s": 12.3, "e": 12.8}]
    beats = [{"id": "B07", "start": 11.0, "end": 19.0, "graphic": {"kind": "gears", "style": "ui", "idea": "gear train", "words": "idler"}}]
    t = gx.prompt_for(short, words, beats)
    assert "graphics.json" in t and "never more than 7" in t and "[12.00-12.80] so idler" in t
    assert "B07 11.0-19.0: gears (ui): gear train" in t and "10.0-30.0, 100.0-115.0" in t and '"kinetic"' in t


# ----------------------------------------------------------------------------- draft stills from a real frame
needs_video = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not installed")


@needs_video
def test_a_draft_still_is_a_vertical_frame_with_the_card_where_the_plan_says(tmp_path):
    from PIL import Image
    src = tmp_path / "main.mp4"
    r = subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=1920x1080:rate=30:duration=4", "-pix_fmt", "yuv420p", str(src)])
    assert r.returncode == 0
    pieces = [{"a": 0.0, "b": 4.0, "t0": 0.0, "dur": 4.0, "layout": "live", "cx": 0.5, "cy": 0.5, "zoom": 1.0}]
    cfg = {"source": str(src), "_tr": {"words": [], "segments": []}}

    def still(place):
        short = {"ranges": [[0.0, 4.0]]}
        gx.import_plan(short, {"graphics": [{**good(0.5, 3.5), "place": place}]})
        return Image.open(io.BytesIO(gx.still_jpeg(cfg, short, pieces, "g1", 1, width=360)))
    top, bottom = still("top"), still("bottom")
    assert top.size == (360, 640)

    def navy_share(im, y0, y1):                                   # how much of a band is the card's navy
        px = [im.getpixel((x, y)) for x in range(20, 340, 4) for y in range(y0, y1, 4)]
        return sum(1 for r_, g_, b_ in px if abs(r_ - 20) < 25 and abs(g_ - 44) < 25 and abs(b_ - 68) < 25) / len(px)
    assert navy_share(top, 70, 230) > 0.5 > navy_share(bottom, 70, 230)      # the card is up high only when place is "top"
    assert navy_share(bottom, 480, 600) > 0.5 > navy_share(top, 480, 600)


# ----------------------------------------------------------------------------- through the app
def test_planning_needs_an_approved_short_and_marks_are_saved(tmp_path):
    import workflow
    r = workflow.create("Gfx Plan App")
    wd = workflow.WORK / r["work"]
    tr = wd / "t.json"
    tr.write_text(json.dumps({"duration": 100, "words": [{"word": "hi", "start": 12.0, "end": 12.4}], "segments": []}), encoding="utf-8")
    shortsapp.new_project(r["work"], r["name"], "main.mp4", str(tr), None)
    raw = shortsapp.read_raw(r["work"], r["name"])
    raw["shorts"] = [{"id": "s1", "title": "T", "hook": "H", "ranges": RANGES, "status": "proposed"}]
    shortsapp.save_raw(r["work"], r["name"], raw)
    assert "graphics.json" in shortsapp.gfx_prompt(r["work"], r["name"], "s1")
    p = tmp_path / "graphics.json"
    p.write_text(json.dumps({"note": "n", "graphics": [good()]}), encoding="utf-8")
    assert shortsapp.gfx_import(r["work"], r["name"], "s1", p)["added"] == 1
    shortsapp.gfx_mark(r["work"], r["name"], "s1", "g1", "ok")
    s = [x for x in shortsapp.state(r["work"], r["name"])["shorts"] if x["id"] == "s1"][0]
    assert s["gfx"]["graphics"][0]["status"] == "ok"
