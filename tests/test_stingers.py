"""Stingers: branded animations made once (HyperFrames) that cover the cut into and out of a cutaway."""
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures"))
import make_project  # noqa: E402
import config  # noqa: E402
import stingers  # noqa: E402
import transitions  # noqa: E402

needs_ffmpeg = pytest.mark.skipif(not make_project.have_ffmpeg(), reason="ffmpeg missing")
BRAND = {"colors": {"primary": "#142C44", "accent": "#E2703A", "light": "#F4EDE4", "dark": "#000000"}, "font": str(Path(__file__).resolve().parent.parent / "fonts" / "Oswald-Bold.ttf"),
         "name": "Sam & Co <Workshop>"}


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    monkeypatch.setattr(stingers, "brand", lambda: dict(BRAND, colors=dict(BRAND["colors"])))
    shutil.rmtree(stingers.OUT, ignore_errors=True)
    config.save_user_settings({"transition_web": "", "transition_broll": ""})
    yield
    shutil.rmtree(stingers.OUT, ignore_errors=True)
    config.save_user_settings({"transition_web": "", "transition_broll": ""})


def fake_render(calls):
    """Stands in for HyperFrames: writes the .mov the command names."""
    def run(cmd, **kw):
        calls.append(cmd)
        if "render" in cmd:
            Path(cmd[cmd.index("-o") + 1]).write_bytes(b"mov")
        return SimpleNamespace(returncode=0, stdout="", stderr="")
    return run


def test_the_starter_templates_are_filled_with_the_brand():
    assert {"sweep", "stripes", "iris", "name"} <= set(stingers.templates())
    d = stingers.prepare("name", BRAND)
    page = (d / "index.html").read_text(encoding="utf-8")
    assert "#142C44" in page and "#E2703A" in page and "__" not in page.replace("__timelines", "")
    assert "Sam &amp; Co &lt;Workshop&gt;" in page and (d / "font.ttf").is_file()


def test_each_picture_is_taken_when_the_stinger_shows_best():
    assert stingers.still_at("name") == 0.5 and stingers.still_at("sweep") == 0.15
    cmd = stingers.still_cmd("name", Path("d"), 0.5)
    assert "trim=start=0.50" in " ".join(cmd) and "-ss" not in cmd       # trimmed and restarted at 0, so it lines up with the grey ground


def test_they_are_made_once_and_again_when_the_brand_changes():
    calls = []
    assert stingers.file_of("sweep") is None
    got = stingers.make(["sweep"], run=fake_render(calls), log=lambda s: None)
    assert got == {"sweep": "made"} and stingers.file_of("sweep") and "--format" in calls[0] and "mov" in calls[0]
    assert stingers.make(["sweep"], run=fake_render(calls), log=lambda s: None) == {"sweep": "ready"}
    old = stingers.file_of("sweep").parent
    BRAND["colors"]["accent"] = "#00AA00"
    try:
        assert stingers.file_of("sweep") is None                           # a new colour: not made for this brand
        stingers.make(["sweep"], run=fake_render(calls), log=lambda s: None)
        assert stingers.file_of("sweep") and not old.exists()               # the old brand's render is cleared away
    finally:
        BRAND["colors"]["accent"] = "#E2703A"


def test_a_render_that_makes_nothing_is_tried_once_more_then_reported():
    calls = []

    def flaky(cmd, **kw):
        calls.append(cmd)
        if "render" in cmd and len([c for c in calls if "render" in c]) == 2:
            Path(cmd[cmd.index("-o") + 1]).write_bytes(b"mov")
        return SimpleNamespace(returncode=0, stdout="", stderr="")
    assert stingers.make(["iris"], run=flaky, log=lambda s: None) == {"iris": "made"}
    failing = lambda cmd, **kw: SimpleNamespace(returncode=1, stdout="", stderr="Chrome crashed")  # noqa: E731
    assert stingers.make(["stripes"], run=failing, log=lambda s: None) == {"stripes": "Chrome crashed"}


def test_only_files_in_the_stingers_folder_are_served():
    stingers.make(["sweep"], run=fake_render([]), log=lambda s: None)
    f = stingers.file_of("sweep")
    assert stingers.served(f"{f.parent.name}/sweep.mov") == f
    for bad in ("../settings.json/x.png", f"{f.parent.name}/../../x.png", f"{f.parent.name}/index.html", "a/b/c.png", ""):
        assert stingers.served(bad) is None


