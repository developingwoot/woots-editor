"""Catches the 'a file got corrupted' class of bug (server.py was corrupted three times)."""
import ast
import importlib
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
PY_FILES = sorted((REPO / "tools").rglob("*.py"))
JS_FILES = sorted((REPO / "tools" / "review_app" / "static").glob("*.js")) + sorted((REPO / "tools" / "review_app" / "static" / "v2").glob("*.js"))


@pytest.mark.parametrize("p", PY_FILES, ids=lambda p: p.name)
def test_python_parses(p):
    ast.parse(p.read_bytes().decode("utf-8-sig"), filename=str(p))


@pytest.mark.skipif(not shutil.which("node"), reason="node not installed")
@pytest.mark.parametrize("p", JS_FILES, ids=lambda p: p.name)
def test_js_parses(p):
    r = subprocess.run(["node", "--check", str(p)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


@pytest.mark.parametrize("name", ["workflow", "beatmap", "storyboard", "sections", "scriptedit", "shootplan",
                                  "clipmap", "gfxplan", "watchnotes", "usage", "finalrender", "builder",
                                  "views", "outline", "shotmatch", "footageview", "publish", "archive", "thumbdraft", "cutview", "makeversion",
                                  "reviewnotes", "teaching", "brolllib"])
def test_tool_imports(name):
    try:
        importlib.import_module(name)
    except ModuleNotFoundError as e:
        if e.name == name or (e.name or "").startswith(("config", "workflow")):
            raise
        pytest.skip(f"optional dependency missing: {e.name}")
