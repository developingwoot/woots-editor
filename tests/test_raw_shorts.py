import json
import shutil
import subprocess

import pytest

import rawshorts
import shortsapp
import shorts
import workflow

needs_ffmpeg = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not installed")


def clip(path, colour, seconds=10, size="640x360", audio=True):
    cmd = ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"color=c={colour}:size={size}:rate=30:duration={seconds}"]
    if audio:
        cmd += ["-f", "lavfi", "-i", f"sine=frequency=300:duration={seconds}", "-shortest"]
    assert subprocess.run(cmd + ["-pix_fmt", "yuv420p", str(path)]).returncode == 0


def said(path, text, seconds=10, start=0.2, step=0.35):
    ws = [{"word": w, "start": start + step * i, "end": start + step * i + 0.3} for i, w in enumerate(text.split())]
    path.write_text(json.dumps({"duration": seconds, "words": ws, "segments": [{"start": start, "end": ws[-1]["end"], "text": text}]}), encoding="utf-8")


TALK = "so the gears kept breaking after three prints and I tried thicker walls but that did nothing then I changed the tooth shape and now they last"


def test_a_restarted_sentence_is_a_mistake_and_the_later_take_stays():
    words = [[w, 0.4 * i, 0.4 * i + 0.3] for i, w in enumerate(
        "and if I am doing something for CAD I use plasticity . and if I am doing something with CAD I use plasticity every time".split())]
    spans = rawshorts.mistakes(words)
    assert spans and spans[0][0] == 0.0 and spans[0][1] < words[12][1] + 0.5          # the first attempt goes
    assert rawshorts.mistakes([]) == []
    clean = [[w, 0.4 * i, 0.4 * i + 0.3] for i, w in enumerate("this is a clean sentence said only once and then another one follows".split())]
    assert rawshorts.mistakes(clean) == []


def test_talking_and_broll_are_told_apart_by_how_much_is_said(tmp_path):
    talk, quiet, noisy = tmp_path / "talk.mp4", tmp_path / "quiet.mp4", tmp_path / "noisy.mp4"
    for f in (talk, quiet, noisy):
        f.write_bytes(b"")
    said(tmp_path / "talk.transcript.json", TALK)
    said(tmp_path / "noisy.transcript.json", "hmm yes", seconds=30)
    info = rawshorts.tell_apart([talk, quiet, noisy], tmp_path)
    assert [info[f]["kind"] for f in (talk, quiet, noisy)] == ["talk", "broll", "broll"]          # no transcript at all = no sound = b-roll


SOURCES = {"t1": {"id": "t1", "kind": "talk", "dur": 60, "mistakes": [[10.0, 14.0]]}, "t2": {"id": "t2", "kind": "talk", "dur": 30, "mistakes": []},
           "b1": {"id": "b1", "kind": "broll", "dur": 5.0}, "b2": {"id": "b2", "kind": "broll", "dur": 8.0}}
THOUGHT = {"setup": "s", "point": "p", "payoff": "y"}


def cand(**kw):
    base = {"title": "T", "thought": THOUGHT, "ranges": [{"src": "t1", "a": 20, "b": 40}], "overlays": []}
    return dict(base, **kw)


def test_a_good_candidate_passes_and_a_bad_one_says_why():
    clean, problems, left = rawshorts.check(cand(), SOURCES)
    assert clean and not problems and not left
    for bad, word in [(cand(ranges=[{"src": "b1", "a": 0, "b": 4}]), "not a talking"), (cand(ranges=[{"src": "t1", "a": 20, "b": 80}]), "outside"),
                      (cand(ranges=[{"src": "t1", "a": 10.5, "b": 13.5}]), "abandoned"), (cand(ranges=[{"src": "t1", "a": 20, "b": 24}]), "minimum"),
                      (cand(ranges=[{"src": "t1", "a": 20, "b": 40}, {"src": "t1", "a": 30, "b": 45}]), "same part"), (cand(thought={}), "setup"),
                      (cand(ranges=[]), "no ranges")]:
        got, problems, _ = rawshorts.check(bad, SOURCES)
        assert got is None and word in problems[0], (word, problems)


