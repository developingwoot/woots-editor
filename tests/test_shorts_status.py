import json

import projectstore
import shortsapp
import workflow


def project(title):
    r = workflow.create(title)
    wd = workflow.WORK / r["work"]
    tr = wd / "t.json"
    tr.write_text(json.dumps({"duration": 100, "words": [], "segments": []}), encoding="utf-8")
    shortsapp.new_project(r["work"], r["name"], "main.mp4", str(tr), None)
    return r["work"], r["name"], wd


def test_old_status_names_are_read_as_kept_and_dropped():
    work, name, wd = project("Old Status")
    raw = json.loads(shortsapp.cfg_file(work, name).read_text(encoding="utf-8"))
    raw["shorts"] = [{"id": "s1", "ranges": [[1, 20]], "status": "approved"}, {"id": "s2", "ranges": [[30, 50]], "status": "rejected"},
                     {"id": "s3", "ranges": [[60, 80]], "status": "proposed"}, {"id": "s4", "ranges": [[1, 2]]}]
    shortsapp.cfg_file(work, name).write_text(json.dumps(raw), encoding="utf-8")
    got = {s["id"]: s["status"] for s in shortsapp.read_raw(work, name)["shorts"]}
    assert got == {"s1": "kept", "s2": "dropped", "s3": "", "s4": ""}
    assert [p for p in shortsapp.projects() if p["name"] == name][0]["kept"] == 1
    assert [s["id"] for s in shortsapp.live(shortsapp.read_raw(work, name)["shorts"])] == ["s1", "s3", "s4"]


def test_a_short_is_kept_or_dropped_by_edit_and_nothing_else_is_accepted():
    work, name, wd = project("Edit Status")
    raw = shortsapp.read_raw(work, name)
    raw["shorts"] = [{"id": "s1", "ranges": [[1, 20]], "status": ""}]
    shortsapp.save_raw(work, name, raw)
    shortsapp.apply_op(work, name, "edit", {"id": "s1", "status": "kept"})
    assert shortsapp.read_raw(work, name)["shorts"][0]["status"] == "kept"
    shortsapp.apply_op(work, name, "edit", {"id": "s1", "status": "rejected"})            # the old name is accepted and means dropped
    assert shortsapp.read_raw(work, name)["shorts"][0]["status"] == "dropped"
    try:
        shortsapp.apply_op(work, name, "edit", {"id": "s1", "status": "maybe"})
    except ValueError as e:
        assert "kept, dropped" in str(e)
    else:
        raise AssertionError("an unknown status was accepted")


def test_the_shorts_project_is_a_plan_file_with_history_and_undo():
    work, name, wd = project("Plan File")
    assert projectstore.is_plan(shortsapp.cfg_file(work, name))
    raw = shortsapp.read_raw(work, name)
    raw["shorts"] = [{"id": "s1", "ranges": [[1, 20]], "status": ""}]
    shortsapp.save_raw(work, name, raw, why="added a short")
    entries = projectstore.history(wd, f"{name}.shorts.json")
    assert entries and entries[0]["why"] == "added a short"
    first = entries[-1]
    projectstore.restore(wd, first["id"])
    assert shortsapp.read_raw(work, name)["shorts"] == []


# ----------------------------------------------------------------------------- real source sizes
import shutil
import subprocess

import pytest

import shorts

needs_ffmpeg = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not installed")


def clip(path, size, seconds=2):
    r = subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"testsrc=size={size}:rate=30:duration={seconds}",
                        "-f", "lavfi", "-i", f"sine=frequency=300:duration={seconds}", "-pix_fmt", "yuv420p", "-shortest", str(path)])
    assert r.returncode == 0


@needs_ffmpeg
def test_the_size_of_a_source_is_read_from_the_file(tmp_path):
    clip(tmp_path / "a.mp4", "1280x720")
    assert shorts.probe_size(tmp_path / "a.mp4") == (1280, 720)
    assert shorts.probe_size(tmp_path / "missing.mp4") == shorts.DEFAULT_SIZE


def test_the_crop_stays_inside_a_720p_frame():
    pc = {"cx": 0.99, "cy": 0.5, "zoom": 1.0, "sw": 1280, "sh": 720}
    cw, ch, x, y = shorts.crop_box(pc)
    assert (cw, ch) == (404, 720) and x + cw <= 1280 and y + ch <= 720
    assert shorts.crop_box({"cx": 0.5, "cy": 0.5, "zoom": 1.0}) [:2] == (608, 1080)             # no size known: the old 1080p default


@needs_ffmpeg
def test_a_720p_source_plans_and_renders_without_reading_outside_the_frame(tmp_path):
    src = tmp_path / "talk.mp4"
    clip(src, "1280x720", 4)
    tr = tmp_path / "t.json"
    words = [{"word": w, "start": 0.2 + 0.4 * i, "end": 0.55 + 0.4 * i} for i, w in enumerate("one two three four five six seven".split())]
    tr.write_text(json.dumps({"duration": 4, "words": words, "segments": [{"start": 0.2, "end": 3, "text": "one two three four five six seven"}]}), encoding="utf-8")
    cfg_path = tmp_path / "cfg.shorts.json"
    cfg_path.write_text(json.dumps({"source": str(src), "transcript": str(tr), "shorts": [{"id": "s1", "hook": "A HOOK", "ranges": [[0.0, 3.5]]}]}), encoding="utf-8")
    cfg = shorts.load(cfg_path)
    assert cfg["_size"] == (1280, 720)
    short = cfg["shorts"][0]
    cfg["_short"] = short
    pieces = shorts.classify(cfg, shorts.build_pieces(cfg, short))
    assert pieces and all((p["sw"], p["sh"]) == (1280, 720) for p in pieces)
    out = tmp_path / "s1.mp4"
    shorts.render(cfg, short, str(out), pieces, "preview")
    assert shorts.probe_size(out) == (540, 960)


