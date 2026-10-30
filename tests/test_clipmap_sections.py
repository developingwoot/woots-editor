import clipmap
import footage_cfg
import sections


def test_parse_script_ids_headings_and_stage_directions():
    text = "# Intro\nS01: Hello there [pause] friend\nnot a script line\n## Part Two\nS02 - Second line\n"
    lines = clipmap.parse_script(text)
    assert [l["id"] for l in lines] == ["S01", "S02"]
    assert lines[0]["heading"] == "Intro" and lines[1]["heading"] == "Part Two"
    assert lines[0]["tokens"] == ["hello", "there", "friend"]       # [pause] is not spoken
    assert lines[1]["tokens"] == ["second", "line"]


def test_tokens_handle_curly_apostrophes():
    assert clipmap.tokens_of("It’s Sam’s") == ["it's", "sam's"]


def test_split_takes_on_long_pause_and_on_restart():
    words = [["a", 0, 1], ["b", 1.1, 2], ["c", 4, 5]]
    assert clipmap.split_takes(words, []) == [words[:2], words[2:]]
    assert clipmap.split_takes(words[:2], [1.1]) == [words[:1], words[1:2]]
    assert clipmap.split_takes([], []) == []


def test_iou():
    assert clipmap.iou(0, 2, 1, 3) == 1 / 3
    assert clipmap.iou(0, 1, 2, 3) == 0.0
    assert clipmap.iou(0, 0, 0, 0) == 0.0


def test_auto_role_prefers_file_name_over_folder():
    r = footage_cfg.auto_role
    assert r("A Roll/clip1.mkv") == "aroll"
    assert r("B Roll/V3/shot.mkv") == "broll"
    assert r("A Roll/intro take 2.mkv") == "intro"
    assert r("B_Roll/outro.mkv") == "outro"
    assert r("misc/x.mkv") == "unassigned"


def test_role_override_wins_and_is_flagged():
    cfg = {"roles": {"misc/x.mkv": "broll"}}
    assert footage_cfg.role_of(cfg, "misc/x.mkv") == ("broll", True)
    assert footage_cfg.role_of(cfg, "A Roll/y.mkv") == ("aroll", False)


def sec(section, dur, n):
    return [{"id": f"{section}{i}", "section": section, "dur": dur} for i in range(n)]


def test_group_keeps_sections_apart_and_ignores_skipped_beats():
    beats = sec("A", 30, 3) + sec("B", 30, 3)
    beats.insert(1, {"id": "skipped", "section": "A", "dur": 500, "skip": True})
    groups = sections.group(beats)
    assert [[b["id"] for b in g] for g in groups] == [["A0", "A1", "A2"], ["B0", "B1", "B2"]]


def test_group_merges_short_neighbours_and_splits_long_sections():
    merged = sections.group(sec("A", 20, 1) + sec("B", 20, 1) + sec("C", 90, 1))
    assert [len(g) for g in merged] == [2, 1]
    long_ = sections.group(sec("A", 30, 5))                 # 150 s > the 120 s cap: cut once the 90 s target is passed
    assert [len(g) for g in long_] == [3, 2]