def test_overlays_that_do_not_fit_are_left_out_one_by_one_and_the_short_stays():
    ovs = [{"src": "b1", "a": 0, "b": 3, "at": {"src": "t1", "t": 25}},                       # fine
           {"src": "b2", "a": 0, "b": 8, "at": {"src": "t1", "t": 30}},                       # too long: shortened to the skill's maximum
           {"src": "t2", "a": 0, "b": 3, "at": {"src": "t1", "t": 33}},                       # not a b-roll clip
           {"src": "b1", "a": 0, "b": 3, "at": {"src": "t1", "t": 35}},                       # used twice
           {"src": "b2", "a": 6, "b": 12, "at": {"src": "t1", "t": 36}},                      # past the end of the clip
           {"src": "b2", "a": 0, "b": 0.4, "at": {"src": "t1", "t": 37}},                     # too short
           {"src": "b2", "a": 0, "b": 3, "at": {"src": "t2", "t": 3}},                        # a word that is not in the short
           {"src": "b2", "a": 0, "b": 3, "at": {"src": "t1", "t": 20.5}}]                     # over the first two seconds
    clean, problems, left = rawshorts.check(cand(overlays=ovs), SOURCES)
    assert clean and not problems and len(left) == 6
    assert [(o["src"], o["b"] - o["a"]) for o in clean["overlays"]] == [("b1", 3.0), ("b2", 4.0)]


def piece(a, b, t0, words, src="t1", cont=False):
    return {"a": a, "b": b, "dur": b - a, "t0": t0, "src": src, "cont": cont, "layout": "live", "zoom": 1.0, "cx": 0.5, "cy": 0.5, "sw": 640, "sh": 360,
            "words": [{"w": "w", "s": s, "e": s + 0.3, "src": src} for s in words]}


def overlay_cfg():
    return {"_srcs": {k: {"id": k} for k in SOURCES}, "_first": "t1"}


def test_broll_over_talking_splits_the_pieces_and_keeps_the_sound_in_one_piece_of_time():
    pieces = [piece(10, 14, 0.0, [10.1, 11, 12, 13]), piece(20, 26, 4.0, [20.1, 21, 22, 23, 24, 25])]
    short = {"overlays": [{"src": "b1", "a": 1.0, "b": 4.0, "at": {"src": "t1", "t": 12.0}}]}
    out = shorts.apply_overlays(overlay_cfg(), short, pieces)
    assert sum(p["dur"] for p in out) == pytest.approx(10.0)
    assert [round(p["t0"], 2) for p in out] == sorted(round(p["t0"], 2) for p in out)
    over = [p for p in out if p.get("over")]
    assert over and all(p["layout"] == "blur" and p["over"]["src"] == "b1" for p in over)
    assert over[0]["t0"] == pytest.approx(2.0 - 0.15, abs=0.01)                                   # the picture comes in a hair before the word
    assert sum(p["over"]["b"] - p["over"]["a"] for p in over) == pytest.approx(3.0, abs=0.05)
    assert over[0]["over"]["a"] == pytest.approx(1.0)
    assert [w["s"] for p in out for w in p["words"]] == [10.1, 11, 12, 13, 20.1, 21, 22, 23, 24, 25]      # every word is in exactly one piece
    assert all(p["cont"] for p in out[1:4] if p["src"] == "t1" and p["a"] < 14 and p is not out[0])
    assert not any(p.get("over") for p in pieces)                                                  # the input was not changed
    assert shorts.apply_overlays(overlay_cfg(), {}, pieces) is pieces


def test_an_overlay_at_a_word_that_is_not_in_the_short_is_ignored():
    pieces = [piece(10, 14, 0.0, [10.1, 11, 12, 13])]
    short = {"overlays": [{"src": "b1", "a": 0, "b": 3, "at": {"src": "t1", "t": 50.0}}]}
    assert [p.get("over") for p in shorts.apply_overlays(overlay_cfg(), short, pieces)] == [None]


@needs_ffmpeg
def test_the_filter_graph_takes_the_picture_from_the_broll_file_and_the_sound_from_the_talk_file():
    pieces = shorts.apply_overlays(overlay_cfg(), {"overlays": [{"src": "b1", "a": 1.0, "b": 4.0, "at": {"src": "t1", "t": 12.0}}]},
                                   [piece(10, 14, 0.0, [10.1, 11, 12, 13])])
    fv, fa = shorts.filter_graph(pieces, {"t1": 9.0, "b1": 0.0}, 1.0, 0.5, {"t1": 0, "b1": 1})
    graph = ";".join(fv + fa)
    i = next(i for i, p in enumerate(pieces) if p.get("over"))
    assert "[1:v]trim=start=1.000" in graph
    assert f"[0:a]atrim=start={pieces[i]['a'] - 9.0:.3f}" in graph and "[1:a]" not in graph


