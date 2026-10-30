"""Golden-file test: a fixed transcript must always produce the same cut list.

The expected numbers are worked out by hand from the defaults (max pause 1.0 s, pad 0.2 before / 0.35 after,
min saving 0.5 s, min keep 0.3 s), not copied from the program's output.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

FIX = Path(__file__).parent / "fixtures"
TOOL = Path(__file__).resolve().parent.parent / "tools" / "roughcut.py"
EXPECTED = json.loads((FIX / "sample.expected.json").read_text(encoding="utf-8"))


def run(tmp_path, *extra):
    out = tmp_path / "plan.edit.json"
    r = subprocess.run([sys.executable, str(TOOL), str(FIX / "sample.transcript.json"), "--out", str(out), *extra],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return json.loads(out.read_text(encoding="utf-8"))


def same_ranges(got, want):
    assert len(got) == len(want)
    for (a, b), (c, d) in zip(got, want):
        assert a == pytest.approx(c) and b == pytest.approx(d)


def test_pauses_are_cut_and_breath_is_kept(tmp_path):
    plan = run(tmp_path)
    same_ranges(plan["keeps"], EXPECTED["no_drops"]["keeps"])
    assert plan["stats"]["pieces"] == EXPECTED["no_drops"]["pieces"]
    assert plan["source"] == "clip.mkv"


def test_retake_is_flagged(tmp_path):
    assert run(tmp_path)["flags"] == EXPECTED["no_drops"]["flags"]


def test_editorial_drop_splits_a_keep(tmp_path):
    plan = run(tmp_path, "--drops", str(FIX / "sample.drops.json"))
    same_ranges(plan["keeps"], EXPECTED["with_drops"]["keeps"])
    assert plan["stats"]["pieces"] == EXPECTED["with_drops"]["pieces"]
    assert plan["stats"]["editorial_cut"] == pytest.approx(0.5)


def test_kept_plus_cut_adds_up_to_the_duration(tmp_path):
    plan = run(tmp_path, "--drops", str(FIX / "sample.drops.json"))
    st = plan["stats"]
    assert st["editorial_cut"] + st["pause_cut"] + sum(e - s for s, e in plan["keeps"]) == pytest.approx(plan["duration"], abs=0.2)
