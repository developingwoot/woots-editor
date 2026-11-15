"""Audience retention: the export is read whatever its shape, the moments that matter are found, and each is lined up with the final."""
import io
import json
import zipfile

import pytest

import config
import retention
import views
import workflow


def _curve(n=101, total=600.0, dips=(), bumps=()):
    """A graph that falls fast for the first 5%, then slowly; `dips` and `bumps` are (position 0..1, size)."""
    out, v = [], 1.0
    for i in range(n):
        p = i / (n - 1)
        v -= 0.05 if p <= 0.05 else 0.003
        v -= sum(size for at, size in dips if abs(p - at) < 0.004)
        v += sum(size for at, size in bumps if abs(p - at) < 0.004)
        out.append((round(p * total, 2), round(v, 4)))
    return out


def test_the_studio_export_is_read_as_percent_of_the_video_and_percent_of_viewers():
    text = "Video position (%),Absolute audience retention (%),Relative audience retention (%)\n" + "\n".join(f"{i},{100 - i * 0.5},50" for i in range(0, 101))
    pts = retention.parse(text)
    assert len(pts) == 101 and pts[0] == ((0.0, "percent"), 1.0) and pts[100] == ((100.0, "percent"), 0.5)
    assert retention.normalise(pts, 600.0)[50] == (300.0, 0.75)


def test_other_shapes_are_read_too_a_zip_times_a_ratio_table_and_the_api():
    rows = "\n".join(f"{i // 60}:{i % 60:02d}\t{90 - i / 10:.1f}%" for i in range(0, 600, 30))
    assert retention.parse("Time\tAudience retention\n" + rows)[2] == ((60.0, "seconds"), 0.84)
    ratio = "elapsedVideoTimeRatio;audienceWatchRatio;relativeRetentionPerformance\n" + "\n".join(f"0,{i:02d};1,{20 - i};0,5".replace("1,", "1.", 1) for i in range(1, 11))
    assert retention.parse(ratio)[0][0] == (0.01, "ratio")
    api = json.dumps({"columnHeaders": [{"name": "elapsedVideoTimeRatio"}, {"name": "audienceWatchRatio"}], "rows": [[i / 100, 1.2 - i / 100] for i in range(1, 101)]})
    got = retention.parse(api)
    assert got[0] == ((0.01, "ratio"), 1.19) and len(got) == 100                         # over 100% at the start (people rewatch the opening) stays a ratio
    z = io.BytesIO()
    with zipfile.ZipFile(z, "w") as f:
        f.writestr("Totals.csv", "Views,100\n")
        f.writestr("Chart data.csv", "Video position (%),Absolute audience retention (%)\n" + "\n".join(f"{i},{100 - i}" for i in range(0, 50)))
    assert len(retention.parse(z.getvalue())) == 50


def test_a_file_without_a_graph_is_refused_in_plain_words():
    for bad in ("Views,Watch time\n100,5", "", b"PK not a zip"):
        with pytest.raises(ValueError):
            retention.parse(bad)


def test_drops_and_spikes_are_found_against_the_usual_decline_and_the_hook_is_separate():
    got = retention.analyse(_curve(dips=[(0.40, 0.04)], bumps=[(0.70, 0.02)]), 600.0)
    assert got["hook"] == pytest.approx(0.7, abs=0.01) and got["hook_s"] == 30.0
    assert [round(d["t"]) for d in got["drops"]] == [234] and got["drops"][0]["lost"] == pytest.approx(0.04, abs=0.005)      # the steep opening is the hook, not a drop
    assert len(got["spikes"]) == 1 and 410 < got["spikes"][0]["t"] < 425
    flat = retention.analyse(_curve(), 600.0)
    assert flat["drops"] == [] and flat["spikes"] == []


def _final(title):
    r = workflow.create(title)
    w, n = r["work"], r["name"]
    wd = config.WORK / w
    (wd / "My video v1 (1080p).final.json").write_text(json.dumps({"version": "1", "dur": "400", "chapters": []}), encoding="utf-8")
    (wd / "My video v2 (1080p).final.json").write_text(json.dumps({"version": "2", "dur": "600.0", "chapters": [{"t": 0.0, "title": "Intro"}, {"t": 200.0, "title": "Setup"}]}), encoding="utf-8")
    (wd / "My video v2 (1080p).transcript.json").write_text(json.dumps({"segments": [{"text": "Now we wait for the download.", "start": 236.0, "end": 239.0},
                                                                                       {"text": "Here is the first print.", "start": 418.0, "end": 420.0}]}), encoding="utf-8")
    return w, n


def test_a_moment_is_lined_up_with_what_the_newest_final_says():
    w, n = _final("ret facts")
    facts = retention.final_facts(w, n)
    assert facts["dur"] == 600.0 and len(facts["chapters"]) == 2 and facts["changes"] == []          # no sections folder: no picture, the rest still works
    at = retention.what_at(facts, 234.0, 240.0)
    assert at["said"] == "Now we wait for the download." and at["chapter"] == "Setup" and at["picture"] == ""
    facts["changes"] = [0.0, 200.0, 260.0, 262.0]
    assert retention.what_at(facts, 234.0)["picture"] == "the same picture for 60 seconds" and retention.what_at(facts, 261.0)["picture"] == "the picture was changing"


def test_an_import_is_kept_and_the_final_screen_shows_it():
    w, n = _final("ret view")
    assert views.final(w, n)["retention"] == {"has": False, "can": True}
    text = "Video position (%),Absolute audience retention (%)\n" + "\n".join(f"{100 * t / 600:.2f},{100 * v:.2f}" for t, v in _curve(dips=[(0.40, 0.04)], bumps=[(0.70, 0.02)]))
    retention.save(w, n, text.encode("utf-8"), source="Chart data.csv")
    v = views.final(w, n)["retention"]
    assert v["has"] and v["hook"] == {"share": "70%", "at": "30 seconds"} and len(v["curve"]) == 101 and v["source"] == "Chart data.csv"
    kinds = [(m["kind"], m["chapter"]) for m in v["moments"]]
    assert kinds == [("drop", "Setup"), ("spike", "Setup")] and "download" in v["moments"][0]["said"] and "first print" in v["moments"][1]["said"]
    assert v["others"] == [] and "only video imported" in v["note"]
    assert [o["key"] for o in retention.overview() if o["key"] == views.key_of(w, n)] == [views.key_of(w, n)]


def test_a_video_without_a_final_cannot_take_an_import():
    r = workflow.create("ret none")
    assert views.final(r["work"], r["name"])["retention"] == {"has": False, "can": False}
    with pytest.raises(ValueError, match="render the final first"):
        retention.save(r["work"], r["name"], "a,b\n1,2")
