import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import recut  # noqa: E402
import shotmatch  # noqa: E402


def words_of(text, t0=0.0, step=0.3):
    return [[w, round(t0 + i * step, 2), round(t0 + i * step + 0.25, 2)] for i, w in enumerate(text.split())]


def an(text, dur=None):
    w = words_of(text)
    return {"dur": dur or w[-1][2] + 1, "words": len(w), "list": w}


def test_numbered_takes_are_a_series_and_other_names_are_not():
    assert recut.series_of("Intro_3.mkv") == ("intro", 3)
    assert recut.series_of("Plasticity 2.mkv") == ("plasticity", 2)
    assert recut.series_of("Blender.mkv") == ("blender", 1)
    assert recut.series_of("2026-07-31 04-37-22.mkv") == ("20260731043722", 1)      # a time stamp is not a take number


def test_a_talking_recording_has_enough_words_said_at_speaking_pace():
    assert recut.is_talking(an(" ".join(["word"] * 80), dur=60))
    assert not recut.is_talking(an(" ".join(["word"] * 30), dur=20))                    # too few
    assert not recut.is_talking(an(" ".join(["word"] * 80), dur=600))                   # a long screen recording with some talk


def test_the_latest_of_a_numbered_series_is_used_and_different_things_are_all_kept():
    base = "the baseline tinkercad scraper holder keep going on about shapes and blocks because it is easy to learn for anyone who has never modeled before at all "
    other = "onshape runs in the browser with parametric sketches constraints and a full history tree which makes changing a dimension simple and reliable every time "
    analysis = {"Intro_1.mkv": an(base * 3), "Intro_2.mkv": an(base * 3 + "more"), "Onshape.mkv": an(other * 3), "Blender.mkv": an("blender sculpting meshes vertices modifiers " * 12)}
    use, left = recut.choose_recordings(analysis, {}, {"Intro_1.mkv": -1, "Intro_2.mkv": -1, "Onshape.mkv": 5, "Blender.mkv": 9}, 30)
    assert use == ["Blender.mkv", "Intro_2.mkv", "Onshape.mkv"]
    assert [x["rel"] for x in left] == ["Intro_1.mkv"] and "Intro_2.mkv" in left[0]["why"]


def test_two_numbered_recordings_about_different_places_are_both_kept():
    a = an("alpha beta gamma delta epsilon zeta " * 14)
    b = an("one two three four five six seven eight " * 11)
    use, _ = recut.choose_recordings({"Part 1.mkv": a, "Part 2.mkv": b}, {}, {"Part 1.mkv": 2, "Part 2.mkv": 20}, 30)
    assert use == ["Part 1.mkv", "Part 2.mkv"]


def test_a_stumble_said_again_is_cut_and_the_later_one_stays():
    text = "bottom line nomad is great i thoroughly enjoyed just spending a few little i thoroughly enjoyed just spending a few hours with it"
    w = words_of(text)
    drop = recut.repeated_phrase_drops(w)
    kept = " ".join(x[0] for i, x in enumerate(w) if i not in drop)
    assert kept == "bottom line nomad is great i thoroughly enjoyed just spending a few hours with it"


def test_a_phrase_far_away_is_not_a_stumble():
    far = "next up on the list is blender " + " ".join(f"filler{i} word{i} more{i} text{i}" for i in range(10)) + " " + "next up on the list is freecad"
    assert recut.repeated_phrase_drops(words_of(far)) == set()


def test_a_retake_after_a_pause_replaces_the_short_attempts_before_it():
    a = words_of("and if i'm doing something for cad", 67.8)
    b = words_of("anything i use", 71.0)
    c = words_of("and if i'm doing something with cad i'm sorry but it is not my choice", 80.2)
    parts = recut.cleaned(a + b + c)
    assert len(parts) == 1 and parts[0][0][0] == len(a) + len(b)


def test_dead_air_splits_a_stretch_into_stretches_of_at_least_three_seconds():
    long_a = words_of("one two three four five six seven eight nine ten eleven twelve", 0.0)
    long_b = words_of("alpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu", 20.0)
    assert len(recut.cleaned(long_a + long_b)) == 2
    short = words_of("one two three four", 0.0) + words_of("five six seven eight", 10.0)           # 1 s each: not a stretch of its own, joined
    assert len(recut.cleaned(short)) == 1


def test_a_silence_over_the_limit_is_cut_out_and_a_short_one_stays():
    w = words_of("one two three four five six", 0.0) + words_of("seven eight nine ten", 2.15) + words_of("eleven twelve thirteen", 5.1)
    (_, keep), = recut.cleaned(w)
    assert len(keep) == 2                                            # the 2 s silence is cut, the 0.4 s one is not
    assert keep[1][0] - keep[0][1] > 1.0


