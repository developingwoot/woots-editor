import json

import beatmap
import clipmap
import coldopen
import cutreview
import takes


def beat(i, rel, text, t0=0.0):
    ws = [[w, round(t0 + k * 0.3, 2), round(t0 + k * 0.3 + 0.25, 2)] for k, w in enumerate(text.split())]
    end = ws[-1][2]
    return {"id": i, "dur": end - t0, "said": text, "aroll": {"rel": rel, "words": ws, "keep": [[t0, end]], "in": t0, "out": end, "dur": end - t0}}


TAKE1 = ["The first thing that jumped out of me was screen real estate.", "Mainsail only gives you three columns on the dashboard.", "Fluidd actually gives you four."]
TAKE2 = ["The first thing that jumped out at me on the dashboard was four columns.", "So it uses more of the screen real estate that is available.", "Mainsail gives three, Fluidd gives four."]
OTHER = ["The console immediately caught my eye.", "You can click a command and it runs.", "Nothing like that exists in Mainsail.", "The viewer is different too.", "It builds the model in three dimensions.", "Fluidd only shows top down."]


def cut_of(texts):
    return {"beats": [beat(f"B{k + 1:02d}", "long.mkv", t, t0=10.0 * k) for k, t in enumerate(texts)]}


def test_paraphrased_takes_of_one_passage_are_found_as_candidates():
    sents = cutreview.sentences(cut_of(TAKE1 + OTHER + TAKE2))
    got = takes.candidates(sents)
    assert got and got[0]["a"][0] == "B01.1" and got[0]["b"][0] == "B10.1"


def test_a_cut_with_no_repeated_passage_has_no_candidates():
    assert takes.candidates(cutreview.sentences(cut_of(TAKE1 + OTHER))) == []


def test_the_best_take_stays_the_others_go_and_a_kept_sentence_survives(tmp_path):
    import config
    work = "zz-takes"
    (config.WORK / work).mkdir(parents=True, exist_ok=True)
    data = cut_of(TAKE1 + OTHER + TAKE2)
    clipmap.write_json(beatmap.path_of(work, work), data)
    (tmp_path / "t.json").write_text(json.dumps({"groups": [{"topic": "screen real estate", "takes": [["B01.1", "B02.1", "B03.1"], ["B10.1", "B11.1", "B12.1"]], "best": 1,
                                                             "use": ["B10.1", "B11.1", "B12.1", "B02.1"], "why": "clearer"}, {"topic": "bad", "takes": [["B04.1"], ["B09.1"]]}]}), encoding="utf-8")
    ok, msg = takes.apply_review(work, work, tmp_path / "t.json")
    assert ok and takes.load(work, work)["v"] == takes.VERSION and len(takes.load(work, work)["groups"]) == 2
    texts = [d["text"] for d in takes.drops(work, work)]
    assert TAKE1[0] in texts and TAKE1[2] in texts and TAKE1[1] not in texts and not any(t in texts for t in TAKE2)      # the kept sentence of the other take stays
    assert takes.choose(work, work, 0, 0)["groups"][0]["best"] == 0
    assert TAKE2[0] in [d["text"] for d in takes.drops(work, work)]


def test_a_take_of_non_consecutive_sentences_is_ignored(tmp_path):
    import config
    work = "zz-takes2"
    (config.WORK / work).mkdir(parents=True, exist_ok=True)
    clipmap.write_json(beatmap.path_of(work, work), cut_of(TAKE1 + OTHER + TAKE2))
    (tmp_path / "t.json").write_text(json.dumps({"groups": [{"topic": "x", "takes": [["B01.1", "B03.1"], ["B10.1"]], "best": 1}]}), encoding="utf-8")
    takes.apply_review(work, work, tmp_path / "t.json")
    assert takes.load(work, work)["groups"] == []


def test_the_opening_is_read_to_claude_and_a_strong_one_means_no_cold_open(tmp_path):
    import config
    work = "zz-cold-skip"
    (config.WORK / work).mkdir(parents=True, exist_ok=True)
    data = cut_of(TAKE1 + OTHER)
    clipmap.write_json(beatmap.path_of(work, work), data)
    assert coldopen.opening(data).startswith("The first thing that jumped")
    (tmp_path / "h.json").write_text(json.dumps({"options": [], "skip": True, "why": "it asks the question at once"}), encoding="utf-8")
    ok, _ = coldopen.apply_options(work, work, tmp_path / "h.json")
    assert ok and coldopen.load(work, work)["skip"] is True and coldopen.insert(work, work) == 0


def test_a_sentence_that_only_builds_on_an_earlier_one_stays_but_one_said_again_at_once_goes():
    import recut
    from test_recut import words_of
    build = (words_of("And this is because Fluid actually hyperlinks commands in the console. ", 0.0) + words_of("So if it tells you run save config you can click on that. ", 5.0)
             + words_of("This is not a feature of Mainsail at all. ", 10.0) + words_of("Fluid hyperlinks a lot of stuff in the console for you. ", 14.0))
    assert not recut.repeated_sentence_drops(build)                                  # a later sentence with some of the same words, two sentences on: it builds on the first
    again = words_of("First up is Tinkercad and the scraper. ", 0.0) + words_of("I designed the scraper in about twenty minutes which is fantastic. ", 5.0) + words_of("In twenty minutes I had a functional part that is fantastic. ", 12.0)
    assert recut.repeated_sentence_drops(again)                                      # the next sentence says it again


