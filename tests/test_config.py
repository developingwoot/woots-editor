import os

import config


def test_data_is_redirected_away_from_the_share():
    assert not str(config.WORK).upper().startswith("Z:")
    assert config.WORK == config.EDITOR_DATA / "work"
    assert config.WORK.is_dir()


def test_code_root_is_the_repo():
    assert (config.CODE_ROOT / "tools" / "config.py").exists()
    assert (config.CODE_ROOT / "models").is_dir()


def test_modules_use_the_configured_work_folder():
    import workflow, builder, finalrender, usage
    for m in (workflow, builder, finalrender, usage):
        assert m.WORK == config.WORK, m.__name__
    assert finalrender.MUSIC_DIR == config.MUSIC_DIR


def test_tools_are_started_with_the_interpreter_that_runs_the_app_unless_told_otherwise(monkeypatch):
    import builder, selfreview, sys
    import importlib
    assert config.PYTHON.name == __import__("pathlib").Path(sys.executable).name or config.PYTHON.exists()
    assert builder.PYV == config.PYTHON and selfreview.PYV == config.PYTHON
    monkeypatch.setenv("WOOTS_PYTHON", "D:/py/python.exe")
    assert str(importlib.reload(config).PYTHON).replace("\\", "/").endswith("D:/py/python.exe")
    monkeypatch.delenv("WOOTS_PYTHON")
    importlib.reload(config)


def test_no_machine_specific_python_path_is_left_in_the_code():
    import pathlib
    for p in (config.CODE_ROOT / "tools").rglob("*.py"):
        assert ".venvs" not in p.read_text(encoding="utf-8", errors="ignore"), p.name


def test_a_replace_that_is_refused_while_another_thread_reads_is_retried(tmp_path, monkeypatch):
    calls = []
    real = os.replace

    def flaky(a, b):
        calls.append(1)
        if len(calls) < 3:
            raise PermissionError("in use")
        real(a, b)
    monkeypatch.setattr(os, "replace", flaky)
    (tmp_path / "a.tmp").write_text("x", encoding="utf-8")
    config.replace_retry(tmp_path / "a.tmp", tmp_path / "a.json")
    assert (tmp_path / "a.json").read_text(encoding="utf-8") == "x" and len(calls) == 3
