"""The kind of video decides what a cutaway may cover: a talking head, never the host's hands on the thing."""
import json

import brolllib
import config
import recut
import videokind
import views
import workflow

FACE = {"kind": "real footage", "subject": "man with beard", "hands": False, "sharp": True}
HANDS = {"kind": "real footage", "subject": "person opening a box", "hands": True, "sharp": True}
THING = {"kind": "real footage", "subject": "white box", "hands": False, "sharp": True}
SCREEN = {"kind": "screen recording", "subject": "slicer", "hands": False, "sharp": True}


def test_the_kind_is_guessed_from_what_the_talking_recordings_show():
    assert videokind.guess([]) == "talking"
    assert videokind.guess([FACE] * 8 + [HANDS] * 2) == "talking"
    assert videokind.guess([FACE] * 4 + [HANDS] * 6) == "hands-on"
    assert videokind.guess([SCREEN] * 7 + [FACE] * 3) == "screen"


def _video(title, samples):
    r = workflow.create(title)
    w, n = r["work"], r["name"]
    words = [[f"w{i}", float(i), i + 0.5] for i in range(500)]
    (config.WORK / w / f"{n}.footage.json").write_text(json.dumps({"analysis": {"talk.mkv": {"dur": 600.0, "words": 500, "list": words}}}), encoding="utf-8")
    brolllib.paths(w, n)[1].write_text(json.dumps({"clips": {"talk.mkv": {"dur": 600.0, "samples": [{**s, "t": 30.0 * i} for i, s in enumerate(samples)]},
                                                             "broll.mkv": {"dur": 60.0, "samples": [{**FACE, "t": 1.0}] * 50}}}), encoding="utf-8")
    return w, n


def test_auto_looks_at_the_talking_recordings_only_and_the_hosts_choice_wins():
    w, n = _video("vk auto", [HANDS] * 6 + [FACE] * 4)
    assert videokind.get(w, n) == "auto" and videokind.resolve(w, n) == "hands-on"          # the 50 faces of the silent recording do not count
    v = videokind.view(w, n)
    assert v["value"] == "auto" and v["now"] == "hands-on" and v["hint"].startswith("Looks like: hands-on") and [o["id"] for o in v["options"]] == list(videokind.KINDS)
    videokind.set(w, n, "talking")
    assert videokind.resolve(w, n) == "talking" and views.footage_view(w, n)["kind"]["value"] == "talking"
    try:
        videokind.set(w, n, "vlog")
        raise AssertionError("an unknown kind was accepted")
    except ValueError:
        pass


def test_in_a_hands_on_video_only_a_known_face_may_be_covered():
    beat = {"aroll": {"rel": "talk.mkv", "in": 0.0, "out": 20.0, "keep": [[0.0, 20.0]], "words": []}}
    at = lambda s: [{**s, "t": 5.0}]
    recut.reload_rules("talking")
    assert not recut.is_demonstration(beat, 3.0, 8.0, at(THING)) and not recut.is_demonstration(beat, 3.0, 8.0, []) and recut.is_demonstration(beat, 3.0, 8.0, at(HANDS))
    recut.reload_rules("hands-on")
    assert recut.is_demonstration(beat, 3.0, 8.0, at(THING)) and recut.is_demonstration(beat, 3.0, 8.0, [])      # the thing alone, or not looked at: still the work
    assert not recut.is_demonstration(beat, 3.0, 8.0, at(FACE))
    recut.reload_rules()
    assert recut.KIND == "talking"


def test_claude_is_told_about_a_hands_on_video_and_nothing_extra_about_a_talking_one():
    assert videokind.line("talking") == "" and "hands-on video" in videokind.line("hands-on") and "screen" in videokind.line("screen")
