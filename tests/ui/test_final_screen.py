import sys
from pathlib import Path

import pytest
from playwright.sync_api import expect

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "fixtures"))
import make_project  # noqa: E402
from conftest import clutter, visible_text  # noqa: E402

pytestmark = [pytest.mark.ui, pytest.mark.skipif(not make_project.have_ffmpeg(), reason="ffmpeg missing")]


def open_final(screen, title, final=False):
    import views
    r = make_project.build(cut=True, preview=True, title=title)
    if final:
        make_project.add_final(r["dir"], r["name"], title)
    return screen(f"/v2/#/v/{views.key_of(r['work'], r['name'])}/final"), r


def test_final_screen_is_ready_and_makes_the_final(screen):
    page, _ = open_final(screen, "ui final render")
    page.wait_for_selector("#renderBtn")
    assert page.inner_text("#renderBtn") == "Render final" and "Ready to render" in visible_text(page)
    assert clutter(visible_text(page)) == []
    page.click("#renderBtn")
    expect(page.locator("#finalPlayer")).to_be_visible(timeout=30000)
    expect(page.locator("#renderBtn")).to_have_text("Render again")
    assert "Final 1" in visible_text(page)
    assert clutter(visible_text(page)) == []


def test_claude_writes_publishing_details_which_can_be_chosen_and_edited(screen):
    page, _ = open_final(screen, "ui final publish")
    page.wait_for_selector("#writeBtn")
    assert page.inner_text("#writeBtn") == "Ask Claude to write the publishing details"
    page.click("#writeBtn")
    expect(page.locator("#titles li")).to_have_count(2, timeout=30000)
    assert "Why did my 3D printed linkage fail?" in page.input_value("#description")
    assert page.input_value("#tags") == "linkage, 3d printing"
    assert "Oswald Bold" in page.locator("#prompts").inner_text()
    page.locator("#titles li").nth(1).locator(".pick").click()
    expect(page.locator("#titles li.chosen")).to_have_count(1)
    assert "I built a linkage and it broke" in page.locator("#titles li.chosen").inner_text()
    page.fill("#description", "My own description")
    page.locator("#tags").focus()                                   # leaving the field saves it
    page.fill("#ownTitle", "A title I typed")
    page.press("#ownTitle", "Enter")
    expect(page.locator("#titles li")).to_have_count(3)
    assert page.input_value("#description") == "My own description"
    assert page.inner_text("#writeBtn") == "Ask Claude to redo"
    assert clutter(visible_text(page)) == []


def test_thumbnail_draft_is_made_on_the_chosen_frame_and_shown_small_too(screen):
    page, _ = open_final(screen, "ui final thumb", final=True)
    page.wait_for_selector("#finalPlayer")
    page.fill("#thumbWords", "THE WORST DESIGN")
    page.click("#makeThumb")
    expect(page.locator("#draftBig")).to_be_visible(timeout=30000)
    assert page.locator("#draftSmall").get_attribute("width") == "168"
    assert page.evaluate("document.getElementById('draftBig').naturalWidth") == 1280
    assert clutter(visible_text(page)) == []


def test_finish_and_archive_shows_the_plan_then_archives_only_after_the_confirm(screen):
    page, r = open_final(screen, "ui final archive", final=True)
    page.wait_for_selector("#archiveCard")
    assert "Choose the title first." in page.inner_text("#archiveCard")
    page.fill("#ownTitle", "Ui Archive Title")
    page.press("#ownTitle", "Enter")
    page.wait_for_selector("#archiveStart")
    page.click("#archiveStart")
    expect(page.locator("#archivePlan")).to_be_visible()
    plan = page.inner_text("#archivePlan")
    assert "Ui Archive Title.mp4" in plan and "Deleted for good" in plan and "DaVinci Resolve" in plan
    assert clutter(plan.replace("Ui Archive Title.mp4", "")) == []
    assert (r["dir"] / "ui final archive v1 (1080p).mp4").exists()               # nothing happened yet
    page.click("text=Cancel")
    expect(page.locator("#archiveStart")).to_be_visible()
    page.click("#archiveStart")
    page.click("#archiveGo")
    expect(page.locator("#archivedBox")).to_be_visible(timeout=60000)
    assert (r["dir"] / "footage" / "Ui Archive Title.mp4").exists() and (r["dir"] / "footage" / "_woots-project" / "MANIFEST.json").exists()
    assert not (r["dir"] / "ui final archive v1 (1080p).mp4").exists()
