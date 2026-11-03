import sys
from pathlib import Path

import pytest
from playwright.sync_api import expect

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "fixtures"))
import make_project  # noqa: E402
from conftest import clutter, visible_text  # noqa: E402

pytestmark = pytest.mark.ui

TEXT = """Title: Gears that last
Logline: A maker fixes gears that kept breaking.

🎬 Intro: The hook

[VISUAL: Sam holds a broken gear]

SAM (A-ROLL):
"My gears kept breaking. So I changed one thing, and it fixed everything. Here is what it was."

⚙️ Part 1: The fix

SAM (VO):
"It was the tooth shape."
"""


def in_file(path, text, seconds=10):
    """The server writes after the page shows the typed text: wait for the file instead of asserting at once."""
    import time
    end = time.time() + seconds
    while time.time() < end:
        try:
            if text in path.read_text(encoding="utf-8"):
                return True
        except PermissionError:                           # the server is replacing the file at this moment (Windows)
            pass
        time.sleep(0.1)
    return False


def open_outline(screen, title, text=TEXT):
    import scriptedit
    import views
    r = make_project.build(clips=False, title=title)
    p = scriptedit.script_path(r["work"], r["name"])
    p.unlink()
    if text:
        p.write_text(text, encoding="utf-8")
    return screen(f"/v2/#/v/{views.key_of(r['work'], r['name'])}/outline"), r, p


def test_outline_cards_show_shots_talking_points_with_folded_wording_and_a_gap_chip(screen):
    page, _, _ = open_outline(screen, "ui outline cards")
    page.wait_for_selector(".osec")
    assert page.locator(".osec").count() == 2
    assert page.locator('.hfield[data-field="title"] .ed').inner_text() == "Gears that last"
    first = page.locator(".osec").nth(0)
    assert "Sam holds a broken gear" in first.inner_text() and "My gears kept breaking." in first.inner_text()
    assert "Here is what it was" not in first.inner_text()                      # the full wording is folded
    first.locator("summary").click()
    assert "Here is what it was" in first.inner_text()
    expect(page.locator(".osec").nth(1).locator(".chip.warn")).to_have_text("Needs shot ideas")
    assert "1 section still needs shot ideas" in page.inner_text("#outlineGaps")
    assert clutter(visible_text(page)) == []


def test_edit_in_place_and_add_a_shot_are_saved(screen):
    page, r, path = open_outline(screen, "ui outline edit")
    page.wait_for_selector(".osec")
    shot = page.locator(".osec").nth(0).locator(".shot .ed")
    shot.click()
    page.keyboard.press("Control+a")
    page.keyboard.type("Sam holds the new gear")
    page.keyboard.press("Enter")
    expect(page.locator(".osec").nth(0).locator(".shot .ed")).to_have_text("Sam holds the new gear")
    assert in_file(path, "[VISUAL: Sam holds the new gear]")
    page.locator(".osec").nth(1).locator(".adder").fill("Close-up of the gear teeth")
    page.locator(".osec").nth(1).locator(".adder").press("Enter")
    expect(page.locator(".osec").nth(1).locator(".chip.warn")).to_have_count(0)
    assert in_file(path, "[VISUAL: Close-up of the gear teeth]")
    page.fill("#outlineHeader >> [data-field=thesis] .ed", "Tooth shape matters")                      # a header field that did not exist yet is added
    page.keyboard.press("Enter")
    expect(page.locator("#outlineHeader >> [data-field=thesis] .ed")).to_have_text("Tooth shape matters")
    assert in_file(path, "Thesis: Tooth shape matters")
    assert clutter(visible_text(page)) == []


def test_claude_drafts_an_outline_when_there_is_none_and_revises_it_after(screen):
    page, r, path = open_outline(screen, "ui outline draft", text=None)
    page.wait_for_selector("#outlineBtn")
    assert page.inner_text("#outlineBtn") == "Ask Claude to draft the outline"
    assert "No outline yet" in visible_text(page)
    page.fill("#outlineNote", "a video about gears")
    page.click("#outlineBtn")
    expect(page.locator(".osec")).to_have_count(2, timeout=30000)
    assert page.inner_text("#outlineBtn") == "Ask Claude to revise"
    assert page.locator('.hfield[data-field="title"] .ed').inner_text() == "Why my gears failed"
    page.fill("#outlineNote", "make the intro shorter")
    page.click("#outlineBtn")
    expect(page.locator(".osec")).to_have_count(2, timeout=30000)
    assert clutter(visible_text(page)) == []


def test_home_card_says_which_sections_need_shots_and_leads_to_the_outline(screen):
    page, r, _ = open_outline(screen, "ui outline home")
    page.goto(page.url.split("#")[0])
    page.wait_for_selector(".vcard")
    card = page.locator(".vcard", has_text="ui outline home")
    assert "Outline: 1 section still needs shot ideas" in card.inner_text()
    card.locator("a.main").click()
    page.wait_for_selector(".osec")
    assert page.locator(".step.current").inner_text() == "Outline"


def test_what_is_half_typed_survives_a_save_elsewhere_on_the_page(screen):
    page, r, path = open_outline(screen, "ui outline typing")
    page.wait_for_selector(".osec")
    adder = page.locator(".osec").nth(1).locator(".adder")
    adder.fill("Close-up of the gear teeth")
    page.locator(".osec").nth(0).locator(".shot .ed").click()
    page.keyboard.press("Control+a")
    page.keyboard.type("Sam holds the new gear")
    page.keyboard.press("Enter")                                           # saved: the page is drawn again from the answer
    assert in_file(path, "[VISUAL: Sam holds the new gear]")
    page.wait_for_timeout(500)
    assert page.locator(".osec").nth(1).locator(".adder").input_value() == "Close-up of the gear teeth"
    page.locator(".osec").nth(1).locator(".adder").press("Enter")
    assert in_file(path, "[VISUAL: Close-up of the gear teeth]")
    expect(page.locator(".osec").nth(1).locator(".adder")).to_have_value("")
