import pytest
from playwright.sync_api import expect

pytestmark = pytest.mark.ui


def test_settings_shows_this_computer_the_model_licences_and_the_version(screen):
    page = screen("/v2/#/settings")
    page.wait_for_selector("#computerCard [data-check='ffmpeg']", timeout=20000)
    text = page.inner_text("#computerCard")
    assert "Python" in text and "Claude Code" in text and "Graphics tool" in text
    expect(page.locator("#appVersion")).to_contain_text("Woots Editor 0.")
    page.wait_for_selector(".modelRow")
    assert "Licence:" in page.inner_text(".modelRow >> nth=0")
