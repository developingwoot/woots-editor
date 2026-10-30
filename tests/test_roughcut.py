import roughcut as rc


def w(start, end):
    return {"start": start, "end": end}


def test_norm_strips_punctuation_and_case():
    assert rc.norm("Hello, World! It's me.") == ["hello", "world", "it's", "me"]


def test_speech_spans_split_on_long_pauses():
    words = [w(0, 1), w(1.2, 2), w(5, 6)]
    assert rc.speech_spans(words, 1.0) == [[0, 2], [5, 6]]


def test_subtract_cuts_the_middle_and_keeps_both_sides():
    assert rc.subtract([(0, 10)], [{"start": 3, "end": 5}]) == [(0, 3), (5, 10)]


def test_subtract_ignores_drops_outside_and_removes_covered_keeps():
    assert rc.subtract([(0, 2)], [{"start": 5, "end": 6}]) == [(0, 2)]
    assert rc.subtract([(1, 2)], [{"start": 0, "end": 3}]) == []


def test_find_retakes_flags_a_restart_and_ignores_distinct_lines():
    segs = [{"start": 0, "end": 3, "text": "So today we are building a whale shark"},
            {"start": 4, "end": 8, "text": "So today we are building a flexi toy"}]
    assert len(rc.find_retakes(segs)) == 1
    segs[1]["text"] = "Next the gear train needs work"
    assert rc.find_retakes(segs) == []
    segs[1]["text"] = "So today we are building a whale shark"
    segs[1]["start"] = 100   # outside the window
    assert rc.find_retakes(segs) == []