def test_a_stinger_not_made_yet_is_a_slide_and_a_made_one_carries_its_file():
    lib = transitions.library()
    p = transitions.pick({"file": "x", "transition": "brand-sweep"}, lib)
    assert p["kind"] == "slide" and p["instead_of"] == "brand-sweep"
    stingers.make(["sweep"], run=fake_render([]), log=lambda s: None)
    p = transitions.pick({"file": "x", "transition": "brand-sweep"}, lib)
    assert p["kind"] == "stinger" and p["file"] == str(stingers.file_of("sweep")) and p["cover"] == 0.4
    rows = {r["id"]: r for r in transitions.view()["presets"]}
    assert rows["brand-sweep"]["ready"] and not rows["brand-iris"]["ready"]


def test_the_cutaway_switches_at_the_cover_moment_inside_the_segment():
    st = {"kind": "stinger", "file": "s.mov", "dur": 0.8, "cover": 0.4, "sound": "whoosh"}
    br = {"at": 0.1, "dur": 3.9, "t_in": st, "t_out": st}
    at, dur, plays = transitions.stinger_times(br, D=4.0)
    assert at == 0.4 and plays[0] == ("s.mov", 0.0)                      # moved in so the stinger starts with the segment
    assert round(at + dur, 3) == 3.6 and plays[1] == ("s.mov", 3.2)       # ends early enough for the stinger to finish inside the segment
    assert transitions.sound_times({"at": 1.0, "dur": 2.0, "t_in": st, "t_out": st}) == [(0.6, "whoosh"), (2.6, "whoosh")]
    pieces = transitions.stamp([{"at": 1.0, "dur": 0.6}], {**st, "id": "brand-sweep", "label": "x", "from": "right"})
    assert pieces[0]["t_in"]["file"] == "s.mov" and pieces[0]["t_out"]["cover"] == 0.4


def test_making_a_stinger_puts_out_of_date_the_sections_that_use_it():
    import json
    import sections
    r = make_project.build(cut=True, title="stinger sig")
    p = r["dir"] / f"{r['name']}.beatmap.json"
    bm = json.loads(p.read_text(encoding="utf-8"))
    bm["beats"][0]["on_screen"]["broll"] = [{"file": "take3.mp4", "in": 0.0, "dur": 1.5, "at": 0.5, "transition": "brand-iris"}]
    p.write_text(json.dumps(bm), encoding="utf-8")
    before = {s["id"]: s["sig"] for s in sections.plan(r["work"], r["name"], write=False)["sections"]}
    stingers.make(["iris"], run=fake_render([]), log=lambda s: None)
    after = {s["id"]: s["sig"] for s in sections.plan(r["work"], r["name"], write=False)["sections"]}
    assert len([k for k in before if before[k] != after[k]]) == 1


@needs_ffmpeg
def test_a_stinger_covers_the_cut_in_a_rendered_segment(tmp_path):
    import sectionrender
    a, b, s = tmp_path / "a.mp4", tmp_path / "b.mp4", tmp_path / "s.mov"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=blue:s=320x180:r=30:d=3", "-f", "lavfi", "-i", "sine=d=3", "-shortest", str(a)], check=True)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=green:s=320x180:r=30:d=3", str(b)], check=True)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=red:s=1920x1080:r=30:d=0.8,format=rgba", "-c:v", "qtrle", str(s)], check=True)
    st = {"kind": "stinger", "file": str(s), "dur": 0.8, "cover": 0.4, "sound": "none"}
    out = tmp_path / "out.mp4"
    sectionrender.render_segment({"size": [320, 180], "fps": 30}, {"id": "B01", "src": str(a)}, 0.0, 3.0, out,
                                 [{"seg": "B01", "file": str(b), "in": 0.0, "dur": 1.5, "at": 1.0, "t_in": st}], [], 0.0)

    def colour(t):
        raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", str(t), "-i", str(out), "-frames:v", "1", "-vf", "scale=1:1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                             capture_output=True).stdout
        return max(range(3), key=lambda i: raw[i])
    assert colour(0.3) == 2 and colour(0.8) == 0 and colour(2.0) == 1        # host (blue), the stinger (red) over the cut, then the cutaway (green)