# ----------------------------------------------------------------------------- several sources
def colour_clip(path, colour, size="640x360", seconds=6, audio=True):
    cmd = ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"color=c={colour}:size={size}:rate=30:duration={seconds}"]
    if audio:
        cmd += ["-f", "lavfi", "-i", f"sine=frequency=300:duration={seconds}", "-shortest"]
    assert subprocess.run(cmd + ["-pix_fmt", "yuv420p", str(path)]).returncode == 0


def words_file(path, text, start=0.2):
    ws = [{"word": w, "start": start + 0.4 * i, "end": start + 0.4 * i + 0.35} for i, w in enumerate(text.split())]
    path.write_text(json.dumps({"duration": 6, "words": ws, "segments": [{"start": start, "end": ws[-1]["end"], "text": text}]}), encoding="utf-8")


def test_a_file_with_one_source_is_read_as_source_a(tmp_path):
    words_file(tmp_path / "t.json", "one two three")
    (tmp_path / "v.mp4").write_bytes(b"")
    cfg_path = tmp_path / "c.shorts.json"
    cfg_path.write_text(json.dumps({"source": str(tmp_path / "v.mp4"), "transcript": str(tmp_path / "t.json"),
                                    "shorts": [{"id": "s1", "ranges": [[0.0, 2.0], {"src": "a", "a": 3.0, "b": 4.0}]}]}), encoding="utf-8")
    cfg = shorts.load(cfg_path)
    assert list(cfg["_srcs"]) == ["a"] and cfg["_first"] == "a"
    assert shorts.norm_ranges(cfg, cfg["shorts"][0]) == [("a", 0.0, 2.0), ("a", 3.0, 4.0)]


def test_words_and_cuts_follow_the_source_of_each_range(tmp_path):
    words_file(tmp_path / "ta.json", "alpha beta gamma")
    words_file(tmp_path / "tb.json", "delta epsilon zeta")
    (tmp_path / "a.mp4").write_bytes(b"")
    (tmp_path / "b.mp4").write_bytes(b"")
    cfg_path = tmp_path / "c.shorts.json"
    cfg_path.write_text(json.dumps({"sources": [{"id": "a", "path": str(tmp_path / "a.mp4"), "transcript": str(tmp_path / "ta.json")},
                                                {"id": "b", "path": str(tmp_path / "b.mp4"), "transcript": str(tmp_path / "tb.json")}],
                                    "shorts": [{"id": "s1", "ranges": [[0.0, 2.0], {"src": "b", "a": 0.0, "b": 2.0}],
                                                "drop": [{"src": "b", "a": 0.6, "b": 1.0}], "words": {"b:0.2": "DELTA"}}]}), encoding="utf-8")
    cfg = shorts.load(cfg_path)
    got = [(w["src"], w["w"]) for w in shorts.kept_words(cfg, cfg["shorts"][0])]
    assert got == [("a", "alpha"), ("a", "beta"), ("a", "gamma"), ("b", "DELTA"), ("b", "zeta")]            # "epsilon" (0.6-0.95) is dropped in b only


@needs_ffmpeg
def test_a_short_from_two_files_shows_each_files_picture(tmp_path):
    import cv2
    colour_clip(tmp_path / "a.mp4", "red")
    colour_clip(tmp_path / "b.mp4", "green", size="1280x720")
    words_file(tmp_path / "ta.json", "red words come first here")
    words_file(tmp_path / "tb.json", "then green words follow it")
    cfg_path = tmp_path / "c.shorts.json"
    cfg_path.write_text(json.dumps({"sources": [{"id": "a", "path": str(tmp_path / "a.mp4"), "transcript": str(tmp_path / "ta.json")},
                                                {"id": "b", "path": str(tmp_path / "b.mp4"), "transcript": str(tmp_path / "tb.json")}],
                                    "shorts": [{"id": "s1", "ranges": [[0.0, 2.4], {"src": "b", "a": 0.0, "b": 2.4}]}]}), encoding="utf-8")
    cfg = shorts.load(cfg_path)
    short = cfg["shorts"][0]
    cfg["_short"] = short
    pieces = shorts.classify(cfg, shorts.build_pieces(cfg, short))
    assert {p["src"] for p in pieces} == {"a", "b"} and {(p["sw"], p["sh"]) for p in pieces if p["src"] == "b"} == {(1280, 720)}
    out = tmp_path / "s1.mp4"
    total, _ = shorts.render(cfg, short, str(out), pieces, "preview")

    def colour_at(t):
        cap = cv2.VideoCapture(str(out))
        cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
        ok, fr = cap.read()
        assert ok
        b, g, r = fr[200:700, 100:440].reshape(-1, 3).mean(axis=0)
        return "red" if r > g and r > b else "green" if g > r and g > b else "other"
    first_b = min(p["t0"] for p in pieces if p["src"] == "b")
    assert colour_at(0.4) == "red" and colour_at(first_b + 0.5) == "green"
