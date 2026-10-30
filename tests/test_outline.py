import json
import sys
from collections import Counter
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures"))
import make_project  # noqa: E402
import outline  # noqa: E402
import projectstore  # noqa: E402
import scriptedit  # noqa: E402
import views  # noqa: E402

SAMPLE = (Path(__file__).resolve().parent / "fixtures" / "outline_sample.md").read_text(encoding="utf-8")
OLD = """# My Video — script DRAFT 1

Logline: A maker fails four times.
Thesis (from Sam): iterate.
Promise to the viewer: you will know why it fails.
Title options: (1) One (2) Two

---

## COLD OPEN (0:00 - 0:12)

S01 And honestly, this was the point where I wanted to give up. It was bad.
[NOTE: the video opens here]

## WHY A WHALE SHARK (0:12 - 0:55)

[VISUAL: the whale shark on a desk]
S02 First I wanted a whale shark.
[NOTE: TP01 | line S02 | term: flexi | VO (Sam): "A flexi is a printed toy that bends." | graphic: none]
"""


def types(sec):
    return Counter(i["type"] for i in sec["items"])


def test_the_sample_has_the_header_seven_sections_and_each_part():
    m = outline.parse(SAMPLE)
    assert m["format"] == "outline"
    assert m["header"]["title"]["text"] == "Which Soldering Iron Should You Buy? I Tested Ten of Them"
    assert m["header"]["thumbnail"]["text"].startswith("Two irons side by side")
    assert [s["title"] for s in m["sections"]] == ["Intro: The Soldering Test", "Tier 1: The Starter Irons", "Tier 2: The Temperature-Controlled Stations",
                                                   "Tier 3: The Odd Ones", "Tier 4: Budget Against Brand Name",
                                                   "Tier 5: The Ones I Would Not Buy Twice", "The Official Ranking"]
    assert [s["icon"][0] for s in m["sections"]] == ["🎬", "⏱", "⚙", "🧪", "🥊", "🎨", "📊"]
    assert types(m["sections"][0]) == {"visual": 2, "aroll": 3, "graphic": 1}
    assert types(m["sections"][1]) == {"entry": 2, "data": 2, "visual": 4, "vo": 2, "aroll": 2}
    assert types(m["sections"][6]) == {"visual": 10, "aroll": 2, "vo": 7}
    assert sum(types(s)["aroll"] for s in m["sections"]) == 15 and sum(types(s)["vo"] for s in m["sections"]) == 18
    data = [i["text"] for i in m["sections"][1]["items"] if i["type"] == "data"]
    assert data[0] == "Time: 12 Mins | Price: Under $15 | Category: Fixed Temperature"
    entries = [i["text"] for i in m["sections"][2]["items"] if i["type"] == "entry"]
    assert entries == ["Fixed Station", "Smart Station"]
    first = m["sections"][0]["items"]
    assert first[0]["text"].startswith("Fast-paced montage") and not first[0]["text"].endswith("]")
    assert first[1]["type"] == "aroll" and first[1]["text"].startswith("If you ask ten different") and not first[1]["text"].startswith('"')


def test_every_section_of_the_sample_has_a_shot_and_the_time_is_an_estimate():
    m = outline.parse(SAMPLE)
    assert outline.gaps(m) == 0
    assert 40 < outline.seconds(m["sections"][0]) < 60


def test_old_script_format_reads_into_the_same_model():
    m = outline.parse(OLD)
    assert m["format"] == "script"
    assert m["header"]["logline"]["text"] == "A maker fails four times." and m["header"]["thesis"]["text"] == "iterate."
    assert m["header"]["promise"]["text"] == "you will know why it fails." and "title" not in m["header"]
    assert [(s["title"], s["time"]) for s in m["sections"]] == [("COLD OPEN", "0:00 - 0:12"), ("WHY A WHALE SHARK", "0:12 - 0:55")]
    assert types(m["sections"][1]) == {"visual": 1, "aroll": 1, "teaching": 1}
    assert next(i["text"] for i in m["sections"][1]["items"] if i["type"] == "teaching") == "A flexi is a printed toy that bends."
    assert m["sections"][0]["items"][0]["text"] == "And honestly, this was the point where I wanted to give up. It was bad."     # the id S01 is not part of the words
    assert outline.gaps(m) == 1                                                                                                  # COLD OPEN has no shot idea


def test_text_that_is_not_an_outline_has_no_sections():
    assert outline.parse("x")["sections"] == [] and outline.parse("")["sections"] == []


