import json
import sys
from pathlib import Path

import pytest
from playwright.sync_api import expect

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "fixtures"))
import make_project  # noqa: E402
from conftest import clutter, visible_text  # noqa: E402

pytestmark = [pytest.mark.ui, pytest.mark.skipif(not make_project.have_ffmpeg(), reason="ffmpeg missing")]

SAID = "we start with the tape shirt on the desk then the gears kept breaking again and again so I changed the tooth shape".split()


def video_with_shorts(title, shorts=True):
    """A video with a final, a transcript of its 9 seconds and (optionally) a shorts project with two shorts."""
    import shortsapp
    import views
    r = make_project.build(cut=True, preview=True, title=title)
    final = make_project.add_final(r["dir"], r["name"], title)
    tr = r["dir"] / "final.transcript.json"
    words = [{"word": w, "start": round(0.2 + 0.45 * i, 2), "end": round(0.2 + 0.45 * i + 0.4, 2)} for i, w in enumerate(SAID)]
    tr.write_text(json.dumps({"duration": 9.0, "words": words, "segments": [{"start": 0.2, "end": words[-1]["end"], "text": " ".join(SAID)}]}), encoding="utf-8")
    if shorts:
        shortsapp.new_project(r["work"], r["name"], str(final).replace("\\", "/"), str(tr).replace("\\", "/"), None)
        raw = shortsapp.read_raw(r["work"], r["name"])
        raw["shorts"] = [{"id": "s1", "title": "The gears kept breaking", "hook": "GEARS KEPT|BREAKING", "why": "The problem in one line", "status": "", "ranges": [[0.0, 4.5]]},
                         {"id": "s2", "title": "The tooth shape", "hook": "THE FIX", "why": "The answer", "status": "", "ranges": [[4.5, 8.8]]}]
        shortsapp.save_raw(r["work"], r["name"], raw)
    return r, views.key_of(r["work"], r["name"])


def raw_of(r):
    import shortsapp
    return shortsapp.read_raw(r["work"], r["name"])


def test_the_area_lists_videos_that_have_shorts_or_a_final(screen):
    video_with_shorts("ui shorts area one")
    video_with_shorts("ui shorts area two", shorts=False)
    page = screen("/v2/#/shorts")
    page.wait_for_selector(".shortsItem")
    text = visible_text(page)
    assert "2 shorts" in text and "Open the shorts" in text and "Make shorts" in text
    assert clutter(text) == []
    page.click("#shortsLink")
    assert page.url.endswith("#/shorts")


def test_a_video_without_a_final_says_what_is_needed(screen):
    import views
    r = make_project.build(cut=True, preview=True, title="ui shorts no final")
    page = screen(f"/v2/#/v/{views.key_of(r['work'], r['name'])}/shorts")
    page.wait_for_selector("#needFinal")
    assert "Render the final first" in visible_text(page)
    page.click("#needFinal a")
    assert page.url.endswith("/final")


def test_the_step_shows_the_shorts_and_they_can_be_kept_dropped_and_brought_back(screen):
    r, key = video_with_shorts("ui shorts keep")
    page = screen(f"/v2/#/v/{key}/shorts")
    page.wait_for_selector(".shortCard")
    expect(page.locator(".shortCard")).to_have_count(2)
    text = visible_text(page)
    assert "The gears kept breaking" in text and "room for about 1 short" in text and "GEARS KEPT BREAKING" in text
    assert "not kept or dropped will be made too" in text
    assert clutter(text) == []
    page.locator(".shortCard[data-id=s1] .keepBtn").click()
    expect(page.locator(".shortCard[data-id=s1]")).to_have_attribute("data-status", "kept")
    assert raw_of(r)["shorts"][0]["status"] == "kept"
    page.locator(".shortCard[data-id=s2] .dropBtn").click()
    expect(page.locator(".shortCard")).to_have_count(1)
    assert raw_of(r)["shorts"][1]["status"] == "dropped"
    page.click("#droppedBox summary")
    page.click("#droppedBox button")
    expect(page.locator(".shortCard")).to_have_count(2)
    assert raw_of(r)["shorts"][1]["status"] == ""
    assert clutter(visible_text(page)) == []


