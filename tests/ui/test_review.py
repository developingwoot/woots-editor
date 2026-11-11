import sys
from pathlib import Path

import pytest
from playwright.sync_api import expect

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "fixtures"))
import make_project  # noqa: E402
from conftest import clutter, visible_text  # noqa: E402

pytestmark = [pytest.mark.ui, pytest.mark.skipif(not make_project.have_ffmpeg(), reason="ffmpeg missing")]


def open_preview(screen, title):
    import views
    r = make_project.build(preview=True, title=title)
    return screen(f"/v2/#/v/{views.key_of(r['work'], r['name'])}/preview"), r


def test_review_screen_loads_and_passes_the_clutter_check(screen):
    page, _ = open_preview(screen, "ui review load")
    expect(page.locator("#player")).to_be_visible()
    assert page.locator(".clip").count() == 3
    expect(page.locator("#makeBtn")).to_be_disabled()
    assert "Add a note first" in visible_text(page)
    assert clutter(visible_text(page)) == []


def test_note_at_the_playhead_then_make_preview_2_with_what_changed(screen, base, tmp_path, monkeypatch):
    page, r = open_preview(screen, "ui review make")
    page.evaluate("document.getElementById('player').currentTime = 4")
    page.wait_for_function("document.getElementById('player').currentTime >= 3.9")
    page.keyboard.press("n")
    page.fill("#noteText", "the shirt changes here")
    page.press("#noteText", "Enter")
    expect(page.locator("#notes li")).to_have_count(1)
    assert page.locator("#notes .when").inner_text() == "0:04"
    expect(page.locator("#makeBtn")).to_have_text("Make preview 2 from my notes")
    expect(page.locator("#makeBtn")).to_be_enabled()
    page.click("#makeBtn")
    expect(page.locator("#versionMenu option")).to_have_count(2, timeout=20000)
    expect(page.locator("#versionMenu")).to_have_value("2")
    page.click(".changes summary")
    assert "Moved the shirt" in page.locator(".changes").inner_text()
    assert "done in Preview 2" in page.locator("#notes").inner_text()
    expect(page.locator("#makeBtn")).to_be_disabled()
    page.select_option("#versionMenu", "1")
    expect(page.locator("#versionMenu")).to_have_value("1")
    assert clutter(visible_text(page)) == []


def open_cut(screen, title, with_cut=True):
    import cutview
    import makeversion
    import views
    r = make_project.build(cut=True, title=title)
    if with_cut:
        video, rows = cutview.render(r["work"], r["name"])
        makeversion.finish_cut(r["work"], r["name"], video, rows, {})
    return screen(f"/v2/#/v/{views.key_of(r['work'], r['name'])}/rough-cut"), r


def test_first_rough_cut_is_made_from_the_plan(screen):
    page, _ = open_cut(screen, "ui cut first", with_cut=False)
    page.wait_for_selector("#makeBtn")
    assert page.inner_text("#makeBtn") == "Make the rough cut"
    page.click("#makeBtn")
    expect(page.locator("#strip .clip")).to_have_count(4, timeout=60000)
    expect(page.locator("#versionMenu")).to_have_value("1")
    assert clutter(visible_text(page)) == []


def test_replace_option_remove_and_make_cut_2(screen):
    page, r = open_cut(screen, "ui cut replace")
    page.locator("#strip .clip").nth(0).click()
    page.click("#actReplace")
    expect(page.locator(".option")).to_have_count(1)
    assert "1 restart" in page.locator(".option").inner_text()
    page.click(".option >> text=Use this one")
    expect(page.locator("#strip .clip").nth(0)).to_have_class(__import__("re").compile("pending"))
    page.locator("#strip .clip").nth(3).click()
    page.click("#actRemove")
    expect(page.locator("#notes li")).to_have_count(2)
    expect(page.locator("#makeBtn")).to_have_text("Make cut 2 from my notes")
    assert "2 clip changes" in page.inner_text(".makebox")
    assert clutter(visible_text(page)) == []
    page.click("#makeBtn")
    expect(page.locator("#versionMenu option")).to_have_count(2, timeout=60000)
    expect(page.locator("#strip .clip")).to_have_count(3)
    page.click(".changes summary")
    changes = page.locator(".changes").inner_text()
    assert "Swapped the clip" in changes and "Took out the clip" in changes
    assert clutter(visible_text(page)) == []


def test_teaching_moments_can_be_ticked(screen):
    page, _ = open_cut(screen, "ui cut teaching")
    row = page.locator("#teaching li").first
    assert "pressure advance" in row.inner_text()
    assert row.locator("button").first.get_attribute("aria-label") == "Explain this in the video"       # an icon-only button is named by its title
    row.locator("button").first.click()
    expect(page.locator("#teaching li.yes")).to_have_count(1)
    assert clutter(visible_text(page)) == []


def test_claude_can_suggest_more_teaching_moments(screen):
    page, _ = open_cut(screen, "ui cut find teaching")
    page.click("#findTeach")
    expect(page.locator("#teaching li")).to_have_count(2, timeout=30000)
    assert "retraction" in page.locator("#teaching").inner_text()
    assert clutter(visible_text(page)) == []