def test_a_sentence_said_again_in_other_words_goes_but_the_opener_stays():
    w = words_of("First up on the list is Tinkercad and the scraper. ", 0.0)         + words_of("Without any tutorials whatsoever I designed the scraper in about twenty minutes which is fantastic. ", 4.0)         + words_of("When you consider in twenty minutes I had a functional part that is fantastic. ", 12.0)         + words_of("That said it has no sketch constraint engine at all.", 20.0)
    drop = recut.repeated_sentence_drops(w)
    kept = " ".join(x[0] for i, x in enumerate(w) if i not in drop)
    assert kept.startswith("First up on the list is Tinkercad") and "functional part" in kept and "tutorials" not in kept and "constraint engine" in kept


def test_the_intro_goes_first_and_the_outro_last_the_rest_by_the_line_they_fit():
    lines = [{"id": "S01", "said": "welcome to the benchmark of cad programs", "heading": "A"},
             {"id": "S02", "said": "tinkercad is the baseline for beginners", "heading": "B"},
             {"id": "S03", "said": "fusion has a timeline and costs money", "heading": "C"},
             {"id": "S04", "said": "recap every program in a tier list tinkercad fusion", "heading": "D"}]
    like = recut.Likeness([ln["said"] for ln in lines])
    t = {"list": words_of("tinkercad is the baseline for beginners okay")}
    f = {"list": words_of("fusion has a timeline it costs money")}
    assert recut.position_of("Intro_1.mkv", t, lines, like)[0] == -1.0
    assert recut.position_of("Outro_1.mkv", t, lines, like)[0] == 5.0
    assert recut.position_of("Tinkercad.mkv", t, lines, like)[0] == 1.0         # the earliest line nearly as good, not the recap
    assert recut.position_of("Fusion.mkv", f, lines, like)[0] == 2.0


def test_broll_of_another_program_is_not_put_over_a_beat_that_names_one(monkeypatch):
    import json
    sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures"))
    import beatmap
    import brolllib
    import make_project
    if not make_project.have_ffmpeg():
        return
    monkeypatch.setattr(recut, "MIN_WORDS", 5)
    monkeypatch.setattr(recut, "MIN_PIECE_S", 1.0)
    r = make_project.build_footage("rc program")
    w, n = r["work"], r["name"]
    recut.build_beats(w, n)
    bp = beatmap.path_of(w, n)
    data = json.loads(bp.read_text(encoding="utf-8"))
    line = recut.spoken_lines(w, n)[0]
    data["beats"][0]["said"] = line["said"] + " shapr3d"
    bp.write_text(json.dumps(data), encoding="utf-8")
    brolllib.paths(w, n)[1].write_text(json.dumps({"clips": {"Fusion/a.mp4": {}, "Shapr3D/b.mp4": {}}}), encoding="utf-8")
    rows = [{"key": "k", "speech": line["id"]}]
    fusion = {"k": {"chosen": {"rel": "Fusion/a.mp4", "t": 0, "dur": 20, "what": "x"}}}
    assert recut.place_broll(w, n, fusion, rows) == 0
    right = {"k": {"chosen": {"rel": "Shapr3D/b.mp4", "t": 0, "dur": 20, "what": "x"}}}
    assert recut.place_broll(w, n, right, rows) == 1


def test_long_beats_without_a_cutaway_get_the_programs_own_screen_recording(monkeypatch):
    import json
    sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures"))
    import beatmap
    import brolllib
    import make_project
    if not make_project.have_ffmpeg():
        return
    monkeypatch.setattr(recut, "MIN_WORDS", 5)
    monkeypatch.setattr(recut, "MIN_PIECE_S", 1.0)
    monkeypatch.setattr(recut, "BROLL_MIN_BEAT_S", 1.0)
    r = make_project.build_footage("rc cover")
    w, n = r["work"], r["name"]
    recut.build_beats(w, n)
    bp = beatmap.path_of(w, n)
    data = json.loads(bp.read_text(encoding="utf-8"))
    data["beats"][0]["said"] += " fusion"
    bp.write_text(json.dumps(data), encoding="utf-8")
    sample = lambda t: {"t": t, "kind": "screen recording", "sharp": True}
    clips = {"Fusion/a.mp4": {"dur": 100, "samples": [sample(10), sample(40), sample(70)]},
             "Shapr3D/b.mp4": {"dur": 100, "samples": [sample(5)]}, "Fusion.mkv": {"dur": 50, "samples": [{"t": 1, "kind": "real footage"}]}}
    brolllib.paths(w, n)[1].write_text(json.dumps({"clips": clips}), encoding="utf-8")
    assert recut.cover_with_footage(w, n) >= 1
    first = json.loads(bp.read_text(encoding="utf-8"))["beats"][0]["on_screen"]["broll"]
    assert first and first[0]["file"] == "Fusion/a.mp4" and first[0]["dur"] >= recut.MIN_PIECE_S
    assert recut.cover_with_footage(w, n) == 0                                  # a beat that has a cutaway is left alone


