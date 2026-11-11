"""B-roll and on-screen text ideas on the rough cut (ideas.py) and the on-screen text cards they make (textcards.py)."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures"))
import make_project  # noqa: E402
import cutview  # noqa: E402
import ideas  # noqa: E402
import noteactions  # noqa: E402
import reviewnotes  # noqa: E402
import sections  # noqa: E402
import sectionrender  # noqa: E402
import textcards  # noqa: E402
import views  # noqa: E402

needs_ffmpeg = pytest.mark.skipif(not make_project.have_ffmpeg(), reason="ffmpeg missing")


def plan(r) -> dict:
    return json.loads((r["dir"] / f"{r['name']}.beatmap.json").read_text(encoding="utf-8"))


def beat(r, bid) -> dict:
    return {b["id"]: b for b in plan(r)["beats"]}[bid]


def library(r, clips: dict):
    import brolllib
    _, jp, _, _ = brolllib.paths(r["work"], r["name"])
    jp.write_text(json.dumps({"clips": clips}), encoding="utf-8")


def answer(tmp_path, found) -> Path:
    p = tmp_path / "ideas.json"
    p.write_text(json.dumps({"ideas": found}), encoding="utf-8")
    return p


def test_a_card_is_a_transparent_frame_with_a_box_at_the_bottom_left():
    from PIL import Image
    p = textcards.card("*0.4 mm nozzle, not 0.6", "correction")
    img = Image.open(p)
    assert img.size == (1920, 1080) and img.mode == "RGBA"
    assert img.getpixel((10, 10))[3] == 0 and img.getpixel((1800, 900))[3] == 0          # clear everywhere but the box
    assert img.getpixel((textcards.LEFT + 60, 1080 - textcards.BOTTOM - 10))[3] > 200       # inside the box
    stamp = p.stat().st_mtime_ns
    assert textcards.card("*0.4 mm   nozzle, not 0.6", "correction") == p and p.stat().st_mtime_ns == stamp     # drawn once
    assert textcards.card("*0.4 mm nozzle, not 0.6", "detail") != p
    with pytest.raises(ValueError):
        textcards.card("  ")


def test_the_stripe_stays_visible_on_the_box():
    b = {"primary": "#1A1A1A", "accent": "#FFC400", "light": "#FFFFFF", "dark": "#000000"}
    assert textcards.bar_colour("correction", b) == "#FFC400" and textcards.bar_colour("detail", b) == "#FFFFFF"     # a near-black primary on a black box
    assert textcards.bar_colour("detail", {**b, "primary": "#142C44", "dark": "#FFFFFF"}) == "#142C44"


def test_a_text_row_is_kept_inside_its_clip():
    assert textcards.entry({"text": " a  b ", "at": 2.5, "dur": 4}, 3.0, 4.0) == {"text": "a b", "kind": "detail", "at": 2.0, "dur": 1.0}
    assert textcards.entry({"text": "x", "kind": "correction"}, 10.0, 4.0)["dur"] == 4.0
    assert textcards.entry({"text": ""}, 3.0, 4.0) is None


def test_on_screen_text_becomes_still_overlays_that_fade_and_carry_over_a_jump_cut():
    b = {"id": "B07", "dur": 6.0, "aroll": {"rel": "t.mp4", "in": 0.0, "out": 8.0, "keep": [[0.0, 3.0], [5.0, 8.0]]},
         "on_screen": {"shot": "a-roll", "broll": [], "text": [{"text": "*right words", "kind": "correction", "at": 2.0, "dur": 3.0}]}}
    got = sections._text_overlays(b, [])
    assert [(o["seg"], o["at"], o["dur"]) for o in got] == [("B07", 2.0, 1.0), ("B07.2", 0.0, 2.0)]
    assert all(o["still"] and o["card"] for o in got) and got[0].get("fade_in") and not got[0].get("fade_out") and got[1].get("fade_out") and not got[1].get("fade_in")
    assert sectionrender.card_fades({"still": True, "dur": 3.0, "fade_in": True, "fade_out": True}) == "fade=t=in:st=0:d=0.200:alpha=1,fade=t=out:st=2.800:d=0.200:alpha=1,"
    assert sectionrender.card_fades({"dur": 3.0}) == ""


@needs_ffmpeg
def test_the_card_is_on_the_picture_only_while_it_shows(tmp_path):
    import numpy as np
    src = tmp_path / "t.mp4"
    make_project.make_clip(src, 3, 220)
    card = textcards.card("*a correction", "correction")
    edit = {"size": [320, 180], "fps": 30, "snap": False, "segments": [{"id": "B01", "src": str(src), "in": 0.0, "out": 3.0}], "broll": [],
            "overlays": [{"seg": "B01", "file": str(card), "at": 1.0, "dur": 1.0, "still": True, "fade_in": True, "fade_out": True}]}
    (tmp_path / "e.json").write_text(json.dumps(edit), encoding="utf-8")
    out = sectionrender.render(tmp_path / "e.json", tmp_path / "out", "x.mp4")["file"]

    def box(t, path=out):
        r = subprocess.run([sectionrender.FFMPEG, "-v", "error", "-ss", str(t), "-i", str(path), "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True)
        f = np.frombuffer(r.stdout, np.uint8).reshape(180, 320, 3)
        return f[146:152, 24:60].astype(float)                    # inside the box (1080p box scaled to 320 x 180)
    plain = subprocess.run([sectionrender.FFMPEG, "-v", "error", "-y", "-i", str(src), "-vf", "fps=30", str(tmp_path / "plain.mp4")])
    assert plain.returncode == 0
    assert np.abs(box(1.5) - box(1.5, tmp_path / "plain.mp4")).mean() > 40          # covered while it shows
    assert np.abs(box(0.5) - box(0.5, tmp_path / "plain.mp4")).mean() < 15          # not before
    assert np.abs(box(2.6) - box(2.6, tmp_path / "plain.mp4")).mean() < 15          # nor after


def test_claudes_ideas_are_checked_and_replace_the_unanswered_ones(tmp_path, monkeypatch):
    import webcapture

    def check(u):
        if "localhost" in u:
            raise ValueError("only public web pages")
        return u
    monkeypatch.setattr(webcapture, "check_url", check)                 # no network in tests
    r = make_project.build(cut=True, title="ideas import")
    w, n = r["work"], r["name"]
    library(r, {"bench.mp4": {"dur": 20.0, "samples": [{"t": 4.0, "subject": "printer", "what": "the printer door"}]}})
    found = [{"beat": "B01", "quote": "the tape shirt", "kind": "footage", "rel": "bench.mp4", "t": 4.0, "text": "the printer door", "why": "shows it"},
             {"beat": "B01", "kind": "footage", "rel": "nowhere.mp4", "t": 4.0, "text": "x"},                    # not in the footage
             {"beat": "B02", "kind": "web", "url": "http://localhost:8765/", "text": "x"},                         # not a public page
             {"beat": "B02", "kind": "web", "url": "https://store.example/spool", "find": "Reusable", "text": "the spool page"},
             {"beat": "B03", "kind": "film", "text": "the nozzle close up"},
             {"beat": "B03", "kind": "correction", "quote": "the end", "text": "*the very  end"},
             {"beat": "B03", "kind": "correction", "text": "*the very end"},                                       # the same one again
             {"beat": "B99", "kind": "detail", "text": "x"}, {"beat": "B01", "kind": "dance", "text": "x"}, "junk"]
    ok, msg = ideas.import_found(w, n, answer(tmp_path, found))
    got = ideas.load(w, n)
    assert ok and [(i["beat"], i["kind"]) for i in got] == [("B01", "footage"), ("B02", "web"), ("B03", "film"), ("B03", "correction")]
    assert got[0]["at"] == 1.5 and got[3]["text"]                                                  # "the tape shirt" is halfway through the 3 s clip == "*the very end" and all(i["status"] == "suggested" for i in got) and "4 ideas" in msg
    ideas.set_status(w, n, got[1]["id"], "no")
    ideas.import_found(w, n, answer(tmp_path, [{"beat": "B01", "kind": "detail", "text": "Bambu P2S"}]))
    again = ideas.load(w, n)
    assert [(i["kind"], i["status"]) for i in again] == [("web", "no"), ("detail", "suggested")] and again[1]["id"] == "i5"


def test_a_yes_on_text_is_applied_by_the_next_cut_and_can_be_taken_back(tmp_path):
    r = make_project.build(cut=True, title="ideas text")
    w, n = r["work"], r["name"]
    ideas.import_found(w, n, answer(tmp_path, [{"beat": "B02", "kind": "correction", "text": "*wrong"}]))
    cutview.set_choice(w, n, "B02", "replace", "Use another take", 3.0, {"span": "spA"})
    ideas.set_status(w, n, "i1", "yes", text="*the tape SHIRT")
    v = views.review(w, n, "cut")
    assert sorted(x["kind"] for x in reviewnotes.open_notes(w, n, "cut")) == ["idea", "replace"]               # beside the clip's own choice
    assert v["ideas"][0]["status"] == "yes" and v["ideas"][0]["text"] == "*the tape SHIRT" and v["clips"] == []
    cutview.set_choice(w, n, "B03", "trim", "Trim", 6.0, {"cut_start": 0.5})                  # another clip's choice leaves the idea alone
    assert any(x.get("kind") == "idea" for x in reviewnotes.open_notes(w, n, "cut"))
    done = cutview.apply_choices(w, n)
    assert any(c.startswith("Showed “*the tape SHIRT” on screen at") for c in done["changes"])
    assert beat(r, "B02")["on_screen"]["text"][0] == {"text": "*the tape SHIRT", "kind": "correction", "at": 0.0, "dur": 3.0, "idea": "i1"}
    edit = cutview.edit_for(plan(r), str(r["dir"] / "footage"))
    assert [(o["seg"], o.get("card")) for o in edit["overlays"]] == [("B02", True)]                # the rough cut shows the text (no other graphics)
    j = reviewnotes.load(w, n)                                                                  # the cut was made: its choices are done
    for x in j["cut"]:
        x["status"] = "done"
    reviewnotes.save(w, n, j)
    ideas.set_status(w, n, "i1", "no")                                                          # taken back after the cut: a choice takes it out again
    out = cutview.apply_choices(w, n)
    assert out["changes"] == ["Took out the idea at 0:03 (*the tape SHIRT)"] and "text" not in beat(r, "B02")["on_screen"]


def test_a_yes_on_footage_puts_the_shot_over_the_clip(tmp_path):
    r = make_project.build(cut=True, title="ideas footage")
    w, n = r["work"], r["name"]
    library(r, {"take3.mp4": {"dur": 3.0, "samples": [{"t": 2.5, "subject": "end", "what": "the end"}]}})
    ideas.import_found(w, n, answer(tmp_path, [{"beat": "B01", "kind": "footage", "rel": "take3.mp4", "t": 2.5, "text": "the end card"}]))
    ideas.set_status(w, n, "i1", "yes")
    ideas.set_status(w, n, "i1", "suggested")                                                   # changed my mind before the cut: nothing to apply
    assert not [x for x in reviewnotes.open_notes(w, n, "cut") if x.get("kind") == "idea"]
    ideas.set_status(w, n, "i1", "yes")
    cutview.apply_choices(w, n)
    ins = beat(r, "B01")["on_screen"]["broll"][-1]
    assert ins == {"file": "take3.mp4", "in": 0.2, "dur": 2.8, "at": 0.0, "why": "Idea: the end card", "idea": "i1"}


def test_a_yes_on_a_shot_to_film_adds_a_pickup_and_a_no_removes_it(tmp_path):
    import shootplan
    r = make_project.build(cut=True, title="ideas film")
    w, n = r["work"], r["name"]
    ideas.import_found(w, n, answer(tmp_path, [{"beat": "B03", "kind": "film", "text": "the nozzle close up"}]))
    i = ideas.set_status(w, n, "i1", "yes")
    picks = shootplan.state(w, n)["pickups"]
    assert [p["what"] for p in picks] == ["the nozzle close up"] and picks[0]["lines"] == ["S03"] and i["pickup"] == picks[0]["id"]
    ideas.set_status(w, n, "i1", "no")
    assert shootplan.state(w, n)["pickups"] == []


def test_the_hosts_own_text_goes_on_the_clip_at_the_playhead():
    r = make_project.build(cut=True, title="ideas own")
    w, n = r["work"], r["name"]
    t = beat(r, "B02")["start"] + 1.0
    i = ideas.add_own(w, n, t, "*0.4 mm nozzle", "correction")
    assert i["beat"] == "B02" and i["at"] == 1.0 and ideas.load(w, n)[0]["status"] == "yes"
    assert [x["text"] for x in reviewnotes.open_notes(w, n, "cut")] == [f"Show “*0.4 mm nozzle” at {views.time_text(t)}"]
    with pytest.raises(ValueError):
        ideas.add_own(w, n, t, "   ")


def test_the_brief_lists_the_footage_but_not_the_takes(tmp_path):
    r = make_project.build(cut=True, title="ideas brief")
    w, n = r["work"], r["name"]
    library(r, {"take1.mp4": {"dur": 3, "samples": [{"t": 1, "subject": "host", "what": "the host talks"}]},
                "bench.mp4": {"dur": 30, "samples": [{"t": 1, "subject": "printer", "what": "a printer"}, {"t": 7, "subject": "printer bed", "what": "the bed"},
                                                     {"t": 13, "subject": "spool", "what": "a spool"}]}})
    prompt = ideas.find_prompt(w, n, tmp_path / "fd")
    assert (tmp_path / "fd" / "footage.txt").read_text(encoding="utf-8").splitlines() == ["bench.mp4 | 1-7 s | a printer | also: printer bed @ 7 s", "bench.mp4 | 13-13 s | a spool"]
    rows = json.loads((tmp_path / "fd" / "beats.json").read_text(encoding="utf-8"))
    assert {x["beat"]: x["has_broll"] for x in rows}["TP01"] is False and (tmp_path / "fd" / "ideas.md").is_file() and (tmp_path / "fd" / "script.md").is_file()
    assert "correction" in prompt and "at most 12 ideas" in prompt


def test_a_note_can_ask_for_text_on_screen():
    r = make_project.build(cut=True, title="ideas note text")
    t = beat(r, "B03")["start"] + 0.5
    got = noteactions.parse({"edits": [{"note": 1, "do": "text", "time": t, "text": "*0.4 mm"}, {"note": 1, "do": "text", "time": t, "text": " "}]}, {1})
    assert len(got) == 1
    done = noteactions.run(r["work"], r["name"], got, {}, log=lambda s: None)
    assert beat(r, "B03")["on_screen"]["text"] == [{"text": "*0.4 mm", "kind": "correction", "at": 0.5, "dur": 2.5}]
    assert done["by_note"][1][0].startswith("Showed “*0.4 mm” on screen")
