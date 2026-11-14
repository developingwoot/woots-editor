"""The user's own copy of a skill is told about rules and numbers the starter skills got later (the host: a change must reach every video, not one)."""
import json

import skillrules
import skillupdates

MINE = """# My rough cut

## How a video is built from recordings
- My own line about recordings.

## Rules (each is checked)
1. **Shots.** My own rule.

## Lessons
- 2026-10-29: my own lesson.
"""


def _own_copy(tmp_path, monkeypatch, numbers=None):
    monkeypatch.setattr(skillrules, "SKILLS", tmp_path)
    d = tmp_path / "youtube-edit"
    d.mkdir()
    (d / "rough-cut.md").write_text(MINE, encoding="utf-8")
    (d / "rough-cut.json").write_text(json.dumps(numbers if numbers is not None else {"min_piece_s": 5.0}), encoding="utf-8")
    return d


def test_every_update_is_a_rule_of_the_starter_skill_in_the_same_words():
    ups = skillupdates.updates()
    assert ups and len({u["id"] for u in ups}) == len(ups)
    for u in ups:
        starter = (skillrules.STARTER / u["file"]).read_text(encoding="utf-8")
        assert skillupdates._flat(u["text"]) in skillupdates._flat(starter), u["id"]
        assert u.get("about") and u.get("date")


def test_a_user_without_their_own_copy_needs_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(skillrules, "SKILLS", tmp_path)
    assert skillupdates.pending() == {"count": 0, "rules": [], "numbers": []}


def test_missing_rules_and_numbers_are_found_and_added_without_changing_what_is_there(tmp_path, monkeypatch):
    d = _own_copy(tmp_path, monkeypatch)
    p = skillupdates.pending()
    assert {n["key"] for n in p["numbers"]} >= {"talk_min_words", "quiet_near_s"} and "min_piece_s" not in {n["key"] for n in p["numbers"]}
    assert len(p["rules"]) == len(skillupdates.updates()) and p["count"] == len(p["rules"]) + len(p["numbers"])
    got = skillupdates.apply()
    assert got["rules"] == len(p["rules"]) and got["numbers"] == len(p["numbers"])
    assert skillupdates.pending()["count"] == 0
    text = (d / "rough-cut.md").read_text(encoding="utf-8")
    for line in MINE.strip().split("\n"):
        assert line in text
    built, rules, lessons = text.index("## How a video"), text.index("## Rules"), text.index("## Lessons")
    assert built < text.index("`talk_min_words`") < rules < text.index("`quiet_near_s`") < lessons          # each rule in its own section
    nums = json.loads((d / "rough-cut.json").read_text(encoding="utf-8"))
    assert nums["min_piece_s"] == 5.0 and nums["talk_min_words"] == 400                                    # the user's number stays
    assert (d / "rough-cut.md.bak").read_text(encoding="utf-8") == MINE
    assert skillupdates.apply() == {"rules": 0, "numbers": 0, "files": []}


def test_a_rule_goes_under_added_by_the_app_when_its_section_is_not_there():
    out = skillupdates.add_rule("# Mine\n\nSome text.\n", "Rules", "A new rule.")
    assert out == "# Mine\n\nSome text.\n\n## Added by the app\n- A new rule.\n"
    assert skillupdates.add_rule(out, "Rules", "Another.").endswith("- A new rule.\n- Another.\n")


def test_a_broken_numbers_file_is_left_alone(tmp_path, monkeypatch):
    d = _own_copy(tmp_path, monkeypatch)
    (d / "rough-cut.json").write_text("{not json", encoding="utf-8")
    assert skillupdates.missing_numbers() == []
    skillupdates.apply()
    assert (d / "rough-cut.json").read_text(encoding="utf-8") == "{not json"


def test_the_home_screen_is_told(tmp_path, monkeypatch):
    import views
    _own_copy(tmp_path, monkeypatch)
    assert views.home()["skill_updates"]["count"] > 0