def test_a_dull_page_of_text_is_not_a_cutaway_unless_the_sentence_is_about_it():
    import recut
    shot = {"file": "B Roll/Fluidd Repository.mkv", "why": "A screen recording showing a GitHub repository page"}
    assert recut.is_dull(shot, {"said": "Mainsail is continually being developed as well."})
    assert not recut.is_dull(shot, {"said": "I watched the Fluidd repository on GitHub."})
    assert not recut.is_dull({"file": "B Roll/Fluidd Dashboard.mkv", "why": "a printer dashboard"}, {"said": "anything"})


def test_a_face_left_of_centre_is_centred_by_the_punch_in_crop():
    import framing
    assert framing.centre_crop(0.38, 1.3) == 0.0                                      # the left edge of the crop is the left edge of the picture: the face lands in the middle
    assert framing.centre_crop(0.5, 1.3) == 0.5 and framing.centre_crop(0.9, 1.3) == 1.0 and framing.centre_crop(0.3, 1.0) == 0.5


def test_a_left_out_sentence_that_sets_up_a_later_one_can_be_brought_back(tmp_path):
    import config
    import cutreview
    work = "zz-restore"
    (config.WORK / work).mkdir(parents=True, exist_ok=True)
    ws = [[w, round(0.3 * k, 2), round(0.3 * k + 0.25, 2)] for k, w in enumerate("The console now links every command you see. I think Mainsail left it out on purpose. Stuff you should not click on.".split())]
    end = ws[-1][2]
    first = [w for w in ws if w[0] == "purpose."][0]
    keep = [[ws[0][1], ws[7][2]], [[w for w in ws if w[0] == "Stuff"][0][1], end]]            # the middle sentence is left out
    data = {"beats": [{"id": "B01", "dur": 4.0, "start": 0.0, "said": "x", "aroll": {"rel": "r.mkv", "words": ws, "keep": keep, "in": 0, "out": end, "dur": 4.0}}]}
    clipmap.write_json(beatmap.path_of(work, work), data)
    gone = cutreview.sentences(data, with_left_out=True)
    left = [s for s in gone if s.get("left_out")]
    assert len(left) == 1 and left[0]["id"] == "B01.L1" and left[0]["text"].startswith("I think Mainsail")
    (tmp_path / "r.json").write_text(json.dumps({"restore": [{"ids": ["B01.L1", "B01.1"], "for": "B01.3", "why": "says why"}]}), encoding="utf-8")
    cutreview.apply_review(work, work, tmp_path / "r.json")
    assert [r["text"][:12] for r in cutreview.load(work, work)["restores"]] == ["I think Main"]
    cutreview.apply(work, work, 0.5, 0.3, 0.1)
    back = json.loads(beatmap.path_of(work, work).read_text(encoding="utf-8"))["beats"][0]
    assert "left it out on purpose" in back["said"] and first


def test_the_cut_is_compared_with_the_video_user_published():
    import benchmark
    pub = ["I think Mainsail probably left this out because it hyperlinks a lot of stuff.", "It is a convenience for a power user.", "Until next time."]
    cut = ["It is a convenience for a power user.", "Until next time.", "Keep thinking about things."]
    r = benchmark.compare(pub, cut)
    assert r["missing"] == [pub[0]] and r["extra"] == [cut[2]] and r["found_share"] == 0.67


def test_a_splice_from_another_take_needs_enough_words_and_the_last_take_is_the_default(tmp_path):
    import config
    work = "zz-splice"
    (config.WORK / work).mkdir(parents=True, exist_ok=True)
    texts = ["Fluidd gives you four columns on the dashboard.", "Short bit.", "That is a nice thing to have at a glance.", "Other things happen in between here for a while.",
             "More filler words fill the gap between the takes now.", "The dashboard in Fluidd has four columns for everything.", "It is really nice at a glance.",
             "Console links are next on the list today.", "They run commands for you.", "That is a power user feature.", "Mainsail does not have it at all."]
    clipmap.write_json(beatmap.path_of(work, work), cut_of(texts))
    (tmp_path / "t.json").write_text(json.dumps({"groups": [{"topic": "columns", "takes": [["B01.1", "B02.1", "B03.1"], ["B06.1", "B07.1"]],
                                                             "use": ["B06.1", "B07.1", "B02.1"], "why": "later is clearer"}]}), encoding="utf-8")
    takes.apply_review(work, work, tmp_path / "t.json")
    g = takes.load(work, work)["groups"][0]
    assert g["best"] == 1 and g["use"] == [texts[5], texts[6]]                           # "Short bit." is two words: too short to splice in
    dropped = [d["text"] for d in takes.drops(work, work)]
    assert texts[0] in dropped and texts[1] in dropped and texts[5] not in dropped


def test_the_take_chosen_to_play_is_not_dropped_again_by_the_read_of_the_cut(tmp_path):
    import config
    work = "zz-guard"
    (config.WORK / work).mkdir(parents=True, exist_ok=True)
    texts = ["The first thing that jumped out at me was four columns.", "It clips long text sometimes.", "Something else happens next here."]
    clipmap.write_json(beatmap.path_of(work, work), cut_of(texts))
    (tmp_path / "t.json").write_text(json.dumps({"groups": [{"topic": "columns", "takes": [["B01.1"], ["B02.1"]], "best": 0}]}), encoding="utf-8")
    takes.apply_review(work, work, tmp_path / "t.json")
    (tmp_path / "r.json").write_text(json.dumps({"drops": [{"id": "B01.1", "kind": "repeat", "why": "x"}, {"id": "B03.1", "kind": "repeat", "why": "y"}]}), encoding="utf-8")
    cutreview.apply_review(work, work, tmp_path / "r.json")
    assert [d["text"] for d in cutreview.load(work, work)["drops"]] == [texts[2]]