def test_the_numbers_come_from_the_skill_and_a_broken_file_falls_back(tmp_path, monkeypatch):
    import skillrules
    d = tmp_path / "youtube-edit"
    d.mkdir()
    (d / "rough-cut.json").write_text('{"min_piece_s": 5, "beat_max_s": -1, "nonsense": 9, "min_words": true}', encoding="utf-8")
    monkeypatch.setattr(skillrules, "SKILLS", tmp_path)
    r = skillrules.rules()
    assert r["min_piece_s"] == 5.0 and r["beat_max_s"] == skillrules.DEFAULTS["beat_max_s"] and "nonsense" not in r and r["min_words"] == 60
    monkeypatch.delenv("WOOTS_MIN_PIECE", raising=False)
    try:
        recut.reload_rules()
        assert recut.MIN_PIECE_S == 5.0
    finally:
        monkeypatch.undo()
        recut.reload_rules()
    (d / "rough-cut.json").write_text("not json", encoding="utf-8")
    monkeypatch.setattr(skillrules, "SKILLS", tmp_path)
    assert skillrules.rules() == skillrules.DEFAULTS
    fd = tmp_path / "run"
    (d / "rough-cut.md").write_text("rules", encoding="utf-8")
    assert skillrules.copy_into(fd, ("youtube-edit/rough-cut.md", "youtube-edit/missing.md")) == ["rough-cut.md"] and (fd / "rough-cut.md").read_text() == "rules"


def test_a_fragment_between_stumbles_goes_a_long_stretch_is_split_at_a_pause_and_a_segue_stays():
    stumble = words_of("and if i'm doing something for cad", 0.0)
    frag = words_of("anything i use", 3.0)                                    # 1 s fragment
    tail = words_of("and if i'm doing something with cad i'm sorry but it is not my choice at all really", 6.0)
    parts = recut.cleaned(stumble + frag + tail)
    assert len(parts) == 1 and parts[0][0][0] == len(stumble) + len(frag)
    seg = words_of("first up on the list is tinkercad", 0.0)                   # a short segue after a stumble
    assert recut.SEGUE.search("first up on the list")
    long_text = " ".join(f"w{i}" for i in range(120))
    w = words_of(long_text, 0.0, 0.3)
    for k in range(60, 120):                                                  # a pause in the middle
        w[k][1] += 1.0
        w[k][2] += 1.0
    pieces = recut.split_long(w, list(range(len(w))))
    assert len(pieces) >= 2 and all(w[p[-1]][2] - w[p[0]][1] <= recut.CHUNK_MAX + 1 for p in pieces[:-1])


def test_a_word_said_twice_and_a_scrap_left_beside_a_cut_go():
    w = words_of("it was a lot of work work and then we left", 0.0)
    assert recut.stammer_drops(w, set()) == {5}                              # the first copy goes
    scrap = words_of("we stopped there", 0.0) + words_of("work.", 3.0) + words_of("and one was a complete disaster", 4.0)
    assert recut.stammer_drops(scrap, {0, 1, 2}) == {3}                  # one word left between the cut words and a pause


def test_program_names_are_found_as_they_sound_and_a_passage_stays_on_the_program_introduced():
    known = {"tinkercad", "shapr3d", "onshape", "fusion"}
    assert shotmatch.named_programs("next up is shaper 3D and it is great", known) == {"shapr3d"}
    assert shotmatch.named_programs("on shape is my daily driver", known) == {"onshape"}
    beats = [{"id": "B01", "aroll": {"rel": "TinkerCAD.mkv"}, "said": "First up on our list is Tinkercad."},
             {"id": "B02", "aroll": {"rel": "TinkerCAD.mkv"}, "said": "Next up on the list is Shaper 3D. Now before this video I had not touched it. It is best described as Tinkercad with more."},
             {"id": "B03", "aroll": {"rel": "TinkerCAD.mkv"}, "said": "I was able to model the part in 20 minutes with direct modeling."},
             {"id": "B04", "aroll": {"rel": "Onshape.mkv"}, "said": "It is my daily driver."},
             {"id": "B05", "aroll": {"rel": "Fusion.mkv"}, "said": "Compared with Onshape and Tinkercad it costs money."}]
    got = recut.beat_programs(beats, known)
    assert [got[i] for i in ("B01", "B02", "B03", "B04")] == ["tinkercad", "shapr3d", "shapr3d", "onshape"]
    assert got["B05"] == "fusion"                                         # names two others in passing: stays on its own program