def test_opening_a_short_cuts_words_and_saves_the_hook(screen):
    r, key = video_with_shorts("ui shorts open")
    page = screen(f"/v2/#/v/{key}/shorts")
    page.wait_for_selector(".shortCard")
    page.locator(".shortCard[data-id=s1] .openBtn").click()
    page.wait_for_selector("#shortWords .w")
    assert page.locator("#shortWords .w").first.inner_text() == "we"
    page.locator("#shortWords .w", has_text="tape").first.click()
    expect(page.locator("#shortWords .w.cut")).to_have_count(1)
    assert raw_of(r)["shorts"][0]["drop"]
    page.locator("#shortWords .w.cut").click()
    expect(page.locator("#shortWords .w.cut")).to_have_count(0)
    assert "drop" not in raw_of(r)["shorts"][0]
    page.fill("#hookInput", "a new hook")
    page.locator("#hookInput").press("Tab")
    page.wait_for_function("() => document.querySelector('.shortCard .vbody').innerText.includes('A NEW HOOK')")
    assert raw_of(r)["shorts"][0]["hook"] == "A NEW HOOK"
    page.select_option("#paceSelect", "tight")
    for _ in range(50):                                      # the select already shows "tight": wait for the save, not for the select
        if raw_of(r)["shorts"][0].get("pace") == "tight":
            break
        page.wait_for_timeout(100)
    assert raw_of(r)["shorts"][0]["pace"] == "tight"
    assert clutter(visible_text(page)) == []


def test_making_a_preview_shows_the_vertical_video(screen):
    r, key = video_with_shorts("ui shorts preview")
    page = screen(f"/v2/#/v/{key}/shorts")
    page.wait_for_selector(".shortCard")
    page.locator(".shortCard[data-id=s1] .openBtn").click()
    page.wait_for_selector("#previewBtn")
    assert page.inner_text("#previewBtn") == "Make a preview"
    page.click("#previewBtn")
    expect(page.locator("#shortPlayer")).to_be_visible(timeout=90000)
    page.locator(".shortCard[data-id=s1] .openBtn").click()           # closed and opened again: the preview is still there
    page.locator(".shortCard[data-id=s1] .openBtn").click()
    expect(page.locator("#shortPlayer")).to_be_visible()
    import shorts
    assert shorts.probe_size(r["dir"] / "shorts" / "s1.mp4") == (540, 960)                  # the file is the vertical preview (the test browser cannot play h264 itself)
    assert clutter(visible_text(page)) == []


def test_the_video_file_picker_lists_folders_and_videos(screen, tmp_path):
    import shutil
    (tmp_path / "Finished Video.mp4").write_bytes(b"x" * 3000)
    (tmp_path / "notes.txt").write_text("no", encoding="utf-8")
    (tmp_path / "More").mkdir()
    page = screen("/v2/#/shorts")
    page.wait_for_selector("#fromFile")
    page.evaluate("p => localStorage.setItem('wr.videoDir', p)", str(tmp_path))          # the picker starts in the folder used last
    page.click("#fromFile")
    page.wait_for_selector("#folderDlg")
    expect(page.locator("#fdInfo")).to_contain_text("1 video file", timeout=60000)
    page.wait_for_selector(".fdFile")
    text = page.inner_text("#folderDlg")
    assert "Finished Video.mp4" in text and "More" in text and "notes.txt" not in text
    assert not page.locator("#fdUse").is_visible()
    page.keyboard.press("Escape")
    expect(page.locator("#folderDlg")).to_have_count(0)


