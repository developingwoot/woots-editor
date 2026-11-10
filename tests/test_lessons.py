import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import makeversion  # noqa: E402
import skillrules  # noqa: E402


def test_a_lesson_must_be_one_general_sentence():
    ok = "Cut the pause before a punchline shorter than the pause after it."
    assert makeversion.clean_lesson(ok) == ok
    assert makeversion.clean_lesson("") == ""
    assert makeversion.clean_lesson(None) == ""
    assert makeversion.clean_lesson("too short") == ""
    assert makeversion.clean_lesson("At 1:23 the host paused for too long before the joke.") == ""
    assert makeversion.clean_lesson("Beat B04 ran long and should be trimmed by half.") == ""
    assert makeversion.clean_lesson("x" * 300) == ""


def test_add_lesson_goes_into_the_users_copy_once(tmp_path, monkeypatch):
    mine = tmp_path / "skills"
    monkeypatch.setattr(skillrules, "SKILLS", mine)
    starter = skillrules.STARTER / "youtube-edit" / "rough-cut.md"
    before = starter.read_text(encoding="utf-8-sig")

    assert skillrules.add_lesson("Keep the host's laugh after a joke.", today="2026-11-10") is True
    text = (mine / "youtube-edit" / "rough-cut.md").read_text(encoding="utf-8")
    assert "- 2026-11-10: Keep the host's laugh after a joke." in text
    assert text.count("Keep the host's laugh") == 1
    assert "## Lessons" in text

    assert skillrules.add_lesson("keep the host's laugh after a joke.", today="2026-11-11") is False     # never twice
    assert (mine / "youtube-edit" / "rough-cut.md").read_text(encoding="utf-8").count("laugh") == 1

    assert skillrules.add_lesson("Start a section on the result, not the setup.", today="2026-11-12") is True
    assert starter.read_text(encoding="utf-8-sig") == before                                              # the repo's starter skills are never touched