# ----------------------------------------------------------------------------- edits
def project(title, text=SAMPLE):
    r = make_project.build(clips=False, title=title)
    scriptedit.script_path(r["work"], r["name"]).write_text(text, encoding="utf-8")
    return r["work"], r["name"], r["dir"]


def item(m, sec, kind, n=0):
    return [i for i in m["sections"][sec]["items"] if i["type"] == kind][n]


def test_edit_a_shot_a_talking_point_and_a_voice_over_keeps_the_layout_and_saves_versions():
    w, n, d = project("ol edits")
    m = outline.load(w, n)
    v, a, vo = item(m, 1, "visual"), item(m, 1, "aroll"), item(m, 1, "vo")
    outline.apply_op(w, n, "set_item", {"line": v["line"], "raw": v["raw"], "text": "A new shot idea"})
    m2 = outline.load(w, n)
    assert item(m2, 1, "visual")["raw"] == "[VISUAL: A new shot idea]" and len(m2["sections"]) == 7
    a = item(m2, 1, "aroll")
    outline.apply_op(w, n, "set_item", {"line": a["line"], "raw": a["raw"], "text": "Short and sweet."})
    lines = (d / f"{n}.script.md").read_text(encoding="utf-8").splitlines()
    assert lines[a["line"]] == a["raw"] and lines[a["line"] + 1] == '"Short and sweet."'                  # label kept, quotes kept
    vo = item(outline.load(w, n), 1, "vo")
    outline.apply_op(w, n, "set_item", {"line": vo["line"], "raw": vo["raw"], "text": "A voice-over."})
    assert item(outline.load(w, n), 1, "vo")["text"] == "A voice-over."
    assert len(scriptedit.history(w, n)) >= 3 and any(e["file"].endswith(".script.md") for e in projectstore.history(d))


def test_edit_refuses_a_line_that_changed_and_a_line_that_is_gone():
    w, n, d = project("ol stale")
    v = item(outline.load(w, n), 0, "visual")
    outline.apply_op(w, n, "set_item", {"line": v["line"], "raw": v["raw"], "text": "First change"})
    with pytest.raises(ValueError, match="changed since you loaded"):
        outline.apply_op(w, n, "set_item", {"line": v["line"], "raw": v["raw"], "text": "Second change"})
    with pytest.raises(ValueError, match="not in the outline"):
        outline.apply_op(w, n, "set_item", {"line": 9999, "raw": "x", "text": "y"})
    with pytest.raises(ValueError):
        outline.apply_op(w, n, "set_item", {"line": v["line"], "raw": "[VISUAL: First change]", "text": "  "})
    with pytest.raises(ValueError, match="unknown operation"):
        outline.apply_op(w, n, "explode", {})


def test_add_a_shot_to_a_section_and_delete_a_line():
    w, n, d = project("ol add delete", OLD)
    m = outline.load(w, n)
    assert outline.gaps(m) == 1
    outline.apply_op(w, n, "add_visual", {"section": "s1", "text": "Sam at the desk"})
    m = outline.load(w, n)
    assert outline.gaps(m) == 0 and item(m, 0, "visual")["text"] == "Sam at the desk" and len(m["sections"]) == 2
    s = item(m, 0, "visual")
    outline.apply_op(w, n, "delete_item", {"line": s["line"], "raw": s["raw"]})
    assert outline.gaps(outline.load(w, n)) == 1
    with pytest.raises(ValueError):
        outline.apply_op(w, n, "add_visual", {"section": "s99", "text": "x"})


def test_old_format_talking_point_keeps_its_id_when_edited():
    w, n, d = project("ol old edit", OLD)
    a = item(outline.load(w, n), 0, "aroll")
    outline.apply_op(w, n, "set_item", {"line": a["line"], "raw": a["raw"], "text": "Sam says it differently now."})
    assert "S01 Sam says it differently now." in (d / f"{n}.script.md").read_text(encoding="utf-8")
    t = item(outline.load(w, n), 1, "teaching")
    outline.apply_op(w, n, "set_item", {"line": t["line"], "raw": t["raw"], "text": "A flexi bends."})
    assert 'VO (Sam): "A flexi bends."' in (d / f"{n}.script.md").read_text(encoding="utf-8")