def test_shorts_made_from_a_video_file_open_under_their_own_heading(screen, tmp_path):
    import shortsapp
    import subprocess
    import workflow
    src = tmp_path / "Own File Video.mp4"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=640x360:rate=15:duration=3", "-f", "lavfi", "-i", "sine=duration=3",
                    "-pix_fmt", "yuv420p", "-shortest", str(src)], check=True)
    work, name = shortsapp.standalone_names(src)
    wd = workflow.WORK / work
    wd.mkdir(parents=True)
    tr = wd / "t.json"
    tr.write_text(json.dumps({"duration": 3, "words": [], "segments": [{"start": 0, "end": 3, "text": "hello"}]}), encoding="utf-8")
    shortsapp.new_project(work, name, str(src).replace("\\", "/"), str(tr).replace("\\", "/"), None)
    raw = shortsapp.read_raw(work, name)
    raw["shorts"] = [{"id": "s1", "title": "Hello there", "hook": "HELLO", "status": "", "ranges": [[0.0, 3.0]]}]
    shortsapp.save_raw(work, name, raw)
    page = screen("/v2/#/shorts")
    row = page.locator(".shortsItem", has_text="Own File Video")
    row.locator("a.main").click()
    page.wait_for_selector(".shortCard")
    assert page.locator("h1").inner_text() == "Own File Video"
    assert "← Shorts" in visible_text(page) and "Hello there" in visible_text(page)
    assert clutter(visible_text(page)) == []
    page.click("text=← Shorts")
    page.wait_for_selector(".shortsItem")


def test_a_short_from_raw_footage_asks_for_a_folder(screen, tmp_path):
    (tmp_path / "Raw Day").mkdir()
    (tmp_path / "Raw Day" / "take1.mp4").write_bytes(b"x" * 3000)
    page = screen("/v2/#/shorts")
    page.wait_for_selector("#fromFolder")
    assert page.inner_text("#fromFolder") == "A short from raw footage"
    page.evaluate("p => localStorage.setItem('wr.rawDir', p)", str(tmp_path))
    page.click("#fromFolder")
    page.wait_for_selector("#folderDlg")
    expect(page.locator("#folderDlg")).to_contain_text("Raw Day", timeout=60000)
    assert "Choose the folder with the raw footage" in page.inner_text("#folderDlg") and page.locator("#fdUse").is_visible()
    assert not page.locator(".fdFile").count()
    page.keyboard.press("Escape")
    expect(page.locator("#folderDlg")).to_have_count(0)


def test_the_sound_panel_saves_the_caption_style_music_and_effects_choices(screen):
    r, key = video_with_shorts("ui shorts sound")
    page = screen(f"/v2/#/v/{key}/shorts")
    page.wait_for_selector(".shortCard")
    page.locator(".shortCard[data-id=s1] .openBtn").click()
    page.wait_for_selector("#styleSelect")
    assert page.input_value("#styleSelect") == "pop" and page.input_value("#sfxSelect") == "on" and page.input_value("#musicSelect") == ""
    assert [o.inner_text() for o in page.locator("#styleSelect option").all()] == ["Pop", "Box", "Bounce", "Plain"]
    page.select_option("#styleSelect", "box")
    page.wait_for_function("() => document.querySelector('#styleSelect').value === 'box'")
    page.select_option("#sfxSelect", "off")
    page.wait_for_function("() => document.querySelector('#sfxSelect').value === 'off'")
    page.select_option("#musicSelect", "none")
    page.wait_for_function("() => document.querySelector('#musicSelect').value === 'none'")
    import time
    for _ in range(50):                                        # the choice is on the page at once and in the file a moment later
        s = raw_of(r)["shorts"][0]
        if (s.get("caption_style"), s.get("sfx"), s.get("music")) == ("box", "off", "none"):
            break
        time.sleep(0.1)
    assert (s["caption_style"], s["sfx"], s["music"]) == ("box", "off", "none")
    assert clutter(visible_text(page)) == []


def test_the_graphics_panel_lists_the_plan_and_cuts_and_brings_back_a_graphic(screen):
    import shortsapp
    r, key = video_with_shorts("ui shorts graphics")
    raw = shortsapp.read_raw(r["work"], r["name"])
    raw["shorts"][0]["gfx"] = {"note": "Two ideas", "skipped": [], "graphics": [
        {"id": "g1", "t0": 1.0, "t1": 3.0, "look": "ui", "place": "top", "text": "GEAR TEETH\nsharp edge\nwears fast", "what": "the gear", "how": "x", "words": "the gears", "status": ""},
        {"id": "g2", "t0": 3.0, "t1": 4.0, "look": "kinetic", "place": "bottom", "text": "3 PRINTS", "what": "the number", "how": "pop", "words": "three prints", "status": ""}]}
    shortsapp.save_raw(r["work"], r["name"], raw)
    page = screen(f"/v2/#/v/{key}/shorts")
    page.wait_for_selector(".shortCard")
    page.locator(".shortCard[data-id=s1] .openBtn").click()
    page.wait_for_selector("#shortGfx .gfxRow")
    assert page.locator("#shortGfx .gfxRow").count() == 2
    assert "GEAR TEETH" in page.inner_text("#shortGfx") and "kinetic · bottom" in page.inner_text("#shortGfx") and "Plan the graphics again" in page.inner_text("#shortGfx")
    page.locator("#shortGfx .gfxRow[data-gid=g1] .gfxCut").click()
    expect(page.locator("#shortGfx .gfxRow.cut")).to_have_count(1)
    assert raw_of(r)["shorts"][0]["gfx"]["graphics"][0]["status"] == "cut"
    page.locator("#shortGfx .gfxRow.cut .gfxCut").click()
    expect(page.locator("#shortGfx .gfxRow.cut")).to_have_count(0)
    assert raw_of(r)["shorts"][0]["gfx"]["graphics"][0]["status"] == ""
    assert clutter(visible_text(page)) == []


