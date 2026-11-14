import pytest

from playwright.sync_api import expect

from conftest import clutter, visible_text

pytestmark = pytest.mark.ui


def make_video(title, outline=True):
    import workflow
    r = workflow.create(title)
    if outline:
        (workflow.WORK / r["work"] / f"{r['name']}.script.md").write_text("# outline", encoding="utf-8")
    return r


def test_home_shows_cards_with_a_sentence_and_one_button(screen):
    make_video("ui card video")
    page = screen("/v2/")
    card = page.locator(".vcard", has_text="ui card video")
    assert "Outline written: add your footage next" in card.inner_text()
    assert card.locator("a.main").inner_text() == "Add footage"
    assert clutter(visible_text(page)) == []


def test_button_opens_the_video_page_with_the_step_bar(screen):
    make_video("ui step video")
    page = screen("/v2/")
    page.locator(".vcard", has_text="ui step video").locator("a.main").click()
    page.wait_for_selector(".stepbar")
    assert [t.replace("Next", "").strip() for t in page.locator(".step").all_inner_texts()] == ["Outline", "Footage", "Rough cut", "Preview", "Final", "Shorts"]
    assert page.locator(".step.current").inner_text().startswith("Footage")
    assert page.locator('.step[data-state="next"]').get_attribute("aria-label") == "Footage: next"
    assert page.locator('.step[data-dot="result"]').all_inner_texts() == ["Outline"]
    assert clutter(visible_text(page)) == []


def test_any_step_can_be_opened_and_new_video_works(screen):
    page = screen("/v2/")
    page.on("dialog", lambda d: (_ for _ in ()).throw(AssertionError("a browser dialog opened")))
    page.click("#newVideo")
    page.fill("#askInput", "ui brand new")
    page.click("#askOk")
    page.wait_for_selector(".stepbar")
    assert page.locator("h1").inner_text() == "ui brand new"
    assert page.locator(".step.current").inner_text().startswith("Outline")
    page.click(".stepbar >> text=Shorts")
    expect(page.locator(".step.current")).to_have_text("Shorts")
    page.click("text=Your videos")
    page.wait_for_selector(".vcard")
    expect(page.locator(".vcard", has_text="ui brand new")).to_have_count(1)
    assert clutter(visible_text(page)) == []


def test_clutter_check_catches_forbidden_text():
    assert clutter("see beat B12 in plan.json costs $0.42") != []
    assert clutter("Rough cut 2 ready to watch, about 4 min") == []


def test_an_empty_home_says_so_without_stray_text(screen):
    page = screen("/v2/")
    if page.locator(".vcard").count():
        pytest.skip("other tests already made videos in this workspace")
    assert "No videos yet." in page.locator("#screen").inner_text()
    assert clutter(visible_text(page)) == []


def test_the_settings_screen_chooses_the_model_and_effort_of_each_job(screen):
    import claudemodels
    page = screen("/v2/#/settings")
    page.wait_for_selector("#claudeModelsCard .cmPick")
    assert "Shorts" in page.inner_text("#claudeModelsCard") and "Graphics critic" in page.inner_text("#claudeModelsCard")
    def choose(field, value):
        page.select_option(f"#claudeModelsCard [data-job=shorts][data-field={field}]", value)
        for _ in range(100):                                   # the card redraws once the choice is saved: wait for that before touching it again
            if claudemodels.get("shorts")[0 if field == "model" else 1] == value:
                break
            page.wait_for_timeout(50)
        page.wait_for_timeout(300)
    choose("model", "opus")
    choose("effort", "high")
    assert claudemodels.get("shorts") == ("opus", "high")
    assert claudemodels.get("edit") == ("sonnet", "medium")
    import config
    config.save_user_settings({"model_shorts": "", "effort_shorts": ""})


def test_the_top_bar_says_all_shorts(screen):
    page = screen("/v2/")
    assert page.inner_text("#shortsLink") == "All shorts"


def test_a_video_can_be_hidden_unhidden_and_deleted_from_its_card(screen):
    """The host: ideas that never get recorded clutter the home screen. Hide parks one; Delete moves its work folder to the trash."""
    import config
    r = make_video("ui shelf video")
    page = screen("/v2/")
    page.on("dialog", lambda d: (_ for _ in ()).throw(AssertionError("a browser dialog opened")))
    card = page.locator("#screen > .vcard", has_text="ui shelf video")
    card.locator(".vmenu summary").click()
    card.locator("text=Hide").click()
    expect(page.locator("#screen > .vcard", has_text="ui shelf video")).to_have_count(0)
    page.click("#hiddenBox summary")
    hidden = page.locator("#hiddenBox .vcard", has_text="ui shelf video")
    hidden.locator(".vmenu summary").click()
    hidden.locator("text=Unhide").click()
    expect(page.locator("#screen > .vcard", has_text="ui shelf video")).to_have_count(1)
    card = page.locator("#screen > .vcard", has_text="ui shelf video")
    card.locator(".vmenu summary").click()
    card.locator("text=Delete").click()
    expect(page.locator("#sureDialog")).to_contain_text("footage is not touched")
    page.click("#sureCancel")
    assert (config.WORK / r["work"]).is_dir()
    card.locator(".vmenu summary").click() if not card.locator(".vmenuList").is_visible() else None
    card.locator("text=Delete").click()
    page.click("#sureOk")
    expect(page.locator(".vcard", has_text="ui shelf video")).to_have_count(0)
    assert not (config.WORK / r["work"]).exists() and any(p.name.startswith(r["work"]) for p in (config.EDITOR_DATA / "trash").iterdir())
    assert clutter(visible_text(page)) == []