def test_set_header_fields_existing_and_new_and_section_titles():
    w, n, d = project("ol header")
    outline.apply_op(w, n, "set_header", {"field": "title", "text": "A better title"})
    outline.apply_op(w, n, "set_header", {"field": "logline", "text": "A new logline."})             # no logline line yet: it is added above the first section
    m = outline.load(w, n)
    assert m["header"]["title"]["text"] == "A better title" and m["header"]["logline"]["text"] == "A new logline."
    assert m["header"]["logline"]["line"] < m["sections"][0]["line"]
    outline.apply_op(w, n, "set_section", {"line": m["sections"][1]["line"], "text": "Tier 1: Beginners"})
    m = outline.load(w, n)
    assert m["sections"][1]["title"] == "Tier 1: Beginners" and m["sections"][1]["icon"].startswith("⏱")
    with pytest.raises(ValueError):
        outline.apply_op(w, n, "set_header", {"field": "nope", "text": "x"})
    w2, n2, _ = project("ol old header", OLD)
    outline.apply_op(w2, n2, "set_section", {"line": outline.load(w2, n2)["sections"][1]["line"], "text": "WHY A SHARK"})
    assert "## WHY A SHARK (0:12 - 0:55)" in (scriptedit.script_path(w2, n2)).read_text(encoding="utf-8")


# ----------------------------------------------------------------------------- the view and Claude
def test_outline_view_groups_each_section_for_the_screen():
    w, n, d = project("ol view")
    v = views.outline_view(w, n)
    assert v["has_outline"] and [h["label"] for h in v["header"]] == ["Title", "Logline", "Thesis", "Promise", "Thumbnail concept"]
    assert v["header"][0]["text"].startswith("Which Soldering Iron") and v["header"][1]["known"] is False
    tier1 = v["sections"][1]
    assert tier1["title"].startswith("Tier 1") and [e["title"] for e in tier1["entries"]] == ["Pencil Iron", "Gas Pen"] and tier1["time"] == "less than a minute" and v["sections"][6]["time"] == "less than a minute"
    e = tier1["entries"][0]
    assert len(e["shots"]) == 2 and len(e["vo"]) == 1 and e["chips"][0]["kind"] == "data" and e["talking"][0]["summary"].startswith("That said, if you have ever lifted a pad")
    assert len(e["talking"][0]["text"]) > len(e["talking"][0]["summary"])
    assert v["button"]["label"] == "Ask Claude to revise" and v["summary"] == ""
    assert "S0" not in json.dumps(v)                                                                                       # no line ids reach the screen


def test_outline_view_without_an_outline_and_with_gaps():
    r = make_project.build(clips=False, title="ol none")
    scriptedit.script_path(r["work"], r["name"]).unlink()
    v = views.outline_view(r["work"], r["name"])
    assert v["has_outline"] is False and v["button"]["label"] == "Ask Claude to draft the outline" and v["note"]["placeholder"] == "What is the video about?"
    w, n, d = project("ol gaps", OLD)
    assert views.outline_view(w, n)["summary"] == "1 section still needs shot ideas"
    f = views.facts(w, n)
    s = views.step_of(f)
    assert (s["step"], s["sentence"], s["button"]) == ("outline", "Outline: 1 section still needs shot ideas", "Open the outline")


def test_brief_for_a_draft_and_for_a_revision(tmp_path):
    r = make_project.build(clips=False, title="ol brief")
    scriptedit.script_path(r["work"], r["name"]).unlink()
    p = outline.brief(r["work"], r["name"], tmp_path / "a", "a video about gears")
    assert p.startswith("Draft the outline") and "a video about gears" in p and "outline.md" in p and "an emoji icon" in p
    assert (tmp_path / "a" / "example.md").exists() and not (tmp_path / "a" / "current.md").exists()
    w, n, d = project("ol brief2")
    p = outline.brief(w, n, tmp_path / "b", "shorter intro", icons=False)
    assert p.startswith("Revise the host's outline") and "shorter intro" in p and "no emoji" in p and (tmp_path / "b" / "current.md").exists()


def test_claude_answer_replaces_the_outline_and_keeps_the_old_one_as_a_version(tmp_path):
    w, n, d = project("ol answer")
    new = tmp_path / "outline.md"
    new.write_text("Title: Short\n\n🎬 One\n\n[VISUAL: a]\n\nSAM (A-ROLL):\n\"Hello there.\"\n\n🎬 Two\n\n[VISUAL: b]\n\nSAM (VO):\n\"More.\"\n", encoding="utf-8")
    before = len(scriptedit.history(w, n))
    ok, msg = outline.apply_answer(w, n, new)
    assert ok and msg == "Claude wrote an outline with 2 sections." and [s["title"] for s in outline.load(w, n)["sections"]] == ["One", "Two"]
    assert len(scriptedit.history(w, n)) == before + 1                                                  # the outline before is saved
    new.write_text("just some words", encoding="utf-8")
    assert outline.apply_answer(w, n, new)[0] is False and len(outline.load(w, n)["sections"]) == 2
