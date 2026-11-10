import json

import pytest

import claudemodels
import config
import workflow


@pytest.fixture(autouse=True)
def clean_settings():
    f = config.settings_file()
    before = f.read_text(encoding="utf-8") if f.exists() else None
    f.unlink(missing_ok=True)
    yield
    if before is None:
        f.unlink(missing_ok=True)
    else:
        f.write_text(before, encoding="utf-8")


def test_the_defaults_are_what_the_app_used_before_the_choice_existed():
    assert claudemodels.get("edit") == ("sonnet", "medium")
    assert claudemodels.get("shorts") == ("sonnet", "medium")
    assert claudemodels.get("critic") == ("opus", "medium")
    assert claudemodels.get("accuracy") == ("opus", "high")


def test_a_choice_is_saved_per_job_and_reaches_the_command_line():
    claudemodels.save({"shorts": {"model": "opus", "effort": "high"}, "edit": {"effort": "low"}})
    assert claudemodels.get("shorts") == ("opus", "high")
    assert claudemodels.get("edit") == ("sonnet", "low")
    assert claudemodels.flags("shorts") == ["--model", "opus", "--effort", "high"]
    assert claudemodels.get("graphics") == ("sonnet", "medium")          # untouched


def test_a_bad_choice_is_refused_and_nothing_is_saved():
    with pytest.raises(ValueError):
        claudemodels.save({"shorts": {"model": "gpt"}})
    with pytest.raises(ValueError):
        claudemodels.save({"edit": {"model": "opus", "effort": "huge"}})
    with pytest.raises(ValueError):
        claudemodels.save({"nothing": {"model": "opus"}})
    assert claudemodels.get("edit") == ("sonnet", "medium")


def test_only_the_critic_can_be_turned_off():
    claudemodels.save({"critic": {"model": "off"}})
    assert claudemodels.get("critic")[0] == "off"
    with pytest.raises(ValueError):
        claudemodels.save({"shorts": {"model": "off"}})


def test_a_damaged_settings_file_falls_back_to_the_default():
    config.settings_file().write_text(json.dumps({"model_edit": "banana", "effort_edit": 7}), encoding="utf-8")
    assert claudemodels.get("edit") == ("sonnet", "medium")


def test_the_graphics_choice_is_the_default_of_every_video_but_a_video_can_keep_its_own():
    claudemodels.save({"graphics": {"model": "opus", "effort": "high"}, "critic": {"model": "off"}})
    assert workflow.effective({})["build_model"] == "opus"
    assert workflow.effective({})["build_effort"] == "high"
    assert workflow.effective({})["critic_model"] == "off"
    assert workflow.effective({"build_model": "haiku"})["build_model"] == "haiku"
    assert workflow.effective({"build_model": "haiku"})["build_effort"] == "high"


def test_the_settings_screen_lists_every_job_with_its_choices():
    v = claudemodels.view()
    assert [j["job"] for j in v["jobs"]] == ["story", "edit", "graphics", "critic", "accuracy", "shorts"]
    assert "off" in next(j for j in v["jobs"] if j["job"] == "critic")["models"]
    assert "off" not in next(j for j in v["jobs"] if j["job"] == "shorts")["models"]
    assert v["efforts"] == ["low", "medium", "high", "xhigh", "max"]


def test_the_story_job_is_opus_and_the_budget_follows_the_model():
    assert claudemodels.get("story") == ("opus", "high")
    assert claudemodels.budget("story", "0.6") == "1.80" and claudemodels.budget("edit", "0.6") == "0.60"
    claudemodels.save({"edit": {"model": "haiku"}})
    assert claudemodels.budget("edit", "1.0") == "0.50"
    claudemodels.save({"edit": {"model": "fable"}})
    assert claudemodels.budget("edit", "1.0") == "5.00"


def test_each_run_uses_the_kind_the_plan_gives_it():
    import re
    from pathlib import Path
    src = (Path(claudemodels.__file__).parent / "review_app" / "server.py").read_text(encoding="utf-8")
    for label in ("comparing takes of the same passage", "looking for a cold open", "reading the cut for repeats and contradictions"):
        line = next(x for x in src.splitlines() if f'claude_step("{label}"' in x)
        assert 'kind="story"' in line, label
    for out in ('"outline.md"', '"publish.json"'):
        line = next(x for x in src.splitlines() if "_claude_run(job, fd, prompt, " + out in x)
        assert 'kind="story"' in line, out
    for label in ("choosing between footage", "finding where the eyes"):
        assert 'kind="story"' not in next(x for x in src.splitlines() if f'claude_step("{label}' in x)