def test_the_zoom_alternates_and_keeps_the_eyes_on_one_line():
    import framing
    import sectionrender
    z = framing.ZOOM
    assert framing.plan_zoom([(0, 5, False), (5, 10, True), (10, 14, False)], 15, 40) == [1.0, z, z]            # zoomed on the intense piece, held (no change a few seconds later)
    assert framing.plan_zoom([(0, 20, False), (20, 25, True), (25, 30, False), (30, 40, True), (40, 50, False)], 15, 40) == [1.0, z, z, z, 1.0]
    flat = [(i * 10, i * 10 + 10, False) for i in range(8)]
    got = framing.plan_zoom(flat, 15, 40)
    assert got[0] == 1.0 and z in got[4:]                                          # flat for 40 s, then one zoom
    changes = [i for i in range(1, 8) if got[i] != got[i - 1]]
    assert all(b - a >= 2 for a, b in zip(changes, changes[1:]))                  # never two changes within 15 s
    z, ey = framing.ZOOM, 0.37
    f = sectionrender.base_filter(1920, 1080, 30, z, 0.5, ey)
    top = (1080 - 1080 / z) * ey                                   # the crop's top edge, in pixels, from the filter's own formula
    assert "y=(in_h-out_h)*0.37" in f
    assert abs((ey * 1080 - top) * z - ey * 1080) < 0.01          # the eyes are on the same line of the screen zoomed or not


def test_a_short_recording_that_retakes_the_start_of_a_long_one_is_left_out(monkeypatch):
    monkeypatch.setattr(recut, "MIN_WORDS", 5)
    long_text = ("i have been running mainsail for years and watch the fluidd repository they both run moonraker and klipper so this test is purely about usability "
                 "the first thing was screen real estate fluidd gives four columns while mainsail gives three and the console hyperlinks commands the gcode viewer is two dimensional "
                 "editing config files is different and i write a lot of code so commenting out lines matters and my decision is to set up new printers with fluidd")
    short_text = "i have been running mainsail for a year and watch the fluidd repository they both run moonraker and klipper so this test is purely about usability"
    other_text = "tinkercad is where beginners start with simple shapes and a grid workplane that snaps while onshape lives in the browser with parametric sketches and a feature tree and cloud documents"
    analysis = {"a long.mkv": an(long_text * 1), "b retake.mkv": an(short_text), "c other.mkv": an(other_text)}
    keep, left = recut.choose_recordings(analysis, {}, None, 0)
    assert "a long.mkv" in keep and "c other.mkv" in keep and "b retake.mkv" not in keep
    assert any(x["rel"] == "b retake.mkv" for x in left)


def test_a_clip_named_for_what_the_beat_is_about_goes_over_it(monkeypatch):
    assert recut.clip_name_words("B Roll/GCodeViewer.mkv") == "g code viewer"
    assert recut.clip_name_words("B Roll/Editing Config Both.mkv") == "editing config both"
    like = recut.Likeness(["now the g-code viewer is where mainsail excels with a three dimensional model", "the console hyperlinks commands", "g code viewer", "console", "editing config both"])
    beat = like.vec("now the g-code viewer is where mainsail excels with a three dimensional model")
    assert like.cos(beat, like.vec("g code viewer")) > recut.NAME_MIN_LIKE > like.cos(beat, like.vec("editing config both"))


def test_a_clean_restart_of_a_whole_passage_replaces_every_earlier_attempt():
    """Sam 2026-10-30: told three times (a rough start, a stumble, then the clean telling that begins again like the first), the clean telling is the one that stays, all of it."""
    w = (words_of("Now the widget panel viewer I must say this is one area where the product shines. ", 0.0)
         + words_of("It has a flexible grid and you can pick any layout on your ", 6.0)
         + words_of("and you can pick any layout on your device and be able to resize. ", 12.0)
         + words_of("The widget panel viewer is an area where the product really shines. ", 18.0)
         + words_of("It has a flexible grid for everything. ", 24.0)
         + words_of("You can pick any layout on your device. ", 28.0)
         + words_of("That said it has no export at all.", 32.0))
    drop = recut.repeated_phrase_drops(w)
    kept = " ".join(x[0] for i, x in enumerate(w) if i not in drop)
    assert kept.startswith("The widget panel viewer is an area") and "Now the widget" not in kept and "be able to resize" not in kept
    assert "flexible grid for everything" in kept and "no export" in kept


def test_a_stumble_inside_one_sentence_still_goes_without_touching_what_came_before():
    w = (words_of("First up is the baseline program for beginners. ", 0.0) + words_of("And if I am doing something for design anything I use I will use this one. ", 5.0)
         + words_of("And if I am doing something with design I am sorry I will use this one every day. ", 12.0))
    drop = recut.repeated_phrase_drops(w)
    kept = " ".join(x[0] for i, x in enumerate(w) if i not in drop)
    assert kept.startswith("First up is the baseline") and kept.count("And if I am doing something") == 1