@needs_ffmpeg
def test_a_rendered_short_shows_the_broll_while_the_talking_recording_keeps_playing(tmp_path):
    import cv2
    clip(tmp_path / "talk.mp4", "red")
    clip(tmp_path / "pic.mp4", "green", seconds=6, size="1280x720", audio=False)
    said(tmp_path / "talk.json", TALK)
    cfg_path = tmp_path / "c.shorts.json"
    cfg_path.write_text(json.dumps({"mode": "raw", "sources": [{"id": "t1", "path": str(tmp_path / "talk.mp4"), "transcript": str(tmp_path / "talk.json"), "kind": "talk"},
                                                               {"id": "b1", "path": str(tmp_path / "pic.mp4"), "kind": "broll"}],
                                    "shorts": [{"id": "s1", "ranges": [{"src": "t1", "a": 0.0, "b": 8.0}],
                                                "overlays": [{"src": "b1", "a": 0.5, "b": 3.5, "at": {"src": "t1", "t": 3.0}}]}]}), encoding="utf-8")
    cfg = shorts.load(cfg_path)
    short = cfg["shorts"][0]
    cfg["_short"] = short
    pieces = shorts.classify(cfg, shorts.build_pieces(cfg, short))
    over = [p for p in pieces if p.get("over")]
    assert over
    out = tmp_path / "s1.mp4"
    total, _ = shorts.render(cfg, short, str(out), pieces, "preview")
    assert shorts.probe_size(out) == (540, 960)

    def colour_at(t):
        cap = cv2.VideoCapture(str(out))
        cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
        ok, fr = cap.read()
        assert ok
        b, g, r = fr[480:520, 270:300].reshape(-1, 3).mean(axis=0)                  # the middle of the frame: the sharp copy of the b-roll
        return "green" if g > r and g > b else "red" if r > g and r > b else "other"
    t0 = over[0]["t0"]
    assert colour_at(max(t0 - 0.5, 0.05)) == "red" and colour_at(t0 + 1.0) == "green"
    audio = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries", "stream=duration", "-of", "csv=p=0", str(out)],
                           capture_output=True, text=True).stdout.strip()
    assert float(audio) == pytest.approx(total, abs=0.3)                          # the sound runs the whole short


@needs_ffmpeg
def test_a_folder_becomes_a_project_and_claudes_answer_is_imported_with_the_mistakes_cut(tmp_path):
    folder = tmp_path / "Raw Day"
    folder.mkdir()
    clip(folder / "take1.mp4", "red", seconds=20)
    clip(folder / "pic.mp4", "green", seconds=4, audio=False)
    work, name = shortsapp.standalone_names(folder)
    wd = workflow.WORK / work
    wd.mkdir(parents=True)
    said(wd / "take1.transcript.json", "and if I am doing something for CAD I use plasticity " + TALK + " " + TALK, seconds=20)
    files = rawshorts.scan(folder)
    assert [f.name for f in files] == ["pic.mp4", "take1.mp4"]
    info = rawshorts.tell_apart(files, wd)
    rawshorts.new_project(work, name, folder, info)
    raw = shortsapp.read_raw(work, name)
    assert raw["mode"] == "raw" and [(s["id"], s["kind"]) for s in raw["sources"]] == [("t1", "talk"), ("b1", "broll")]
    assert shortsapp.video_plan(work, name)["recommended"] == 3
    text = shortsapp.find_prompt(work, name)
    assert "TALKING RECORDING t1" in text and "B-ROLL b1" in text and (wd / "shorts" / "_find" / "broll" / "b1.jpg").is_file()
    answer = tmp_path / "candidates.json"
    answer.write_text(json.dumps([cand(ranges=[{"src": "t1", "a": 0.2, "b": 16.0}], hook="why gears break",
                                        overlays=[{"src": "b1", "a": 0, "b": 3, "at": {"src": "t1", "t": 9.0}}])]), encoding="utf-8")
    assert shortsapp.import_candidates(work, name, answer) == 1
    s = shortsapp.read_raw(work, name)["shorts"][0]
    assert s["hook"] == "WHY GEARS BREAK" and s["overlays"][0]["src"] == "b1" and s["status"] == ""
    assert s["drop"] and s["drop"][0]["src"] == "t1"                                  # the restarted opening is cut out of the short
    assert shortsapp.import_candidates(work, name, answer) == 0                       # the same part again is not added twice
    assert "same part" in shortsapp.read_raw(work, name)["last_find"]["skipped"][0]


