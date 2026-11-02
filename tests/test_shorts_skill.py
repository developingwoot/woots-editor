import json

import shortsplan
import shorts
import skillrules


def test_the_starter_skill_has_the_numbers_shortsplan_used_to_hold():
    r = skillrules.shorts()
    assert (r["min_s"], r["favour_s"], r["max_s"], r["minutes_per_short"], r["hard_cap"]) == (10.0, 60.0, 180.0, 3.5, 8)
    assert (r["caption_max_words"], r["caption_max_chars"], r["hook_s"]) == (3, 17, 2.8)


def test_the_users_copy_of_the_numbers_wins_and_bad_values_are_ignored(tmp_path, monkeypatch):
    monkeypatch.setattr(skillrules, "SKILLS", tmp_path)
    (tmp_path / "youtube-shorts").mkdir()
    (tmp_path / "youtube-shorts" / "shorts.json").write_text(json.dumps({"max_s": 90, "hard_cap": 3, "min_s": -5, "hook_s": "soon", "other": 1}), encoding="utf-8")
    r = skillrules.shorts()
    assert r["max_s"] == 90.0 and r["hard_cap"] == 3 and r["min_s"] == 10.0 and r["hook_s"] == 2.8 and "other" not in r
    assert shortsplan.hard_cap() == 3
    problems = shortsplan.validate([{"title": "T", "ranges": [[0, 100]], "thought": {"setup": "a", "point": "b", "payoff": "c"}}], 200)
    assert any("over the 90 s maximum" in p for p in problems)


def test_a_broken_numbers_file_falls_back_to_the_defaults(tmp_path, monkeypatch):
    monkeypatch.setattr(skillrules, "SKILLS", tmp_path)
    monkeypatch.setattr(skillrules, "STARTER", tmp_path / "none")
    (tmp_path / "youtube-shorts").mkdir()
    (tmp_path / "youtube-shorts" / "shorts.json").write_text("not json", encoding="utf-8")
    assert skillrules.shorts() == skillrules.SHORTS_DEFAULTS


def test_the_find_prompt_carries_the_skills_rules_with_its_numbers(tmp_path, monkeypatch):
    monkeypatch.setattr(skillrules, "SKILLS", tmp_path)
    (tmp_path / "youtube-shorts").mkdir()
    (tmp_path / "youtube-shorts" / "shorts.md").write_text("# mine\n- Between {min_s} and {max_s} seconds, hook for {hook_s} s.\n- Always end on a joke.\n", encoding="utf-8")
    text = shortsplan.find_rules(2)
    assert "Between 10 and 180 seconds, hook for 2.8 s." in text and "Always end on a joke." in text and "# mine" not in text
    assert "make exactly 2 shorts" in text and "candidates.json" in text


def test_the_starter_rules_say_what_the_prompt_always_said():
    text = shortsplan.find_rules(1)
    for need in ("COMPLETE THOUGHT", "Start on the hook", "10 seconds to 180 seconds", "first 2.8 seconds"):
        assert need in text


def test_the_caption_size_comes_from_the_skill(tmp_path, monkeypatch):
    words = [{"w": w, "s": i, "e": i + 0.5} for i, w in enumerate("a b c d e f".split())]
    assert [len(c) for c in shorts.chunks_of(words)] == [3, 3]
    monkeypatch.setattr(skillrules, "SKILLS", tmp_path)
    (tmp_path / "youtube-shorts").mkdir()
    (tmp_path / "youtube-shorts" / "shorts.json").write_text(json.dumps({"caption_max_words": 2}), encoding="utf-8")
    assert [len(c) for c in shorts.chunks_of(words)] == [2, 2, 2]
