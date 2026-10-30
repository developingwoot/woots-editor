"""Build a throwaway `zz-demo` project for tests: a workflow state, an outline, and three tiny ffmpeg test clips with tone audio.
Later phases add transcripts, clips.json, a beat map and a half-res preview here. Call build() with the data root already set."""
import shutil
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
TITLE = "zz demo"


def have_ffmpeg() -> bool:
    return shutil.which("ffmpeg") is not None


def make_clip(path: Path, seconds: int, freq: int) -> None:
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"testsrc=size=320x180:rate=15:duration={seconds}",
           "-f", "lavfi", "-i", f"sine=frequency={freq}:duration={seconds}", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
           "-shortest", str(path)]
    subprocess.run(cmd, check=True)


def build(clips: bool = True, preview: bool = False, title: str = TITLE, cut: bool = False) -> dict:
    """Returns {'work': slug, 'name': slug, 'dir': Path}. Needs ffmpeg when clips or preview is True.
    cut=True also writes footage.json, clips.json (three takes, S01 has two candidate takes) and a beat map of three clips plus one teaching
    voice-over (TP01); it implies clips. preview=True also writes a 9 s stitched preview (the three clips joined) with its stitch.json of three sections."""
    import workflow
    r = workflow.create(title)
    d = workflow.WORK / r["work"]
    shutil.copyfile(HERE / "outline_sample.md", d / f"{r['name']}.script.md")
    footage = d / "footage"
    footage.mkdir(exist_ok=True)
    if clips or cut:
        for i, freq in enumerate((220, 330, 440), start=1):
            make_clip(footage / f"take{i}.mp4", 3, freq)
    if cut:
        _write_cut_plan(d, r["name"], footage)
    if preview:
        import json
        lst = d / "concat.txt"
        lst.write_text("".join(f"file '{(footage / f'take{i}.mp4').as_posix()}'\n" for i in (1, 2, 3)), encoding="utf-8")
        out = d / f"{r['name']}.preview-half.mp4"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(lst), "-c:v", "libx264", "-pix_fmt", "yuv420p",
                        "-c:a", "aac", str(out)], check=True)
        stitch = {"file": out.name, "dur": 9.0, "sections": [{"id": f"S{i}", "title": f"Part {i}", "start": 3.0 * (i - 1), "dur": 3.0, "beats": []}
                                                           for i in (1, 2, 3)]}
        (d / f"{r['name']}.stitch.json").write_text(json.dumps(stitch), encoding="utf-8")
        for i in (1, 2, 3):                                  # what selfreview.timeline / finalrender read for each section
            sb = d / "sections" / r["name"] / f"S{i}"
            (sb / "out").mkdir(parents=True, exist_ok=True)
            (sb / "section.edit.json").write_text(json.dumps({"size": [960, 540], "fps": 30, "segments": [], "overlays": [], "broll": []}), encoding="utf-8")
            seg = {"id": f"B0{i}", "out_start": 0.0, "out_dur": 3.0, "src": str(footage / f"take{i}.mp4"), "in": 0.0, "out": 3.0}
            (sb / "out" / "render.json").write_text(json.dumps({"segments": [seg], "dur": 3.0}), encoding="utf-8")
    return {**r, "dir": d}


