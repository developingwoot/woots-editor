import json
import subprocess
import sys
from pathlib import Path

import pytest

import config
import scorecard
import skillrules

sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures"))
import make_project  # noqa: E402


def test_shot_numbers_come_from_the_times_the_picture_changed():
    s = scorecard.shot_stats([3.0, 6.0, 30.0], 60.0)                 # shots of 3, 3, 24 and 30 s
    assert s == {"changes_per_min": 3.0, "median_shot_s": 13.5, "longest_s": 30, "long_share": 90}
    assert scorecard.shot_stats([], 0) == {}
    assert scorecard.shot_stats([], 20.0)["longest_s"] == 20 and scorecard.shot_stats([], 20.0)["changes_per_min"] == 0


def test_a_cut_counts_as_face_to_face_only_when_both_sides_show_a_face():
    faces = [True] * 10 + [False] * 5 + [True] * 5                  # one frame a second
    s = scorecard.face_stats(faces, cuts=[5.0, 10.5, 17.0], step=1.0)
    assert s["face_share"] == 75 and s["first_thing_s"] == 10.0
    assert s["face_cuts_per_min"] == 6.0                             # 5 s and 17 s have a face either side; 10.5 s goes to the work
    assert scorecard.face_stats([True, True])["first_thing_s"] is None


def test_each_number_sits_inside_below_or_above_the_reference_range():
    refs = scorecard.ranges([{"changes_per_min": 12.0, "longest_s": 20}, {"changes_per_min": 20.0, "longest_s": 50, "label": "x"}, {"changes_per_min": "?"}])
    assert refs["changes_per_min"] == (12.0, 20.0, 2) and "face_share" not in refs
    rows = {r["key"]: r for r in scorecard.compare({"changes_per_min": 9.5, "longest_s": 22, "face_share": 50}, refs)}
    assert rows["changes_per_min"]["where"] == "below" and rows["longest_s"]["where"] == "inside" and rows["face_share"]["where"] == ""
    assert [r["key"] for r in scorecard.compare({"words_per_min": 300}, {"words_per_min": (150, 215, 7)})] == ["words_per_min"]
    assert scorecard.compare({"words_per_min": 300}, {"words_per_min": (150, 215, 7)})[0]["where"] == "above"


def test_the_references_are_the_skill_file_plus_the_ones_the_user_measured(tmp_path, monkeypatch):
    d = tmp_path / "skills" / "youtube-edit"
    d.mkdir(parents=True)
    (d / "references.json").write_text(json.dumps({"videos": [{"label": "a", "changes_per_min": 10.0}, "junk"]}), encoding="utf-8")
    monkeypatch.setattr(skillrules, "SKILLS", tmp_path / "skills")
    monkeypatch.setattr(config, "EDITOR_DATA", tmp_path / "data")
    assert [v["label"] for v in scorecard.reference_videos()] == ["a"]
    (tmp_path / "data" / "references").mkdir(parents=True)
    (tmp_path / "data" / "references" / "mine.json").write_text(json.dumps({"label": "mine", "changes_per_min": 30.0}), encoding="utf-8")
    (tmp_path / "data" / "references" / "broken.json").write_text("not json", encoding="utf-8")
    assert scorecard.ranges(scorecard.reference_videos())["changes_per_min"] == (10.0, 30.0, 2)


def test_the_starter_skill_holds_the_study_videos():
    vids = json.loads((skillrules.STARTER / scorecard.REFS_FILE).read_text(encoding="utf-8"))["videos"]
    assert len(vids) >= 7 and all(isinstance(v.get("changes_per_min"), (int, float)) for v in vids)


def test_a_saved_measurement_comes_back_with_its_comparison_and_says_when_the_final_is_newer(tmp_path, monkeypatch):
    import views
    monkeypatch.setattr(config, "WORK", tmp_path)
    (tmp_path / "w").mkdir()
    (tmp_path / "w" / "v.scorecard.json").write_text(json.dumps({"file": "v1.mp4", "numbers": {"changes_per_min": 1.0}}), encoding="utf-8")
    got = scorecard.load("w", "v")
    assert got["rows"][0]["key"] == "changes_per_min" and got["rows"][0]["where"] == "below" and got["n_refs"] >= 7
    assert views.scorecard_view("w", "v", {"file": "v2.mp4"}, False)["stale"] is True
    view = views.scorecard_view("w", "v", {"file": "v1.mp4"}, True)
    assert view["stale"] is False and view["button"]["enabled"] is False and view["button"]["label"] == "Measure again"
    assert views.scorecard_view("w", "none", None, False)["button"] == {"label": "Measure the final", "enabled": False, "estimate": views.minutes_text(3)}


@pytest.mark.skipif(not make_project.have_ffmpeg(), reason="ffmpeg missing")
def test_a_real_file_is_measured(tmp_path):
    import sectionrender
    out = tmp_path / "two.mp4"
    subprocess.run([sectionrender.FFMPEG, "-v", "error", "-f", "lavfi", "-i", "color=red:s=320x180:d=20", "-f", "lavfi", "-i", "color=blue:s=320x180:d=20",
                    "-filter_complex", "[0][1]concat=n=2:v=1", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(out)], check=True)
    import mpfaces
    n = scorecard.measure(str(out), n_words=100)
    assert n["dur_s"] == 40 and n["changes_per_min"] == 1.5 and n["longest_s"] == 20 and n["words_per_min"] == 150
    if mpfaces.available():
        assert n["face_share"] == 0 and n["first_thing_s"] == 0.0
    else:
        assert "face_share" not in n
