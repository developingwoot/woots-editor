import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures"))
import make_project  # noqa: E402


def test_fixture_project_without_clips_has_an_outline():
    r = make_project.build(clips=False)
    assert (r["dir"] / f"{r['name']}.script.md").read_text(encoding="utf-8").strip()


@pytest.mark.skipif(not make_project.have_ffmpeg(), reason="ffmpeg missing")
def test_fixture_clips_are_real_video_files():
    import workflow
    workflow.WORK  # data root is the temp one from conftest
    import shutil
    d = workflow.WORK / "zz-demo"
    shutil.rmtree(d, ignore_errors=True)
    r = make_project.build()
    assert len(list((r["dir"] / "footage").glob("take*.mp4"))) == 3