def test_claude_can_suggest_fun_moments_and_a_tick_accepts_one(screen):
    page, _ = open_cut(screen, "ui cut fun moments")
    page.click("#findFun")
    expect(page.locator("#moments li")).to_have_count(1, timeout=30000)
    assert "IT BROKE" in page.locator("#moments").inner_text()
    page.locator("#moments li button").first.click()
    expect(page.locator("#moments li.yes")).to_have_count(1)
    assert clutter(visible_text(page)) == []


def test_search_all_footage_adds_takes_for_a_clip_with_none(screen):
    page, _ = open_cut(screen, "ui cut search")
    page.locator("#strip .clip").nth(3).click()            # the last clip has no other take
    page.click("#actReplace")
    expect(page.locator("#findOptions")).to_be_visible()
    assert "no other take" in page.locator("#clipPanel").inner_text()
    page.click("#findOptions")
    expect(page.locator(".option")).to_have_count(1, timeout=30000)
    assert clutter(visible_text(page)) == []


def test_picture_clip_needs_the_footage_looked_at_then_offers_shots(screen):
    page, _ = open_cut(screen, "ui cut vision")
    page.locator("#strip .clip").nth(2).click()                 # the voice-over's picture: no speech to search by
    page.click("#actReplace")
    expect(page.locator("#visionNote")).to_be_visible()
    assert "have not been looked at" in page.locator("#visionNote").inner_text()
    assert page.locator("#findOptions").count() == 0
    page.click("#lookBtn")
    expect(page.locator(".option")).to_have_count(2, timeout=60000)
    assert "Looks like" in page.locator(".option").first.inner_text()
    assert page.locator("#visionNote").count() == 0
    assert clutter(visible_text(page)) == []


def test_a_suggestion_in_what_changed_becomes_a_note_in_one_click(screen):
    import cutview
    import makeversion
    import views
    r = make_project.build(cut=True, title="ui suggest")
    video, rows = cutview.render(r["work"], r["name"])
    text = 'Move "so I changed the tooth shape" before "then the gears kept breaking" - a viewer needs the cause first'
    makeversion.finish_cut(r["work"], r["name"], video, rows, {"changes": ["Cut it together"], "suggestions": [{"text": text, "t": 3.0}]})
    page = screen(f"/v2/#/v/{views.key_of(r['work'], r['name'])}/rough-cut")
    page.wait_for_selector(".changes")
    page.click(".changes summary")
    assert "Claude suggests" in page.inner_text("#suggestions")
    page.click("#suggestions button")
    expect(page.locator("#notes li")).to_have_count(1)
    assert "tooth shape" in page.inner_text("#notes") and "B0" not in page.inner_text("#notes")
    expect(page.locator("#suggestions button")).to_be_disabled()


def test_graphics_in_the_preview_can_be_skipped_before_the_build(screen):
    import json
    import projectstore
    import views
    r = make_project.build(cut=True, preview=True, title="ui graphics list")
    page = screen(f"/v2/#/v/{views.key_of(r['work'], r['name'])}/preview")
    bp = r["dir"] / f"{r['name']}.beatmap.json"
    bm = json.loads(bp.read_text(encoding="utf-8"))
    bm["beats"][1]["graphic"] = {"kind": "stamp", "text": "IT BROKE", "dur": 1.5, "words": "the tape shirt again", "why": "joke", "strength": 3, "struck": False}
    projectstore.write_json(bp, bm)
    page.reload()
    page.wait_for_selector("#graphicsList")
    assert "Graphics in this preview (1)" in page.locator("#graphicsList summary").inner_text()
    page.click("#graphicsList summary")
    assert "Sticker: IT BROKE" in page.locator("#graphicsList").inner_text()
    page.locator("#graphicsList .tick").click()
    expect(page.locator("#graphicsList summary")).to_have_text("Graphics in this preview (0)")
    assert clutter(visible_text(page)) == []


def test_a_note_can_be_about_the_whole_video(screen):
    page, _ = open_cut(screen, "ui whole note")
    page.fill("#noteText", "The video is too long, kill more darlings")
    page.check("#wholeNote")
    page.press("#noteText", "Enter")
    expect(page.locator("#notes li")).to_have_count(1)
    assert page.locator("#notes .when").inner_text() == "Whole video"
    assert page.locator("#wholeNote").is_checked() is False
    assert clutter(visible_text(page)) == []


def test_a_web_page_can_be_asked_for_on_a_clip_and_a_local_address_is_refused(screen):
    screen.allow.add("status of 400")                               # the refusal is an error answer, shown as a message
    page, _ = open_cut(screen, "ui web broll")
    page.locator("#strip .clip").nth(1).click()
    page.click("#actWeb")
    expect(page.locator("#webUrl")).to_be_visible()
    assert "added to the credits" in page.locator("#clipPanel").inner_text()
    page.fill("#webUrl", "http://127.0.0.1:8765/")
    page.click("#webGo")
    expect(page.locator("#sayBar")).to_contain_text("private network")
    assert clutter(visible_text(page)) == []