def test_the_youtube_details_and_the_full_video_link_are_edited_on_the_screen(screen):
    import time
    r, key = video_with_shorts("ui shorts publish")
    page = screen(f"/v2/#/v/{key}/shorts")
    page.wait_for_selector(".shortCard")
    assert "saved in" in page.inner_text("#folderNote") and "Shorts" in page.inner_text("#folderNote")
    page.fill("#linkInput", "https://youtu.be/abc")
    page.press("#linkInput", "Tab")
    for _ in range(50):                                        # the page redraws when the link is saved: wait for that before typing elsewhere
        if raw_of(r).get("full_video_url"):
            break
        time.sleep(0.1)
    page.wait_for_timeout(300)
    page.locator(".shortCard[data-id=s1] .openBtn").click()
    page.wait_for_selector("#pubTitle")
    assert "Write them for me" in page.inner_text("#shortPublish")
    page.fill("#pubTitle", "Never use a cold iron")
    page.press("#pubTitle", "Tab")
    page.wait_for_function("() => document.querySelector('#titlesBtn').textContent.includes('again')")
    page.fill("#pubTags", "Soldering, Tips")
    page.press("#pubTags", "Tab")
    for _ in range(50):
        raw = raw_of(r)
        if raw["shorts"][0].get("publish", {}).get("tags") == ["Soldering", "Tips"] and raw.get("full_video_url"):
            break
        time.sleep(0.1)
    assert raw["full_video_url"] == "https://youtu.be/abc" and raw["shorts"][0]["publish"]["title"] == "Never use a cold iron"
    page.wait_for_selector("#shortPublish")
    assert "Write them again" in page.inner_text("#shortPublish") and page.input_value("#linkInput") == "https://youtu.be/abc"
    assert clutter(visible_text(page)) == []


def test_feedback_is_saved_on_a_short_and_as_a_general_note(screen):
    r, key = video_with_shorts("ui shorts feedback")
    page = screen(f"/v2/#/v/{key}/shorts")
    page.wait_for_selector(".shortCard")
    page.locator("#generalFeedback summary").click()
    page.locator("#generalFeedback .fbInput").fill("Hooks are too long")
    page.locator("#generalFeedback .fbAdd").click()
    page.wait_for_selector("#generalFeedback .noteRow")
    page.locator(".shortCard[data-id=s1] .openBtn").click()
    page.wait_for_selector("#shortFeedback")
    assert page.locator("#shortFeedback .fbApply").is_disabled()                      # nothing to apply yet
    page.locator("#shortFeedback .fbInput").fill("Start on the number")
    page.locator("#shortFeedback .fbAdd").click()
    page.wait_for_selector("#shortFeedback .noteRow")
    assert "Waiting" in page.inner_text("#shortFeedback") and "Apply 1 note" in page.inner_text("#shortFeedback")
    raw = raw_of(r)
    assert raw["feedback"][0]["text"] == "Hooks are too long" and raw["shorts"][0]["feedback"][0]["text"] == "Start on the number"
    page.locator("#shortFeedback .noteDelete").click()
    page.wait_for_function("() => !document.querySelector('#shortFeedback .noteRow')")
    assert "feedback" not in raw_of(r)["shorts"][0]
    assert clutter(visible_text(page)) == []
