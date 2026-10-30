"""Every test runs against a throwaway data root, never the real Z: share."""
import os
import sys
import tempfile
from pathlib import Path

_DATA = Path(tempfile.mkdtemp(prefix="woots-test-"))
for k in ("WOOTS_WORK_ROOT", "WOOTS_MUSIC_DIR", "WOOTS_SFX_DIR", "WOOTS_STATE_DIR"):
    os.environ.pop(k, None)
os.environ["WOOTS_DATA_ROOT"] = str(_DATA)
os.environ["WOOTS_SETTINGS_FILE"] = str(_DATA / "user-settings.json")       # never the real per-user file
os.environ["WOOTS_PROFILE_FILE"] = str(_DATA / "user-profile.json")
os.environ["WOOTS_SKILLS_DIR"] = str(_DATA / "user-skills")                 # never the real ~/.claude/skills

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))
(_DATA / "_editor" / "work").mkdir(parents=True)


def pytest_sessionfinish(session, exitstatus):
    """The throwaway data root is not kept: every run used to leave a woots-test-* folder in the temp directory."""
    import shutil
    shutil.rmtree(_DATA, ignore_errors=True)


import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def rough_cut_numbers_back_to_the_skill():
    """A job reloads the rough-cut numbers (some tests set environment overrides first): put the module values back after every test."""
    yield
    for m in ("recut", "coldopen"):
        if m in sys.modules:
            sys.modules[m].reload_rules()
