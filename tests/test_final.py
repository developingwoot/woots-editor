import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures"))
import archive  # noqa: E402
import finalize  # noqa: E402
import make_project  # noqa: E402
import projectstore  # noqa: E402
import publish  # noqa: E402
import thumbdraft  # noqa: E402
import views  # noqa: E402

needs_ffmpeg = pytest.mark.skipif(not make_project.have_ffmpeg(), reason="ffmpeg missing")


def project(title, final=True):
    r = make_project.build(cut=True, preview=True, title=title)
    out = make_project.add_final(r["dir"], r["name"], title) if final else None
    return r["work"], r["name"], r["dir"], out


# ----------------------------------------------------------------------------- publishing details
def test_title_choice_and_fields_are_cleaned_and_recorded(tmp_path):
    r = make_project.build(clips=False, title="pub fields")
    w, n = r["work"], r["name"]
    d = publish.set_title(w, n, "  My   Title ")
    assert d["title"] == "My Title" and d["titles"] == ["My Title"]
    with pytest.raises(ValueError):
        publish.set_title(w, n, "ab")
    d = publish.set_field(w, n, "tags", "3d printing, #gears, Gears , " + ", ".join(f"t{i}" for i in range(30)))
    assert d["tags"][:2] == ["3d printing", "gears"] and len(d["tags"]) == 15
    assert publish.set_field(w, n, "thumbnail_text", "A\n\nB")["thumbnail_text"] == ["A", "B"]
    assert publish.set_field(w, n, "thumb", {"t": "4.26", "text": " hi   there "})["thumb"] == {"t": 4.3, "text": "hi there"}
    with pytest.raises(ValueError):
        publish.set_field(w, n, "nope", 1)
    assert any(e["file"].endswith(".publish.json") for e in projectstore.history(r["dir"]))


def test_claude_answer_is_validated_and_chapters_come_from_code(tmp_path, monkeypatch):
    r = make_project.build(clips=False, title="pub answer")
    w, n = r["work"], r["name"]
    monkeypatch.setattr(publish, "chapter_lines", lambda *_: ["0:00 Intro", "1:10 The gear problem", "2:30 Fix"])
    publish.set_title(w, n, "My own title")
    p = tmp_path / "answer.json"
    p.write_text(json.dumps({"titles": ["Why my linkage failed", "ab", ""], "hook": "Why did my 3D printed linkage fail?", "summary": "I built it.",
                             "credits": ["Someone - Their video - https://example.com"], "tags": ["linkage", "linkage", "3d printing"],
                             "thumbnail_prompts": ["a", "b", "c", "d"], "thumbnail_text": ["worst design"], "chapters": ["9:99 invented"]}), encoding="utf-8")
    ok, msg = publish.apply_answer(w, n, p)
    d = publish.load(w, n)
    assert ok and d["titles"] == ["Why my linkage failed", "My own title"] and d["title"] == "My own title"     # Sam's own title survives a redo
    assert d["description"].startswith("Why did my 3D printed linkage fail?\n\nI built it.\n\nChapters\n0:00 Intro")
    assert "invented" not in d["description"] and d["description"].endswith("Credits\nSomeone - Their video - https://example.com")
    assert d["tags"] == ["linkage", "3d printing"] and len(d["thumbnail_prompts"]) == 3 and d["thumbnail_text"] == ["WORST DESIGN"]
    p.write_text(json.dumps({"titles": []}), encoding="utf-8")
    assert publish.apply_answer(w, n, p)[0] is False
    p.write_text("not json", encoding="utf-8")
    assert publish.apply_answer(w, n, p)[0] is False


def test_brief_carries_the_note_and_the_outline(tmp_path):
    r = make_project.build(clips=False, title="pub brief")
    prompt = publish.brief(r["work"], r["name"], tmp_path / "fd", "make the title shorter")
    assert "make the title shorter" in prompt and "publish.json" in prompt and "Do not write chapters" in prompt
    assert (tmp_path / "fd" / "script.md").read_text(encoding="utf-8").strip()


# ----------------------------------------------------------------------------- thumbnail draft
def test_words_split_into_balanced_lines():
    assert thumbdraft.lines_of("") == [] and thumbdraft.lines_of("the worst design ever") == ["THE WORST", "DESIGN EVER"]
    assert len(thumbdraft.lines_of("a b c d e f g")) == 3


@needs_ffmpeg
def test_thumbnail_draft_is_1280_by_720_with_the_words_on_the_frame(tmp_path):
    from PIL import Image
    w, n, d, out = project("td draft")
    video = d / f"{n}.preview-half.mp4"
    plain = thumbdraft.grab(video, 1.0, tmp_path / "f.jpg")
    drawn = thumbdraft.make(video, 1.0, "THE WORST DESIGN", tmp_path / "out" / "t.jpg")
    a, b = Image.open(plain), Image.open(drawn)
    assert b.size == (1280, 720) and a.size == (1280, 720) and a.tobytes() != b.tobytes()
    assert not (tmp_path / "out" / "t.frame.jpg").exists()
    with pytest.raises(ValueError):
        thumbdraft.draw(plain, "   ", tmp_path / "x.jpg")


