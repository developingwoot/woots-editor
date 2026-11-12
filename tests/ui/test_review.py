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


def test_ideas_for_broll_and_on_screen_text_are_answered_on_the_card(screen):
    page, r = open_cut(screen, "ui cut ideas")
    expect(page.locator("#makeBtn")).to_be_disabled()
    page.click("#findIdeas")
    expect(page.locator("#ideas li")).to_have_count(2, timeout=30000)
    row = page.locator('#ideas li[data-kind="correction"]')
    assert "Correction" in row.inner_text()
    row.locator(".ideaText").fill("*the tape shirt")
    page.evaluate("const v = document.getElementById('player'); v.currentTime = 5; v.dataset.mine = '1'")
    page.wait_for_function("document.getElementById('player').currentTime >= 4.9")
    row.locator("button.tick").first.scroll_into_view_if_needed()
    scroll = page.evaluate("document.scrollingElement.scrollTop")
    row.locator("button.tick").first.click()                              # yes, with my own words
    expect(page.locator('#ideas li.yes[data-kind="correction"]')).to_have_count(1)
    assert page.evaluate("[document.getElementById('player').dataset.mine, document.getElementById('player').currentTime]") == ["1", 5]   # the same player, at the same moment
    assert abs(page.evaluate("document.scrollingElement.scrollTop") - scroll) < 2
    expect(page.locator('#ideas li[data-kind="correction"] .ideaText')).to_have_value("*the tape shirt")
    expect(page.locator("#makeBtn")).to_be_enabled()
    assert "Show “*the tape shirt” at" in page.locator("#notes").inner_text()
    page.locator('#ideas li[data-kind="film"] button.tick').first.click()  # a shot to film: it goes on the shoot plan's pickups
    expect(page.locator('#ideas li.yes[data-kind="film"]')).to_have_count(1)
    import shootplan
    assert [p["what"] for p in shootplan.state(r["work"], r["name"])["pickups"]] == ["the shirt from above"]
    page.evaluate("document.getElementById('player').currentTime = 7.5")
    page.wait_for_function("document.getElementById('player').currentTime >= 7.4")
    page.fill("#ownText", "*0.4 mm nozzle")
    page.press("#ownText", "Enter")                                       # my own correction at the playhead
    expect(page.locator("#ideas li")).to_have_count(3)
    assert "*0.4 mm nozzle" in page.locator("#notes").inner_text()
    assert clutter(visible_text(page)) == []


def test_a_box_drawn_on_the_paused_cut_is_followed_and_shown_over_the_player(screen):
    page, r = open_cut(screen, "ui cut blur")
    page.evaluate("document.getElementById('player').currentTime = 1")
    page.wait_for_function("document.getElementById('player').currentTime >= 0.9")
    page.click("#frameOn")                                                 # one frame on: frame 31 of 30 a second
    page.wait_for_function("Math.abs(document.getElementById('player').currentTime - 31.5 / 30) < 0.002")
    page.keyboard.press(",")
    page.wait_for_function("Math.abs(document.getElementById('player').currentTime - 30.5 / 30) < 0.002")
    assert page.inner_text("#frameClock") == "0:01 · frame 1 of 30"
    page.fill("#blurWhat", "the label")
    page.click("#blurAdd")
    expect(page.locator("#blurLayer.drawing")).to_have_count(1)
    box = page.locator("#blurLayer").bounding_box()
    page.mouse.move(box["x"] + box["width"] * 0.3, box["y"] + box["height"] * 0.3)
    page.mouse.down()
    page.mouse.move(box["x"] + box["width"] * 0.5, box["y"] + box["height"] * 0.5, steps=4)
    page.mouse.up()
    expect(page.locator("#blurs li")).to_have_count(1, timeout=30000)
    assert "the label" in page.locator("#blurs").inner_text() and "Blur the label at 0:01" in page.locator("#notes").inner_text()
    expect(page.locator("#blurLayer .blurBox")).to_have_count(1)                  # the box over the picture at the playhead
    expect(page.locator("#makeBtn")).to_be_enabled()
    page.locator("#blurs .blurRowStyle").select_option("block")
    expect(page.locator("#blurLayer .blurBox.block")).to_have_count(1)
    b = {x["id"]: x for x in __import__("json").loads((r["dir"] / f"{r['name']}.beatmap.json").read_text(encoding="utf-8"))["beats"]}
    e = next(x for bb in b.values() for x in (bb.get("on_screen") or {}).get("blur") or [])
    assert e["style"] == "block" and e["track"][0][1] == pytest.approx(0.3, abs=0.03) and len(e["track"]) > 2
    page.locator("#blurs li button", has_text="✕").click()
    expect(page.locator("#blurs li")).to_have_count(0)
    assert clutter(visible_text(page)) == []


def test_a_redrawn_screen_stops_the_old_player_and_a_hung_job_check_is_tried_again(screen):
    page, _ = open_cut(screen, "ui cut release")
    expect(page.locator("#player")).to_have_attribute("src", __import__("re").compile("cut-v1"))
    page.evaluate("() => { window._old = document.getElementById('player'); window._old.dataset.old = '1'; }")
    page.evaluate("() => dispatchEvent(new HashChangeEvent('hashchange'))")                 # what a finished job does: the screen is drawn again
    expect(page.locator("#player:not([data-old])")).to_have_count(1)
    assert page.evaluate("() => window._old.getAttribute('src')") is None                   # the old one stopped downloading
    asked = []
    page.route("**/api/v2/job", lambda route: asked.append(1) if len(asked) == 0 else (asked.append(1), route.continue_()))   # the first check never answers
    page.wait_for_timeout(12000)
    assert len(asked) >= 2                                                                  # it gave up after 8 s and asked again


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
    assert "Slide in from the right" in page.locator("#webTrans option").first.inner_text()      # the default first, then every other preset
    page.select_option("#webTrans", "flash")
    page.fill("#webUrl", "http://127.0.0.1:8765/")
    page.click("#webGo")
    expect(page.locator("#sayBar")).to_contain_text("private network")
    assert clutter(visible_text(page)) == []
