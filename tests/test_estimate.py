import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures"))
import make_project  # noqa: E402
import views  # noqa: E402

needs_ffmpeg = pytest.mark.skipif(not make_project.have_ffmpeg(), reason="ffmpeg missing")


@needs_ffmpeg
def test_the_first_rough_cut_button_shows_the_same_estimate_on_both_screens():
    r = make_project.build(cut=True, title="estimate same")
    foot = views.footage_view(r["work"], r["name"])["button"]["estimate"]
    cut = views.review(r["work"], r["name"], "cut")["button"]["estimate"]
    assert foot and foot == cut


def test_the_step_bar_says_which_step_is_next_and_never_runs_ahead_unmarked():
    f = {"outline": True, "clips": False, "cut": False, "cut_made": False, "preview": True, "final": False, "shorts_kept": 0}
    bar = {s["id"]: s for s in views._dots(f, "footage")}
    assert bar["outline"]["state"] == "done" and bar["footage"]["state"] == "next"
    assert bar["preview"]["state"] == "made earlier"                      # a later step with files while an earlier one has none
    assert bar["final"]["state"] == "not started" and bar["final"]["label"] == "Final: not started"
