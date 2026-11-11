"""Notes the app carries out itself: a web page, a sound effect, another camera angle (the notes run asks for them in `edits`)."""
import json
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures"))
import make_project  # noqa: E402
import config  # noqa: E402
import makeversion  # noqa: E402
import noteactions  # noqa: E402
import reviewnotes  # noqa: E402

needs_ffmpeg = pytest.mark.skipif(not make_project.have_ffmpeg(), reason="ffmpeg missing")


def plan(r) -> dict:
    return json.loads((r["dir"] / f"{r['name']}.beatmap.json").read_text(encoding="utf-8"))


def beat(r, bid) -> dict:
    return {b["id"]: b for b in plan(r)["beats"]}[bid]


def test_times_and_well_formed_edits():
    assert noteactions.seconds_of("3:22") == 202 and noteactions.seconds_of("1:02:03") == 3723 and noteactions.seconds_of(31) == 31.0
    assert noteactions.seconds_of("soon") is None and noteactions.seconds_of(-1) is None
    ans = {"edits": [{"note": 1, "do": "web", "time": "0:31", "url": "https://a.example/"}, {"note": 1, "do": "web", "time": "x", "url": "https://a/"},
                     {"note": 2, "do": "sfx", "time": "0:31", "sound": "buzz"}, {"note": 9, "do": "sfx", "time": "0:01", "sound": "buzz"},
                     {"note": 1, "do": "dance"}, {"note": 2, "do": "angle", "file": ""}, {"note": 2, "do": "angle", "file": "PXL_1.mp4"}, "junk"]}
    got = noteactions.parse(ans, {1, 2})
    assert [(a["note"], a["do"]) for a in got] == [(1, "web"), (2, "sfx"), (2, "angle")]


def test_the_clip_playing_at_a_time_is_found():
    r = make_project.build(cut=True, title="na beat at")
    beats = plan(r)["beats"]
    starts = {b["id"]: b["start"] for b in beats}
    b, at = noteactions.beat_at(beats, starts["B02"] + 1.2)
    assert b["id"] == "B02" and at == 1.2
    assert noteactions.beat_at(beats, 999)[0]["id"] in starts


def test_a_sound_effect_goes_on_the_clip_at_that_time():
    r = make_project.build(cut=True, title="na sfx")
    sfx = config.SFX_DIR
    sfx.mkdir(parents=True, exist_ok=True)
    (sfx / "Wrong_Buzzer.wav").write_bytes(b"x")
    try:
        t = beat(r, "B02")["start"] + 0.5
        n = reviewnotes.add(r["work"], r["name"], "cut", "a negative sound here", t)
        done = noteactions.run(r["work"], r["name"], [{"note": n["id"], "do": "sfx", "time": t, "sound": "wrong buzzer"},
                                                      {"note": 77, "do": "sfx", "time": t, "sound": "applause"}], {}, log=lambda s: None)
        assert beat(r, "B02")["audio"]["sfx"] == ["Wrong_Buzzer @ 0.5"]
        assert "Wrong_Buzzer" in done["by_note"][n["id"]][0] and "preview" in done["by_note"][n["id"]][0]
        assert "applause" in done["failed"][77]
    finally:
        (sfx / "Wrong_Buzzer.wav").unlink()


def test_a_web_page_is_captured_and_put_over_the_clip(monkeypatch):
    import webcapture
    r = make_project.build(cut=True, title="na web")
    monkeypatch.setattr(webcapture, "check_url", lambda u: u)
    seen = {}

    def fake(url, out, style, find, seconds, env=None):
        seen.update(url=url, style=style, find=find)
        return {"ok": True, "file": str(Path(out) / "page.mp4"), "still": "", "url": url, "title": "Reusable spool", "seconds": 2.0, "found": True}
    monkeypatch.setattr(webcapture, "capture_apart", fake)
    t = beat(r, "B01")["start"] + 0.5
    done = noteactions.run(r["work"], r["name"], [{"note": 1, "do": "web", "time": t, "url": "https://store.example/spool", "find": "reusable  spool"}], {}, log=lambda s: None)
    ins = beat(r, "B01")["on_screen"]["broll"][-1]
    assert seen == {"url": "https://store.example/spool", "style": "scroll", "find": "reusable spool"}
    assert ins["at"] == 0.5 and ins["dur"] == 2.0 and ins["source"]["title"] == "Reusable spool" and done["changes"][0].startswith("Put the web page store.example")


def test_the_other_angle_covers_the_kept_stretches_it_was_filmed_over():
    b = {"aroll": {"in": 593.0, "out": 669.0, "keep": [[593.0, 600.0], [610.0, 640.0], [645.0, 669.0]]}}
    got = noteactions.angle_inserts(b, "PXL.mp4", 638.2, 20.9)
    assert [(x["in"], x["dur"], x["at"]) for x in got] == [(0.0, 1.8, 35.2), (6.8, 14.1, 37.0)]       # the stretch cut out in between is skipped in the clip too
    assert all(x["transition"] == "cut" and x["angle"] for x in got)
    assert noteactions.angle_inserts(b, "PXL.mp4", 700.0, 10.0) == []


