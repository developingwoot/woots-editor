import shortsplan as sp


def beats(spec):
    """spec: [(section, dur, graphic_or_None, extra)] -> beats laid end to end like beatmap.retime does."""
    out, t = [], 0.0
    for i, (sec, dur, g, extra) in enumerate(spec, 1):
        b = {"id": f"B{i:02d}", "section": sec, "dur": float(dur), "start": t, "end": t + dur, "graphic": g,
             "on_screen": {"broll": []}, "skip": False}
        b.update(extra or {})
        out.append(b)
        t += dur
    return out


EXPLAINER = {"kind": "gears", "strength": 3}


def test_beat_scores():
    s = sp.beat_score
    assert s({"graphic": {"kind": "title"}}) == 0 and s({"graphic": {"kind": "end"}}) == 0
    assert s({"graphic": {"kind": "gears", "strength": 5}}) == 4.0
    assert s({"graphic": {"kind": "gears", "strength": 1}}) == 2.0
    assert s({"graphic": {"kind": "stamp"}}) == 0.5
    assert s({"graphic": {"kind": "gears"}, "vo": {"id": "TP01"}}) == 4.5          # explainer + teaching point
    assert s({"on_screen": {"broll": ["a.mp4"]}}) == 1.0
    assert s({"graphic": {"kind": "gears"}, "skip": True}) == 0
    assert s({"graphic": {"kind": "gears", "struck": True}}) == 0


def test_a_moment_takes_its_setup_and_payoff_but_stays_inside_its_section():
    bs = beats([("A", 20, None, None), ("B", 6, None, None), ("B", 10, EXPLAINER, None), ("B", 6, None, None), ("C", 6, None, None)])
    [m] = sp.moments(bs)
    assert m["beats"] == ["B02", "B03", "B04"]                   # the 6 s before and after, not the section next door
    assert m["sections"] == ["B"] and m["start"] == 20 and m["end"] == 42


def test_nearby_strong_beats_merge_into_one_moment():
    bs = beats([("A", 6, None, None), ("A", 10, EXPLAINER, None), ("A", 10, EXPLAINER, None), ("A", 6, None, None)])
    assert len(sp.moments(bs)) == 1


def test_a_ten_minute_video_gets_about_three_shorts_not_ten():
    spec = []
    for s in "ABCDE":                                           # five sections, each with one strong moment
        spec += [(s, 30, None, None), (s, 10, EXPLAINER, None), (s, 80, None, None)]
    r = sp.recommend(beats(spec))
    assert r["runtime_s"] == 600 and r["by_length"] == 3 and r["strong"] == 5
    assert r["recommended"] == 3 and r["confidence"] == "high"
    assert any("one short per 3.5 minutes" in x for x in r["reasons"])


def test_fewer_strong_moments_than_the_length_allows_stops_at_the_strong_ones():
    spec = [("A", 200, None, None), ("A", 10, EXPLAINER, None), ("A", 390, None, None)]     # 10 minutes, one strong moment
    r = sp.recommend(beats(spec))
    assert r["by_length"] == 3 and r["strong"] == 1 and r["recommended"] == 1


def test_short_and_very_long_videos():
    assert sp.recommend(beats([("A", 180, EXPLAINER, None)]))["by_length"] == 1
    assert sp.recommend(beats([("A", 2400, EXPLAINER, None)]))["by_length"] == sp.HARD_CAP


def test_no_beat_map_or_no_strong_moments_is_a_low_confidence_estimate():
    r = sp.recommend(None, runtime_s=600)
    assert r["recommended"] == 3 and r["confidence"] == "low"
    r = sp.recommend(beats([("A", 600, None, None)]))
    assert r["recommended"] == 1 and r["confidence"] == "low" and r["strong"] == 0
    assert sp.recommend(None)["recommended"] == 0                                           # nothing to cut from


def good(title="T", ranges=((10, 40),)):
    return {"title": title, "ranges": [list(r) for r in ranges], "thought": {"setup": "a", "point": "b", "payoff": "c"}}


def test_validate_accepts_a_good_set():
    assert sp.validate([good("A", ((10, 40),)), good("B", ((100, 120), (300, 310)))], 600, 3) == []


def test_validate_enforces_length_thought_range_overlap_and_count():
    p = sp.validate([good("short", ((10, 15),))], 600)
    assert any("under the 10 s minimum" in x for x in p)
    p = sp.validate([good("long", ((0, 200),))], 600)
    assert any("over the 180 s maximum" in x for x in p)
    no_thought = good("x"); no_thought["thought"] = {"setup": "a", "point": "", "payoff": "c"}
    assert any("complete thought" in x for x in sp.validate([no_thought], 600))
    assert any("past the end" in x for x in sp.validate([good("x", ((590, 640),))], 600))
    assert any("same part" in x for x in sp.validate([good("a", ((10, 40),)), good("b", ((20, 50),))], 600))
    assert any("3 shorts were proposed but 2 were asked" in x for x in sp.validate([good("a"), good("b", ((100, 130),)), good("c", ((200, 230),))], 600, 2))
    assert any("not valid" in x for x in sp.validate([{"title": "bad", "ranges": [[5, 5]]}], 600))


def test_fifteen_seconds_is_fine_and_over_a_minute_is_only_flagged():
    assert sp.validate([good("brief", ((50, 65),))], 600) == []
    assert sp.long_ones([good("a", ((0, 61),)), good("b", ((0, 30),))]) == ["a"]


def test_prompt_text_states_the_count_and_the_rules():
    t = sp.find_rules(3)
    assert "exactly 3 shorts" in t and "10 seconds to 180 seconds" in t and "DIFFERENT sections" in t and '"thought"' in t
    assert "exactly 1 short." in sp.find_rules(1)
    assert "only 1 strong visual moment" in sp.find_rules(5, strong=1)
    assert "none were found" in sp.moments_text([])