# ----------------------------------------------------------------------------- the Final screen's view model
def test_plain_warnings_have_no_file_names():
    assert views.plain_warning("no stitched preview yet") == "Make the preview first: the final is made from it."
    assert "match what you watched" in views.plain_warning("the plan changed since the preview was stitched (beatmap.json): the final will not match what you watched")
    assert ".json" not in views.plain_warning("see big-thing.json and x.md for details")
    assert views.plain_warning("section S1 has no render.json: rebuild it") == "Some parts of the preview need to be made again before the final."


@needs_ffmpeg
def test_final_view_without_and_with_a_final_and_a_title():
    w, n, d, _ = project("fv view", final=False)
    v = views.final(w, n)
    assert v["state"]["ready"] is True and v["button"]["label"] == "Render final" and v["button"]["detail"] == "Ready to render" and v["latest"] is None
    assert v["archive"]["can"] is False and v["archive"]["why"] == "Render the final first."
    make_project.add_final(d, n, "fv view")
    v = views.final(w, n)
    assert v["button"]["label"] == "Render again" and v["finals"][0]["label"] == "Final 1" and v["latest"]["video"].startswith("/media/")
    assert v["archive"]["why"] == "Choose the title first."
    publish.set_title(w, n, "My Video")
    v = views.final(w, n)
    assert v["title"] == "My Video" and v["archive"]["can"] is True
    assert views.final(w, n, running=True)["button"]["enabled"] is False


# ----------------------------------------------------------------------------- finish and archive
@needs_ffmpeg
def test_archive_saves_the_project_into_the_footage_folder_then_cleans_and_can_be_restored(tmp_path):
    w, n, d, out = project("ar run")
    footage = d / "footage"
    (d / "junk render.mp4").write_bytes(b"x" * 1000)
    (d / "cache").mkdir()
    (d / "cache" / "a.wav").write_bytes(b"y" * 500)
    (d / "resolve" / "media").mkdir(parents=True)
    (d / "resolve" / "media" / "copy.mov").write_bytes(b"z" * 700)
    publish.set_title(w, n, "Ar Run Title")
    pv = archive.preview(w, n, "Ar Run Title", footage)
    assert pv["final_name"] == "Ar Run Title.mp4" and [x["what"] for x in pv["delete"]][0].endswith("old renders, previews and sound files")
    assert "converted copies made for DaVinci Resolve" in [x["what"] for x in pv["delete"]]
    assert not (footage / archive.BUNDLE).exists() and out.exists()                      # a preview changes nothing
    r = archive.run(w, n, "Ar Run Title", footage)
    bundle = footage / archive.BUNDLE
    man = json.loads((bundle / "MANIFEST.json").read_text(encoding="utf-8"))
    assert (footage / "Ar Run Title.mp4").exists() and not out.exists() and not (d / "junk render.mp4").exists()
    assert not (d / "cache").exists() and not (d / "resolve" / "media").exists() and (d / "FINALIZED.json").exists()
    assert f"{n}.script.md" in man["files"] and f"{n}.publish.json" in man["files"] and (bundle / "README.txt").exists()
    assert any(f.startswith(".history/") for f in man["files"]) and r["bundle"]["files"] == len(man["files"])
    assert not any(f.endswith((".mp4", ".mov", ".wav")) for f in man["files"])                # no renders in the project
    restored = archive.restore(bundle, tmp_path / "work2")
    assert restored["work"] == w and (tmp_path / "work2" / w / f"{n}.beatmap.json").exists()
    with pytest.raises(ValueError):
        archive.restore(bundle, tmp_path / "work2")                                          # never over an existing project
    with pytest.raises(ValueError):
        archive.restore(tmp_path, tmp_path / "work3")


@needs_ffmpeg
def test_archive_deletes_nothing_when_the_move_cannot_happen():
    w, n, d, out = project("ar refuse")
    footage = d / "footage"
    (footage / "Ar Refuse.mp4").write_bytes(b"already here")
    (d / "junk render.mp4").write_bytes(b"x" * 100)
    with pytest.raises(ValueError, match="refusing to overwrite"):
        archive.run(w, n, "Ar Refuse", footage)
    assert out.exists() and (d / "junk render.mp4").exists() and not (footage / archive.BUNDLE).exists()


@needs_ffmpeg
def test_finalize_cli_behaviour_is_kept(capsys, monkeypatch):
    w, n, d, out = project("fz cli")
    footage = d / "footage"
    monkeypatch.setattr(sys, "argv", ["finalize.py", str(d), "--title", "Fz Cli", "--project", str(footage)])
    finalize.main()
    assert "DRY RUN" in capsys.readouterr().out and out.exists()
    monkeypatch.setattr(sys, "argv", ["finalize.py", str(d), "--title", "Fz Cli", "--project", str(footage), "--yes"])
    finalize.main()
    assert (footage / "Fz Cli.mp4").exists() and not out.exists()
