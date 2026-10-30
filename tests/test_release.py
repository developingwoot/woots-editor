"""The public copy (release/export_public.py) stays clean: nothing personal gets back in. Skipped in the public copy itself, which has no release folder."""
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
pytestmark = pytest.mark.skipif(not (REPO / "release" / "export_public.py").exists() or not (REPO / ".git").exists(), reason="not the development repository")


def test_the_public_copy_has_no_personal_lines_and_none_of_the_excluded_files(tmp_path):
    sys.path.insert(0, str(REPO / "release"))
    import export_public as ex
    files = ex.build(tmp_path / "pub")
    assert ex.scan(tmp_path / "pub", files) == []
    for gone in ("graphics/brain-transplant", "study", "scripts", "sfx", "music_catalog.json", "docs/workflow.md", "docs/backlog.md", "release"):
        assert not (tmp_path / "pub" / gone).exists(), gone
    for there in ("README.md", "LICENSE", "NOTICE.md", "CLAUDE.md", "fonts/OFL.txt", "skills/youtube-edit/rough-cut.json", "tools/channel.py"):
        assert (tmp_path / "pub" / there).is_file(), there
    assert not (tmp_path / "pub" / ".git").exists()