def _write_cut_plan(d: Path, name: str, footage: Path) -> None:
    import json
    import beatmap
    (d / f"{name}.footage.json").write_text(json.dumps({"folder": str(footage)}), encoding="utf-8")

    def span(sid, lines, text, restarts=0):
        return {"id": sid, "start": 0.0, "end": 3.0, "dur": 3.0, "text": text, "script_lines": lines, "coverage": {ln: 1.0 for ln in lines},
                "restarts": restarts, "flags": [], "confidence": 0.9}
    clips = {"folder": str(footage), "clips": [
        {"rel": "take1.mp4", "name": "take1.mp4", "dur": 3.0, "role": "aroll", "spans": [span("spA", ["S01"], "we start with the tape shirt")]},
        {"rel": "take2.mp4", "name": "take2.mp4", "dur": 3.0, "role": "aroll", "spans": [span("spB", ["S01", "S02"], "the tape shirt again", 1)]},
        {"rel": "take3.mp4", "name": "take3.mp4", "dur": 3.0, "role": "aroll", "spans": [span("spC", ["S03"], "and then the end")]}],
        "by_line": {"S01": {"candidates": ["spA", "spB"], "picked": "spA", "picked_by": "auto"},
                    "S02": {"candidates": ["spB"], "picked": "spB", "picked_by": "auto"},
                    "S03": {"candidates": ["spC"], "picked": "spC", "picked_by": "auto"}}}
    (d / f"{name}.clips.json").write_text(json.dumps(clips), encoding="utf-8")

    def aroll(rel, sid):
        return {"rel": rel, "in": 0.0, "out": 3.0, "dur": 3.0, "span": sid, "span_in": 0.0, "span_out": 3.0, "keep": None, "words": []}
    beats = [beatmap.blank_beat("B01", "Intro", ["S01"], "we start with the tape shirt", aroll("take1.mp4", "spA"), 3.0, False, []),
             beatmap.blank_beat("B02", "Intro", ["S02"], "the tape shirt again", aroll("take2.mp4", "spB"), 3.0, False, []),
             beatmap.blank_beat("B03", "Middle", ["S03"], "and then the end", aroll("take3.mp4", "spC"), 3.0, False, [])]
    tp = beatmap.blank_beat("TP01", "Middle", [], "Pressure advance is how the printer keeps up", None, 1.5, False, [])
    tp["vo"] = {"id": "TP01", "file": "take1.mp4", "start": 0.0, "end": 1.5, "after": "S02", "words": [], "term": "pressure advance"}
    tp["on_screen"] = {"shot": "b-roll", "note": "", "broll": [{"file": "take3.mp4", "in": 0.0, "dur": 1.5, "why": "take2 close up"}]}
    beats.insert(2, tp)
    beatmap.retime(beats)
    data = {"version": 1, "generated": "x", "beats": beats, "orphans": [], "changes": []}
    (d / f"{name}.beatmap.json").write_text(json.dumps(data), encoding="utf-8")


def add_final(d: Path, name: str, title: str, version: int = 1) -> Path:
    """A stand-in for a finished full-quality render: a copy of the stitched preview named the way finalrender names its output."""
    import json
    out = d / f"{title} v{version} (1080p).mp4"
    shutil.copyfile(d / f"{name}.preview-half.mp4", out)
    out.with_name(out.stem + ".final.json").write_text(json.dumps({"version": version, "dur": 9.0}), encoding="utf-8")
    return out


FOOTAGE_OUTLINE = "\n".join([
    "Title: Gears that last", "", "🎬 Intro: The hook", "", "[VISUAL: Cut to A-Roll]", "", "SAM (A-ROLL):", '"we start with the tape shirt on the desk"', "",
    "[VISUAL: close up of gears turning]", "", "SAM (VO):", '"then the gears kept breaking again and again"', "",
    "⚙️ Part 2: The fix", "", "[VISUAL: a rainbow unicorn dancing]", "", "SAM (A-ROLL):", '"so I changed the tooth shape and it worked"', ""])
SAID = ["we start with the tape shirt on the desk", "then the gears kept breaking again and again", "so I changed the tooth shape and it worked"]


def build_footage(title: str = "zz footage") -> dict:
    """A video at the footage step: the outline above, three recordings whose words match its three spoken lines (already read), and two silent
    B-roll clips in 'B Roll' (not looked at yet). No clips.json and no beat map: 'Make the rough cut' makes them."""
    import json
    import workflow
    r = workflow.create(title)
    d = workflow.WORK / r["work"]
    (d / f"{r['name']}.script.md").write_text(FOOTAGE_OUTLINE, encoding="utf-8")
    footage = d / "footage"
    (footage / "B Roll").mkdir(parents=True, exist_ok=True)
    analysis = {}
    for i, (said, freq) in enumerate(zip(SAID, (220, 330, 440)), start=1):
        make_clip(footage / f"take{i}.mp4", 3, freq)
        words = [[w, round(0.2 + k * 0.3, 2), round(0.2 + k * 0.3 + 0.25, 2)] for k, w in enumerate(said.split())]
        analysis[f"take{i}.mp4"] = {"dur": 3.0, "words": len(words), "text": said, "first": words[0][1], "last": words[-1][2], "restarts": 0, "restart_at": [],
                                    "pauses": 0, "wpm": 150, "trim": [0.0, 3.0], "list": words}
    make_clip(footage / "B Roll" / "gears close up.mp4", 3, 550)
    make_clip(footage / "B Roll" / "workbench wide.mp4", 3, 660)
    (d / f"{r['name']}.footage.json").write_text(json.dumps({"folder": str(footage), "analysis": analysis}), encoding="utf-8")
    return {**r, "dir": d}
