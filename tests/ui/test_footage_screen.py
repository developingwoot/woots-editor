import re
import sys
from pathlib import Path

import pytest
from playwright.sync_api import expect

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "fixtures"))
import make_project  # noqa: E402
from conftest import clutter, visible_text  # noqa: E402

pytestmark = [pytest.mark.ui, pytest.mark.skipif(not make_project.have_ffmpeg(), reason="ffmpeg missing")]


def open_footage(screen, title):
    import views
    r = make_project.build_footage(title)
    return screen(f"/v2/#/v/{views.key_of(r['work'], r['name'])}/footage"), r


def test_footage_screen_shows_the_folder_recordings_and_one_button(screen):
    page, r = open_footage(screen, "ui footage load")
    page.wait_for_selector("#cutBtn")
    assert page.inner_text("#cutBtn") == "Make the rough cut" and page.locator("#cutBtn").is_enabled()
    assert "5 recordings" in page.inner_text("#footageSummary")
    assert page.locator("#recordings .rec").count() == 5
    assert page.locator('#recordings .rec[data-speech="read"]').count() == 3 and page.locator('#recordings .rec[data-speech="silent footage"]').count() == 2
    assert page.locator("#folderPath").inner_text() == "ui-footage-load › footage".replace("-", "-")
    assert clutter(visible_text(page)) == []


def test_making_the_rough_cut_fills_in_the_shots_and_makes_cut_1(screen):
    page, r = open_footage(screen, "ui footage cut")
    page.wait_for_selector("#cutBtn")
    page.click("#cutBtn")
    expect(page.locator("#shotsCard .frow.shot")).to_have_count(2, timeout=90000)
    expect(page.locator('#shotsCard .frow.shot[data-status="ready"]')).to_have_count(1, timeout=90000)
    expect(page.locator('#shotsCard .frow.shot[data-status="nothing"] .chip.warn')).to_have_text("Nothing yet")
    expect(page.locator('#shotsCard .frow.take[data-status="ready"]')).to_have_count(3)
    expect(page.locator("#recordings .looked")).to_have_count(5)
    expect(page.locator("#cutBtn")).to_have_text("Make the rough cut again")
    assert "film or find" not in visible_text(page)
    expect(page.locator("#copyMissing")).to_have_text("Copy the list of missing shots (1)")
    assert clutter(visible_text(page)) == []
    page.locator("a.step", has_text="Rough cut").click()
    expect(page.locator("#strip .clip")).to_have_count(3, timeout=20000)
    assert "Cut 1" in page.inner_text("#versionMenu")
    page.click(".changes summary")
    assert "1 of 2 shots have footage" in page.inner_text(".changes")


def test_user_can_pick_another_clip_for_a_shot(screen):
    page, r = open_footage(screen, "ui footage pick")
    page.click("#cutBtn")
    expect(page.locator('#shotsCard .frow.shot[data-status="ready"]')).to_have_count(1, timeout=90000)
    thumbs = page.locator('#shotsCard .frow.shot[data-status="ready"] .pickThumb')
    assert thumbs.count() >= 2
    expect(thumbs.nth(0)).to_have_class(re.compile("on"))
    thumbs.nth(1).click()
    expect(page.locator('#shotsCard .frow.shot[data-status="ready"] .pickThumb').nth(1)).to_have_class(re.compile("on"))
    page.click('#shotsCard .frow.shot[data-status="ready"] >> text=None of these')
    expect(page.locator('#shotsCard .frow.shot[data-status="ready"]')).to_have_count(0)
    expect(page.locator('#shotsCard .frow.shot[data-status="nothing"]')).to_have_count(2)


def test_change_folder_with_the_dialog_and_the_button_explains_an_empty_folder(screen):
    page, r = open_footage(screen, "ui footage folder")
    page.wait_for_selector("#changeFolder")
    empty = r["dir"] / "empty folder"
    empty.mkdir()
    page.click("#changeFolder")
    expect(page.locator("#folderDlg")).to_be_visible()
    expect(page.locator("#fdInfo")).to_have_text("3 video files directly in this folder")        # the dialog opens on the current folder
    page.fill("#fdPath", str(empty))
    page.press("#fdPath", "Enter")
    expect(page.locator("#fdInfo")).to_have_text("0 video files directly in this folder")
    page.click("#fdUse")
    expect(page.locator("#folderPath")).to_have_text("ui-footage-folder › empty folder")
    expect(page.locator("#cutBtn")).to_be_disabled()
    assert "There are no recordings in that folder yet." in visible_text(page)


def test_a_recording_can_be_left_out_and_put_back(screen):
    page, r = open_footage(screen, "ui footage leave out")
    page.wait_for_selector("#recordings")
    first = page.locator("#recordings .rec").nth(0)
    first.locator("button", has_text="Leave out").click()
    expect(page.locator("#recordings .rec.ignored")).to_have_count(1)
    assert "4 recordings, 1 left out" in page.inner_text("#footageSummary")
    expect(page.locator("#recordings .rec.ignored .chip2")).to_have_text("left out")
    page.locator("#recordings .rec.ignored button", has_text="Use it").click()
    expect(page.locator("#recordings .rec.ignored")).to_have_count(0)
    assert "5 recordings" in page.inner_text("#footageSummary") and "left out" not in page.inner_text("#footageSummary")


def test_new_recordings_can_be_read_without_making_a_cut(screen):
    import json
    page, r = open_footage(screen, "ui footage read new")
    page.wait_for_selector("#cutBtn")
    assert page.locator("#readNew").count() == 0                          # everything is read: no button
    fp = r["dir"] / f"{r['name']}.footage.json"
    cfg = json.loads(fp.read_text(encoding="utf-8"))
    cfg["analysis"].pop(next(iter(cfg["analysis"])))                      # one recording is new
    fp.write_text(json.dumps(cfg), encoding="utf-8")
    page.reload()
    page.wait_for_selector("#readNew")
    assert page.inner_text("#readNew") == "Read the 1 new recording"
    assert page.locator('#recordings .rec[data-speech="not read yet"]').count() == 1
    page.click("#readNew")                                                # the test server fakes the reading: the job starts and ends at once
    page.wait_for_timeout(1500)
    assert page.locator("#sayBar:visible").count() == 0                   # no error message
    assert clutter(visible_text(page)) == []
