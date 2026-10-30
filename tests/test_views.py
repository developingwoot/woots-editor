import views


def job(**kw):
    base = {"pipeline": "final", "log": "", "done": False, "ok": None, "step": 0, "steps": ["a", "b", "c", "d"], "started": 1000.0}
    base.update(kw)
    return base


def test_running_job_has_sentence_progress_and_whole_minute_estimate():
    v = views.job_sentence(job(step=2), now=1000.0 + 5 * 60)
    assert v["state"] == "running" and v["sentence"] == "Rendering the final video"
    assert v["progress"] == 0.5 and v["estimate"] == "about 10 min"


def test_single_step_job_has_unknown_progress():
    assert views.job_sentence(job(steps=["x"]), now=1000.0)["progress"] is None


def test_done_and_failed_jobs():
    assert views.job_sentence(job(done=True, ok=True))["sentence"] == "Final video rendered"
    bad = views.job_sentence(job(done=True, ok=False, log="Traceback boom"))
    assert bad["state"] == "failed" and "Traceback" not in bad["error"] and bad["details"] == "Traceback boom"


def test_unknown_pipeline_still_gets_a_plain_sentence():
    assert views.job_sentence(job(pipeline="mystery"), now=1000.0)["sentence"] == "Working"


def test_times_never_show_decimals():
    assert views.time_text(42.4) == "0:42" and views.time_text(3909) == "1:05:09"
    assert views.minutes_text(0.2) == "less than a minute" and views.minutes_text(3.6) == "about 4 min"


def test_fake_claude_copies_the_canned_answer_and_runs_apply(tmp_path, monkeypatch):
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools" / "review_app"))
    import server
    canned = tmp_path / "canned"
    canned.mkdir()
    (canned / "out.json").write_text('{"ok": 1}', encoding="utf-8")
    monkeypatch.setenv("WOOTS_FAKE_CLAUDE", str(canned))
    job = {"log": "", "ok": None}
    seen = []
    server._claude_run(job, tmp_path / "run", "prompt", "out.json", lambda p, r: (seen.append(p.read_text(encoding="utf-8")) or True, "applied"))
    assert seen == ['{"ok": 1}'] and job["ok"] is True and job["log"] == "applied"
    job2 = {"log": "", "ok": None}
    server._claude_run(job2, tmp_path / "run2", "prompt", "missing.json", lambda p, r: (True, ""))
    assert job2["ok"] is False


def _facts(**kw):
    base = {"work": "w", "name": "n", "title": "T", "outline": False, "clips": False, "cut": False, "preview": False, "final": False,
            "shorts_approved": 0, "finished": False}
    base.update(kw)
    return base


def test_step_of_follows_what_exists():
    cases = [({}, "outline", "Outline: not started"),
             ({"outline": True}, "footage", "Outline written: add your footage next"),
             ({"outline": True, "clips": True}, "footage", "Footage read: ready to make the rough cut"),
             ({"outline": True, "clips": True, "cut": True}, "rough-cut", "Rough cut ready to watch"),
             ({"outline": True, "clips": True, "cut": True, "preview": True}, "preview", "Preview ready to watch"),
             ({"outline": True, "clips": True, "cut": True, "preview": True, "final": True}, "final", "Final rendered: publishing details ready"),
             ({"final": True, "shorts_approved": 3}, "shorts", "Shorts: 3 approved")]
    for kw, step, sentence in cases:
        s = views.step_of(_facts(**kw))
        assert (s["step"], s["sentence"]) == (step, sentence), kw
        assert [d["id"] for d in s["steps"]] == views.STEP_IDS and sum(d["current"] for d in s["steps"]) == 1


def test_dots_mark_steps_that_have_a_result():
    s = views.step_of(_facts(outline=True, clips=True))
    assert [d["dot"] for d in s["steps"]] == ["result", "result", "none", "none", "none", "none"]


def test_a_running_job_takes_over_the_sentence():
    s = views.step_of(_facts(outline=True, clips=True, cut=True), job(pipeline="preview", started=1e12))
    assert s["step"] == "preview" and s["sentence"].startswith("Claude is working: making the preview")


def test_keys_round_trip():
    assert views.split_key(views.key_of("a-b", "a-b")) == ("a-b", "a-b")


def test_home_lists_videos_by_stage_and_folds_finished_ones():
    import workflow
    a = workflow.create("Home Alpha")
    b = workflow.create("Home Beta")
    (workflow.WORK / a["work"] / f"{a['name']}.script.md").write_text("x", encoding="utf-8")
    (workflow.WORK / b["work"] / "FINALIZED.json").write_text("{}", encoding="utf-8")
    h = views.home()
    cards = {c["title"]: c for c in h["videos"]}
    assert cards["Home Alpha"]["step"] == "footage" and cards["Home Alpha"]["button"] == "Add footage"
    assert "Home Beta" not in cards and "Home Beta" in [c["title"] for c in h["done"]]
    assert views.split_key(cards["Home Alpha"]["key"]) == (a["work"], a["name"])
