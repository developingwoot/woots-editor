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
    page.wait_for_function("() => document.querySelector('#paceSelect').value === 'tight'")
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
