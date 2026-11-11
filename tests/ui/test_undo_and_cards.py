"""Undo and History on every video screen; the fact check, music and DaVinci Resolve cards; the usage line on Home."""
import json
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


def outline(screen, title):
    import scriptedit
    import views
    r = make_project.build(clips=False, title=title)
    p = scriptedit.script_path(r["work"], r["name"])
    p.unlink()
    p.write_text(TEXT, encoding="utf-8")
    return screen(f"/v2/#/v/{views.key_of(r['work'], r['name'])}/outline"), r


def test_deleting_an_outline_line_can_be_undone_for_ten_seconds(screen):
    page, _ = outline(screen, "ui undo outline")
    page.wait_for_selector(".osec")
    before = page.locator(".shot").count()
    assert before >= 1
    page.locator(".shot .x").first.click()
    expect(page.locator("#undoBtn")).to_be_visible(timeout=10000)
    expect(page.locator(".shot")).to_have_count(before - 1)
    page.click("#undoBtn")
    expect(page.locator(".shot")).to_have_count(before, timeout=10000)
    expect(page.locator("#undoBar")).to_be_hidden()


def test_history_lists_the_changes_and_puts_a_version_back(screen):
    page, _ = outline(screen, "ui history")
    page.wait_for_selector(".osec")
    before = page.locator(".shot").count()
    page.locator(".shot .x").first.click()
    expect(page.locator(".shot")).to_have_count(before - 1, timeout=10000)
    page.click("#historyBtn")
    expect(page.locator("#historyPanel li").first).to_be_visible()
    assert "Script" in page.inner_text("#historyPanel")
    page.locator("#historyPanel li button", has_text="Put this back").first.click()
    expect(page.locator(".shot")).to_have_count(before, timeout=10000)


def test_fact_check_card_shows_the_problems_with_sources_and_can_dismiss_one(screen):
    import views
    page, r = outline(screen, "ui facts")
    (r["dir"] / f"{r['name']}.accuracy.json").write_text(json.dumps({"status": "done", "summary": "Mostly right, one thing matters.", "dismissed": [], "claims": [
        {"id": "C01", "verdict": "incorrect", "quote": "Steel never bends", "claim": "x", "explanation": "Steel flexes under load.", "suggestion": "Re-record",
         "sources": [{"title": "A reference", "url": "https://example.com/steel"}, {"title": "bad", "url": "javascript:alert(1)"}]},
        {"id": "C02", "verdict": "correct", "quote": "Gears turn", "claim": "y", "explanation": "", "sources": []}],
        "findings": [{"id": "C01", "verdict": "incorrect", "quote": "Steel never bends", "claim": "x", "explanation": "Steel flexes under load.", "suggestion": "Re-record",
                      "sources": [{"title": "A reference", "url": "https://example.com/steel"}, {"title": "bad", "url": "javascript:alert(1)"}]}]}), encoding="utf-8")
    page.goto(page.url.rsplit("/", 1)[0] + "/final")
    page.wait_for_selector("#factCard #factSummary")
    assert "Wrong" in page.inner_text("#factList") and "Steel never bends" in page.inner_text("#factList")
    links = page.locator("#factList a")
    assert links.count() == 1 and links.first.get_attribute("href") == "https://example.com/steel"
    page.locator("#factList button", has_text="Dismiss").click()
    expect(page.locator("#factNone")).to_be_visible()
    assert "Dismissed (1)" in page.inner_text("#factCard")


def test_a_right_claim_offers_show_the_source_and_a_refused_page_says_why(screen):
    import views
    r = make_project.build(cut=True, title="ui fact source")
    (r["dir"] / f"{r['name']}.accuracy.json").write_text(json.dumps({"status": "done", "summary": "All right.", "dismissed": [], "findings": [], "claims": [
        {"id": "C01", "beat": "B02", "verdict": "correct", "quote": "Gears turn", "claim": "y", "explanation": "",
         "sources": [{"title": "Gear page", "url": "http://127.0.0.1:9/gears", "evidence": "gears turn together"}]},
        {"id": "C02", "verdict": "correct", "quote": "Teeth mesh", "claim": "z", "explanation": "", "sources": []}]}), encoding="utf-8")
    page = screen(f"/v2/#/v/{views.key_of(r['work'], r['name'])}/final")
    page.wait_for_selector("#factCard #factRight")
    page.click("#factRight summary")
    assert "gears turn together" in page.inner_text("#factRight") and "No web page was given" in page.inner_text("#factRight")
    screen.allow.add("status of 400")                               # a page on this computer is refused, and the refusal is shown
    page.click("#factRight button[data-claim='C01']")
    expect(page.locator("#sayBar")).to_contain_text("private network")
    expect(page.locator("#factRight button[data-claim='C01']")).to_be_enabled()


def test_resolve_card_says_what_is_needed_and_the_usage_line_shows_on_home(screen):
    page, r = outline(screen, "ui resolve")
    page.goto(page.url.rsplit("/", 1)[0] + "/final")
    page.wait_for_selector("#resolveCard")
    expect(page.locator("#resolveGo")).to_be_disabled()
    assert "Export for DaVinci Resolve" in page.inner_text("#resolveCard") and "stitch" not in page.inner_text("#resolveCard").lower()
    page.goto(page.url.split("#")[0] + "#/")
    expect(page.locator("#usageLine")).to_be_visible(timeout=15000)
    assert "plan" in page.inner_text("#usageLine")


@pytest.mark.skipif(not make_project.have_ffmpeg(), reason="ffmpeg missing")
def test_music_card_on_the_preview_asks_for_a_new_preview_when_the_old_one_has_no_speech_track(screen):
    import views
    r = make_project.build(cut=True, preview=True, title="ui music")
    page = screen(f"/v2/#/v/{views.key_of(r['work'], r['name'])}/preview")
    page.wait_for_selector("#musicCard:not([hidden])", timeout=15000)
    assert "Make a new preview first" in page.inner_text("#musicCard")
    assert clutter(visible_text(page)) == []
