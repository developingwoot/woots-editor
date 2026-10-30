import cutreview
import loudness


def beat(i, rel, text, t0=0.0, dur=None):
    ws = [[w, round(t0 + k * 0.3, 2), round(t0 + k * 0.3 + 0.25, 2)] for k, w in enumerate(text.split())]
    end = ws[-1][2]
    return {"id": i, "dur": dur or end - t0, "said": text, "aroll": {"rel": rel, "words": ws, "keep": [[t0, end]]}}


def test_a_sentence_that_stops_mid_thought_is_found_and_a_finished_one_is_not():
    data = {"beats": [beat("B01", "x.mkv", "One of them I had to use AI to even get it to"), beat("B02", "x.mkv", "It took me an hour to model the part.")]}
    got = cutreview.dangling(data)
    assert [d["text"] for d in got] == ["One of them I had to use AI to even get it to"]


def test_the_opening_is_measured_against_the_hook_budget():
    data = {"beats": [beat("H01", "Outro_2.mkv", "I hated it " * 3, dur=10.0), beat("B01", "Intro_3.mkv", "If you ask people they say many things", dur=40.0),
                      beat("B02", "Tinkercad.mkv", "First up is Tinkercad", dur=20.0)]}
    hb = cutreview.hook_budget(data, 30.0)
    assert hb == {"cold_open_s": 10.0, "intro_s": 40.0, "intro_allowed_s": 20.0}
    assert [s.get("part") for s in cutreview.sentences(data)] == ["intro", None]


def test_every_piece_of_a_recording_gets_the_same_gain_from_one_measure():
    assert loudness.gain_for(-22.0) == 6.0 and loudness.gain_for(-10.0) == -6.0
    assert loudness.gain_for(-60.0) is None and loudness.gain_for(None) is None
    assert loudness.gain_for(-50.0) == loudness.MAX_GAIN


def test_the_rule_checker_finds_a_short_shot_a_close_framing_change_and_a_long_opening():
    import cutcheck
    rules = {"min_piece_s": 3.0, "beat_max_s": 30.0, "punch_hold_s": 15.0, "cold_open_max_s": 15.0, "hook_total_s": 30.0, "repeat_phrase_words": 4,
             "repeat_phrase_within_words": 40, "repeat_phrase_within_s": 20.0, "max_pause_s": 0.5}
    a = beat("B01", "Tinkercad.mkv", "so this is the first program we try today", dur=40.0)
    a["start"] = 40.0
    a["on_screen"] = {"broll": [{"file": "T/x.mp4", "at": 5.0, "dur": 6.0}], "punch": {"zooms": [1.0], "cy": 0.4}}
    b = beat("B02", "Tinkercad.mkv", "and then we did one more thing", dur=20.0)
    b["start"] = 80.0
    b["on_screen"] = {"broll": [], "punch": {"zooms": [1.3], "cy": 0.4}}        # framing changes 1 s after the cutaway ended? no: 29 s later; see the cold open instead
    h = beat("H01", "Outro_2.mkv", "I hated it", dur=20.0)
    h["start"] = 0.0
    rows = {r["rule"]: r for r in cutcheck.check({"beats": [h, a, b]}, rules)}
    assert not rows["cold open at most cold_open_max_s"]["ok"] and not rows["content starts by hook_total_s"]["ok"]
    assert rows["no shot under min_piece_s"]["ok"] and rows["framing changes at least punch_hold_s apart"]["ok"]
    a["on_screen"]["broll"] = [{"file": "T/x.mp4", "at": 39.0, "dur": 6.0}]       # a cutaway ending 1 s before the next beat's framing change
    b["start"] = 80.0 - 36.0 + 1.0
    rows = {r["rule"]: r for r in cutcheck.check({"beats": [h, a, b]}, rules)}
    assert not rows["no shot under min_piece_s"]["ok"]


def test_silences_left_in_the_cut_are_read_from_the_sound_of_each_recording():
    import cutcheck
    ws = [["a", 1.0, 1.2]]
    data = {"beats": [{"id": "B01", "start": 0.0, "dur": 9.0, "aroll": {"rel": "x.mkv", "in": 0, "out": 12, "words": ws, "keep": [[0.0, 5.0], [6.0, 12.0]]}}]}
    cache = {"x.mkv": {"silences": [[2.0, 3.2], [4.5, 5.0], [6.0, 6.4]]}}          # 1.2 s inside the first piece; 0.5 s at its end and 0.4 s at the start of the next = a 0.9 s join
    got = cutcheck.silences_in_cut(data, cache)
    assert (2.0, 1.2) in got and any(abs(t - 5.0) < 0.01 and abs(d - 0.9) < 0.01 for t, d in got)


def test_a_stumbled_start_of_one_or_two_words_is_cut_off():
    data = {"beats": [beat("B01", "x.mkv", "Until next time. I'm sorry. I'")]}
    assert [d["text"] for d in cutreview.dangling(data)] == ["I'"]