@needs_ffmpeg
def test_the_folder_job_reads_the_recordings_writes_the_project_and_asks_claude(tmp_path, monkeypatch):
    import sys
    import time
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools" / "review_app"))
    import server
    folder = tmp_path / "Job Raw"
    folder.mkdir()
    clip(folder / "take1.mp4", "red", seconds=20)
    clip(folder / "pic.mp4", "green", seconds=4, audio=False)
    canned = tmp_path / "canned"
    canned.mkdir()
    (canned / "candidates.json").write_text(json.dumps([cand(ranges=[{"src": "t1", "a": 0.2, "b": 16.0}])]), encoding="utf-8")
    monkeypatch.setenv("WOOTS_FAKE_CLAUDE", str(canned))
    work, name = shortsapp.standalone_names(folder)
    said(tmp_path / "ready.json", TALK + " " + TALK, seconds=20)                 # what transcribe.py would write for take1.mp4
    monkeypatch.setattr(server, "PY", __import__("sys").executable)
    monkeypatch.setattr(server, "TOOLS", tmp_path)                              # a stand-in transcribe.py that writes that file where it is told
    stand_in = ["import shutil, sys, pathlib",
                "out = pathlib.Path(sys.argv[sys.argv.index('--out') + 1])",
                f"shutil.copy({str(tmp_path / 'ready.json')!r}, out / 'take1.transcript.json')"]
    (tmp_path / "transcribe.py").write_text(chr(10).join(stand_in), encoding="utf-8")
    job = server.start_shorts_from_folder(str(folder))
    for _ in range(300):
        if job.get("done"):
            break
        time.sleep(0.1)
    assert job["ok"], job["log"]
    raw = shortsapp.read_raw(work, name)
    assert raw["mode"] == "raw" and len(raw["shorts"]) == 1
    assert job["key"] == f"{work}~{name}"


def test_a_newer_story_from_the_raw_footage_carries_the_hosts_brief_and_leaves_the_old_short_alone(tmp_path):
    r = workflow.create("Redo Video")
    work, name = r["work"], r["name"]
    wd = workflow.WORK / work
    tr = wd / "t.json"
    said(tr, "the gears broke then I changed the tooth shape and now they last", seconds=20)
    shortsapp.new_project(work, name, "main.mp4", str(tr), None)
    raw = shortsapp.read_raw(work, name)
    raw["shorts"] = [{"id": "s1", "title": "Gears", "hook": "H", "ranges": [[0, 6]], "status": ""}]
    shortsapp.save_raw(work, name, raw)
    with pytest.raises(ValueError, match="footage folder"):
        shortsapp.footage_folder(work, name)                                      # no footage.json yet
    folder = tmp_path / "Raw"
    folder.mkdir()
    (wd / f"{name}.footage.json").write_text(json.dumps({"folder": str(folder)}), encoding="utf-8")
    assert shortsapp.footage_folder(work, name) == str(folder)
    with pytest.raises(ValueError):
        shortsapp.raw_brief(work, name, "", "   ")
    assert shortsapp.raw_brief(work, name, "", " tell the print story ") == "tell the print story"
    b = shortsapp.raw_brief(work, name, "s1", "redo without the slicer part")
    assert "redo without the slicer part" in b and "Gears" in b and "tooth shape" in b
    # the brief reaches the raw project's prompt
    talk = tmp_path / "Raw" / "take1.mp4"
    rawtr = wd / "take1.transcript.json"
    said(rawtr, TALK, seconds=20)
    rname = "redo-raw"
    shortsapp.save_raw(work, rname, {"mode": "raw", "folder": str(folder), "source": str(talk), "transcript": str(rawtr), "speakers": "", "brief": b,
                                     "sources": [{"id": "t1", "path": str(talk), "transcript": str(rawtr), "kind": "talk", "mistakes": []}], "shorts": []})
    assert "THE HOST'S BRIEF" in shortsapp.find_prompt(work, rname) and "redo without the slicer part" in shortsapp.find_prompt(work, rname)
    assert [s["id"] for s in shortsapp.read_raw(work, name)["shorts"]] == ["s1"]   # the original project is untouched
