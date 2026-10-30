import pytest

import beatmap as bm
import workflow

W = [["a", 0.0, 0.5], ["b", 0.6, 1.0], ["c", 1.1, 1.5], ["d", 5.0, 5.4]]


def ranges(got, want):
    assert len(got) == len(want), got
    for (a, b), (c, d) in zip(got, want):
        assert a == pytest.approx(c) and b == pytest.approx(d)


def test_keep_from_idx_adds_breath_but_not_before_time_zero():
    ranges(bm.keep_from_idx(W, [0, 1, 2]), [[0.0, 1.68]])


def test_keep_from_idx_splits_on_dead_air():
    ranges(bm.keep_from_idx(W, [0, 1, 2, 3]), [[0.0, 1.68], [4.92, 5.58]])


def test_keep_from_idx_gives_no_breath_next_to_a_cut_word():
    w = [["a", 0.0, 1.0], ["b", 1.1, 2.0], ["c", 2.1, 3.0]]
    ranges(bm.keep_from_idx(w, [1]), [[1.1, 2.0]])


def test_kept_flags_and_text():
    keep = [[0.0, 1.68]]
    assert bm.kept_flags(W, keep) == [True, True, True, False]
    assert bm.kept_text(W, keep) == "a b c"


def beat(i, dur, skip=False, graphic=None):
    return {"id": i, "dur": dur, "skip": skip, "graphic": graphic, "on_screen": {"shot": "a-roll", "broll": []},
            "audio": {}, "aroll": {}}


def test_retime_is_cumulative_and_skips_do_not_advance_time():
    beats = [beat("B1", 10), beat("B2", 5, skip=True), beat("B3", 7)]
    bm.retime(beats)
    assert [(b["start"], b["end"]) for b in beats] == [(0.0, 10.0), (10.0, 10.0), (10.0, 17.0)]


def test_graphic_kinds():
    assert bm.is_card({"kind": "title"}) and bm.is_card({"kind": "end"})
    assert bm.is_popup({"kind": "stamp"}) and not bm.is_card({"kind": "stamp"})
    assert bm.is_explainer({"kind": "gears"})
    assert not bm.is_explainer({"kind": "title"}) and not bm.is_explainer(None)


def test_struck_or_skipped_graphics_are_not_live():
    g = {"kind": "gears"}
    assert bm.live_graphic(beat("B", 5, graphic=g)) is g
    assert bm.live_graphic(beat("B", 5, graphic={**g, "struck": True})) is None
    assert bm.live_graphic(beat("B", 5, skip=True, graphic=g)) is None


def test_stats_budget_counts_only_explainers():
    beats = [beat("B1", 60, graphic={"kind": "gears"}), beat("B2", 60, graphic={"kind": "title"}),
             beat("B3", 30, graphic={"kind": "stamp"}), beat("B4", 10, skip=True)]
    s = bm.stats({"beats": beats}, workflow.DEFAULT_SETTINGS)
    assert (s["graphics"], s["cards"], s["popups"]) == (1, 1, 1)
    assert s["runtime_s"] == 150.0 and s["skipped"] == 1
    assert s["budget"] == 2        # ceil(2.5 min * 0.5 per minute)


def test_reading_budget():
    st = workflow.DEFAULT_SETTINGS
    assert bm.reading_budget("two words", st) == pytest.approx(1.0 + 0.4)      # minimum visible time wins
    assert bm.reading_budget("one two three four five six seven eight nine ten", st) == pytest.approx(3.0 + 0.4)
