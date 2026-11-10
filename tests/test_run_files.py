"""Each kind of Claude run is given the skill files that suit it; a file that does not exist is skipped."""
import skillrules


def test_every_run_has_a_list_and_the_house_style_comes_first(tmp_path, monkeypatch):
    monkeypatch.setattr(skillrules, "SKILLS", tmp_path / "mine")
    for run in ("takes", "coldopen", "cutreview", "story", "shots", "publish", "outline", "moments"):
        assert skillrules.RUN_FILES[run][:2] == skillrules.COMMON, run
    assert "youtube-edit/takes-and-splicing.md" in skillrules.RUN_FILES["takes"]
    assert {"youtube-script/story-patterns.md", "youtube-edit/lessons.md", "youtube-script/structure.md"} <= set(skillrules.RUN_FILES["cutreview"])
    assert "youtube-script/structure.md" in skillrules.RUN_FILES["coldopen"]


def test_a_missing_file_is_skipped_and_the_users_copy_wins(tmp_path, monkeypatch):
    mine = tmp_path / "mine"
    (mine / "youtube-edit").mkdir(parents=True)
    (mine / "youtube-edit" / "lessons.md").write_text("my lessons", encoding="utf-8")
    monkeypatch.setattr(skillrules, "SKILLS", mine)
    got = skillrules.copy_into(tmp_path / "fd", "cutreview")
    assert "lessons.md" in got and (tmp_path / "fd" / "lessons.md").read_text(encoding="utf-8") == "my lessons"
    assert "director-notes.md" not in got and "story-patterns.md" in got


def test_every_starter_skill_folder_has_a_skill_file():
    for d in skillrules.STARTER.iterdir():
        if d.is_dir():
            assert (d / "SKILL.md").is_file(), d.name
