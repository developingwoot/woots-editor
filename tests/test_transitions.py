"""Transitions: a cutaway comes in and goes out with a preset from the library (youtube-edit/transitions.json), with its sound in the preview and the final mix."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures"))
import make_project  # noqa: E402
import config  # noqa: E402
import skillrules  # noqa: E402
import transitions  # noqa: E402

needs_ffmpeg = pytest.mark.skipif(not make_project.have_ffmpeg(), reason="ffmpeg missing")


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    user = skillrules.SKILLS / transitions.FILE
    user.unlink(missing_ok=True)
    config.save_user_settings({"transition_web": "", "transition_broll": ""})
    yield
    user.unlink(missing_ok=True)
    config.save_user_settings({"transition_web": "", "transition_broll": ""})


def test_the_starter_library_has_the_presets_and_defaults():
    lib = transitions.library()
    assert {"cut", "dissolve", "slide", "slide-up", "whip", "pop", "flash"} <= set(lib["presets"])
    assert lib["defaults"] == {"web": "slide", "broll": "cut"}
    assert lib["presets"]["slide"]["sound"] == "whoosh" and lib["presets"]["cut"]["dur"] == 0.0


def test_a_users_preset_is_added_and_a_broken_one_is_left_out():
    p = skillrules.SKILLS / transitions.FILE
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"presets": {"zip": {"label": "Zip", "kind": "slide", "from": "top", "dur": 9, "sound": "laser"}, "bad": {"kind": "spin"}},
                             "defaults": {"web": "zip", "broll": "nope"}}), encoding="utf-8")
    lib = transitions.library()
    assert lib["presets"]["zip"] == {"id": "zip", "label": "Zip", "kind": "slide", "dur": 1.0, "from": "top", "sound": "none"}   # clamped; an unknown sound is none
    assert "bad" not in lib["presets"] and lib["defaults"] == {"web": "zip", "broll": "cut"}


def test_settings_choose_the_default_and_a_clip_can_choose_its_own():
    assert transitions.pick({"file": "x", "source": {"url": "https://a/"}})["id"] == "slide"
    assert transitions.pick({"file": "x"})["id"] == "cut"
    transitions.save_defaults({"broll": "dissolve"})
    assert transitions.view()["defaults"] == {"web": "slide", "broll": "dissolve"}
    assert transitions.pick({"file": "x"})["id"] == "dissolve"
    assert transitions.pick({"file": "x", "transition": "flash"})["id"] == "flash"
    with pytest.raises(ValueError):
        transitions.save_defaults({"web": "nope"})


def test_in_and_out_go_on_the_first_and_last_piece_with_their_sounds():
    slide = transitions.library()["presets"]["slide"]
    one = transitions.stamp([{"seg": "B1", "at": 0.5, "dur": 3.0}], slide)
    assert one[0]["t_in"]["kind"] == "slide" and one[0]["t_out"]["from"] == "right"
    assert transitions.sound_times(one[0]) == [(0.38, "whoosh"), (3.03, "whoosh")]         # each just before its move
    two = transitions.stamp([{"seg": "B1", "at": 2.0, "dur": 1.0}, {"seg": "B1.2", "at": 0.0, "dur": 2.0}], slide)
    assert "t_in" in two[0] and "t_out" not in two[0] and "t_out" in two[1] and "t_in" not in two[1]
    short = transitions.stamp([{"seg": "B1", "at": 0.0, "dur": 0.5}], slide)
    assert "t_in" not in short[0] and "t_out" not in short[0]                                 # too short for two moves
    assert transitions.stamp([{"seg": "B1", "at": 0.0, "dur": 3.0}], transitions.CUT) == [{"seg": "B1", "at": 0.0, "dur": 3.0}]


def test_the_filters_for_each_kind():
    br = {"at": 1.0, "dur": 2.0}
    t = lambda pid: {**br, **{k: {kk: v for kk, v in transitions.library()["presets"][pid].items() if kk in ("kind", "dur", "from", "sound")} for k in ("t_in", "t_out")}}  # noqa: E731
    assert "x='1*W*(1-" in transitions.overlay_xy(t("slide")) and "-1*W*" in transitions.overlay_xy(t("slide"))
    assert ":y='1*H*(1-" in transitions.overlay_xy(t("slide-up"))
    assert "alpha=1" in transitions.in_filters(t("dissolve"), 960, 540) and transitions.overlay_xy(t("dissolve")) == ""
    assert "color=white" in transitions.in_filters(t("flash"), 960, 540)
    assert "eval=frame" in transitions.in_filters(t("pop"), 960, 540) and "(W-w)/2" in transitions.overlay_xy(t("pop"))
    assert transitions.in_filters(br, 960, 540) == "" and transitions.overlay_xy(br) == ""


def test_a_web_page_slides_in_with_a_whoosh_in_the_edit_and_the_final_mix(tmp_path):
    import sections
    import finalrender
    sfx = config.SFX_DIR
    sfx.mkdir(parents=True, exist_ok=True)
    (sfx / "Whoosh_01.wav").write_bytes(b"x")
    page = tmp_path / "page.mp4"
    beats = [{"id": "B01", "dur": 4.0, "aroll": {"rel": "a.mp4", "in": 0.0, "out": 4.0}, "on_screen": {"shot": "a-roll", "broll": [
        {"file": str(page), "in": 0.0, "dur": 3.0, "at": 0.5, "source": {"url": "https://example.com/"}},
        {"file": str(page), "in": 0.0, "dur": 1.0, "at": 3.0}]}}]
    edit = sections.baseline_edit(beats, str(tmp_path))
    web, plain = edit["broll"]
    assert web["t_in"]["kind"] == "slide" and "t_in" not in plain
    assert [(x["seg"], x["at"], x["transition"]) for x in edit["sfx"]] == [("B01", 0.38, True), ("B01", 3.03, True)]
    got = finalrender.transition_sounds([{**web, "seg_info": {"start": 10.0}}])
    assert [x["t"] for x in got] == [10.38, 13.03] and got[0]["file"].endswith("Whoosh_01.wav")
    (sfx / "Whoosh_01.wav").unlink()


def test_changing_the_transition_makes_only_sections_with_a_moving_cutaway_out_of_date():
    import sections
    r = make_project.build(cut=True, title="transition sig")
    before = {s["id"]: s["sig"] for s in sections.plan(r["work"], r["name"], write=False)["sections"]}
    transitions.save_defaults({"web": "flash"})                                    # the fixture has no web page: nothing changes
    assert {s["id"]: s["sig"] for s in sections.plan(r["work"], r["name"], write=False)["sections"]} == before
    transitions.save_defaults({"broll": "dissolve"})                               # its voice-over beat has no second picture either
    p = r["dir"] / f"{r['name']}.beatmap.json"
    bm = json.loads(p.read_text(encoding="utf-8"))
    bm["beats"][0]["on_screen"]["broll"] = [{"file": "take3.mp4", "in": 0.0, "dur": 1.5, "at": 0.5}]
    p.write_text(json.dumps(bm), encoding="utf-8")
    mid = {s["id"]: s["sig"] for s in sections.plan(r["work"], r["name"], write=False)["sections"]}
    transitions.save_defaults({"broll": "pop"})
    after = {s["id"]: s["sig"] for s in sections.plan(r["work"], r["name"], write=False)["sections"]}
    changed = [k for k in mid if mid[k] != after[k]]
    assert len(changed) == 1                                                        # the section holding B01 only


@needs_ffmpeg
@pytest.mark.parametrize("pid", ["slide", "dissolve", "pop", "flash", "slide-up"])
def test_every_preset_renders(tmp_path, pid):
    import sectionrender
    a, b = tmp_path / "a.mp4", tmp_path / "b.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=320x180:r=30:d=3", "-f", "lavfi", "-i", "sine=d=3", "-shortest", str(a)], check=True)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "smptebars=s=640x360:r=30:d=3", str(b)], check=True)
    br = transitions.stamp([{"seg": "B01", "file": str(b), "in": 0.0, "dur": 2.0, "at": 0.5}], transitions.library()["presets"][pid])
    out = tmp_path / "out.mp4"
    sectionrender.render_segment({"size": [320, 180], "fps": 30}, {"id": "B01", "src": str(a)}, 0.0, 3.0, out, br, [], 0.0)
    assert abs(sectionrender.video_seconds(out, 30) - 3.0) < 0.05