def test_an_angle_is_found_near_the_note_and_only_inside_the_footage_folder(tmp_path):
    r = make_project.build(cut=True, title="na angle")
    footage = r["dir"] / "footage"
    (footage / "PXL_other.mp4").write_bytes(b"x")
    calls = []

    def find(clip, rec, lo, hi):
        calls.append(Path(rec).name)
        return (1.0, 0.8) if rec.endswith("take2.mp4") else (0.0, 0.05)
    t = beat(r, "B02")["start"]
    done = noteactions.run(r["work"], r["name"], [{"note": 5, "do": "angle", "file": str(footage / "PXL_other.mp4")}], {5: t}, log=lambda s: None,
                           find=find, length_of=lambda p: 1.5)
    ins = beat(r, "B02")["on_screen"]["broll"][0]
    assert ins["angle"] and ins["at"] == 1.0 and ins["dur"] == 1.5 and ins["in"] == 0.0 and "take2.mp4" in calls
    assert "with the sound of your take" in done["by_note"][5][0]
    outside = tmp_path / "elsewhere.mp4"
    outside.write_bytes(b"x")
    bad = noteactions.run(r["work"], r["name"], [{"note": 6, "do": "angle", "file": str(outside)}], {6: t}, log=lambda s: None, find=find, length_of=lambda p: 1.5)
    assert "footage folder" in bad["failed"][6]
    lost = noteactions.run(r["work"], r["name"], [{"note": 7, "do": "angle", "file": "PXL_other.mp4"}], {7: t}, log=lambda s: None,
                           find=lambda *a: (0.0, 0.1), length_of=lambda p: 1.5)
    assert "could not be lined up" in lost["failed"][7]


def test_a_note_whose_edit_failed_stays_open_and_says_why():
    res = {"applied_ids": [1, 2, 3], "changes": ["Cut the intro", "Added a web page", "Added a sound"], "summaries": {1: "Cut the intro", 2: "Added a web page", 3: "Added a sound"}}
    got = makeversion.after_actions(res, {"failed": {2: "the page took too long to capture"}, "by_note": {3: ["Added the sound Buzz at 0:31 (heard from the preview on)"]}},
                                    {2: 31.0})
    assert got["applied_ids"] == [1, 3]
    assert got["changes"] == ["Cut the intro", "Added the sound Buzz at 0:31 (heard from the preview on)", "Not done, the note at 0:31: the page took too long to capture"]


def test_the_brief_offers_the_edits_and_a_refusal_says_why(tmp_path):
    r = make_project.build(cut=True, title="na brief")
    w, n = r["work"], r["name"]
    a = reviewnotes.add(w, n, "cut", "show the spool page here", 1.0)
    prompt = makeversion.brief(w, n, "cut", tmp_path / "fd")
    rows = json.loads((tmp_path / "fd" / "beats.json").read_text(encoding="utf-8"))
    assert all("starts_at" in x for x in rows if not x["skipped"]) and (tmp_path / "fd" / "sounds.txt").is_file()
    assert '"do": "web"' in prompt and '"do": "angle"' in prompt and "never say it cannot be done" in prompt
    p = tmp_path / "answer.json"
    p.write_text(json.dumps({"applied": [], "skipped": [{"id": a["id"], "why": "There is no recording of the page."}]}), encoding="utf-8")
    ok, msg, _ = makeversion.apply_answer(w, n, "cut", p)
    assert not ok and msg.endswith("There is no recording of the page.")
    p.write_text(json.dumps({"applied": [{"id": a["id"], "summary": "Put the page over the clip"}],
                             "edits": [{"note": a["id"], "do": "web", "time": "0:01", "url": "https://a.example/"}]}), encoding="utf-8")
    ok, msg, res = makeversion.apply_answer(w, n, "cut", p)
    assert ok and res["actions"] == [{"note": a["id"], "do": "web", "time": "0:01", "url": "https://a.example/"}]


def test_the_make_job_does_the_edits_without_waiting_on_itself(tmp_path, monkeypatch):
    """The answer is applied under the server's lock; the edits must not take it again (that hung the job on 'Doing 3 edits')."""
    import time
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools" / "review_app"))
    import server
    r = make_project.build(cut=True, title="na job")
    t = beat(r, "B02")["start"] + 0.5
    n = reviewnotes.add(r["work"], r["name"], "cut", "a negative sound here", t)
    canned = tmp_path / "canned"
    canned.mkdir()
    (canned / "answer.json").write_text(json.dumps({"applied": [{"id": n["id"], "summary": "Added a sound"}],
                                                    "edits": [{"note": n["id"], "do": "sfx", "time": t, "sound": "applause"}]}), encoding="utf-8")
    monkeypatch.setenv("WOOTS_FAKE_CLAUDE", str(canned))
    job = server.start_make_version(r["work"], r["name"], "cut")
    end = time.time() + 20
    while not job.get("done") and time.time() < end:
        time.sleep(0.1)
    assert job.get("done") and "applause" in job["log"]                     # the edit ran (and failed: there is no such sound), the job finished
    assert server._lock.acquire(timeout=1)
    server._lock.release()


@needs_ffmpeg
def test_two_recordings_are_lined_up_by_their_sound(tmp_path):
    import wave
    import anglesync
    rng = np.random.default_rng(3)
    sr = 8000
    x = np.zeros(sr * 40, np.float32)
    t = 0
    while t < sr * 39:                                                     # speech-like bursts and gaps
        n = int(rng.uniform(0.08, 0.4) * sr)
        x[t:t + n] = rng.normal(0, 3000, n) * np.hanning(n)
        t += n + int(rng.uniform(0.05, 0.5) * sr)

    def save(p, y):
        with wave.open(str(p), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(sr)
            w.writeframes(np.clip(y, -32000, 32000).astype(np.int16).tobytes())
    main, phone = tmp_path / "main.wav", tmp_path / "phone.wav"
    save(main, x)
    save(phone, 0.4 * x[int(sr * 22.5): int(sr * 34.5)] + rng.normal(0, 300, int(sr * 12)))    # a quieter phone that filmed 22.5 s to 34.5 s
    start, score = anglesync.locate(phone, main, 10, 40)
    assert abs(start - 22.5) < 0.02 and score >= anglesync.MIN_SCORE
    assert anglesync.locate(phone, main, 0, 15)[1] < anglesync.MIN_SCORE                       # a stretch it did not film
