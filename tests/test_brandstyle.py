import re
from pathlib import Path

import brandstyle
import shorts
import sysfonts

TOOLS = Path(__file__).resolve().parent.parent / "tools"


def test_the_palette_the_settings_screen_writes_is_read_by_role():
    p = brandstyle.palette({"colors": "primary #142C44, accent #E2703A, colour 3 #F4EDE4"})
    assert (p["primary"], p["accent"], p["light"], p["extra"]) == ("#142C44", "#E2703A", "#F4EDE4", ["#F4EDE4"])


def test_free_text_colours_take_the_first_two_as_primary_and_accent():
    p = brandstyle.palette({"colors": "navy #142C44, orange #e2703a"})
    assert (p["primary"], p["accent"]) == ("#142C44", "#E2703A")


def test_a_named_accent_comes_first_even_when_listed_second():
    p = brandstyle.palette({"colors": "teal #00AAAA, accent #FF0000, grey #888888"})
    assert (p["accent"], p["primary"], p["extra"]) == ("#FF0000", "#00AAAA", ["#888888"])


def test_short_hex_codes_and_lines_without_a_code_are_handled():
    assert brandstyle.parse_colors("red #f00\nno code here\nblue: #00F") == [("red", "#FF0000"), ("blue", "#0000FF")]


def test_an_empty_profile_gives_plain_colours_that_are_not_any_channels():
    p = brandstyle.palette({})
    assert p["light"] == "#FFFFFF" and p["dark"] == "#000000" and p["extra"] == []
    assert p["primary"] == brandstyle.FALLBACK["primary"] and p["accent"] == brandstyle.FALLBACK["accent"]


def test_light_and_dark_only_come_from_the_palette_when_light_and_dark_enough():
    mid = brandstyle.palette({"colors": "a #808080, b #909090"})
    assert mid["light"] == "#FFFFFF" and mid["dark"] == "#000000"
    ends = brandstyle.palette({"colors": "ink #101010, paper #FAFAF0"})
    assert ends["light"] == "#FAFAF0" and ends["dark"] == "#101010"


def test_colour_formats_for_the_renderers():
    assert brandstyle.ass("#E2703A") == "&H003A70E2&"
    assert brandstyle.bgr("#142C44") == (68, 44, 20)
    assert brandstyle.ffmpeg("#E2703A") == "0xE2703A"


def test_the_headline_font_comes_from_the_profile_and_its_file(monkeypatch, tmp_path):
    f = tmp_path / "x.ttf"
    f.write_bytes(b"")
    monkeypatch.setattr(sysfonts, "files", lambda: {"oswald bold": str(f)})
    monkeypatch.setattr(sysfonts, "family_of_file", lambda p: "Oswald")
    got = brandstyle.font("headline", {"headline_font": "Oswald Bold"})
    assert got == {"name": "Oswald Bold", "family": "Oswald", "file": str(f), "bold": True}


def test_the_label_font_falls_back_to_the_headline_font_and_then_the_bundled_one(monkeypatch, tmp_path):
    f = tmp_path / "x.ttf"
    f.write_bytes(b"")
    monkeypatch.setattr(sysfonts, "files", lambda: {"georgia": str(f)})
    monkeypatch.setattr(sysfonts, "family_of_file", lambda p: "Georgia")
    assert brandstyle.font("label", {"headline_font": "Georgia"})["family"] == "Georgia"
    assert brandstyle.font("label", {"headline_font": "Not Installed"})["file"] == str(brandstyle.FALLBACK_FONT[1])
    assert Path(brandstyle.font("headline", {})["file"]).is_file()


def test_a_font_file_gives_its_family_name():
    assert sysfonts.family_of_file(str(brandstyle.FALLBACK_FONT[1])) == "Oswald"
    assert sysfonts.family_of_file(str(TOOLS / "nothing.ttf")) == ""


def test_the_font_lookup_by_name(monkeypatch):
    monkeypatch.setattr(sysfonts, "files", lambda: {"arial bold": "C:/f/arialbd.ttf"})
    assert sysfonts.file_for("Arial Bold (TrueType)") == "C:/f/arialbd.ttf" and sysfonts.file_for("Nope") == "" and sysfonts.file_for("") == ""


def test_the_captions_use_the_profile_colours_and_font(monkeypatch):
    monkeypatch.setattr(brandstyle.channel, "load", lambda: {"colors": "primary #102030, accent #FF8800", "headline_font": "", "terms": ""})
    monkeypatch.setattr(brandstyle.sysfonts, "family_of_file", lambda p: "Test Family")
    word = {"w": "Hello", "s": 0.0, "e": 0.4}
    piece = {"layout": "live", "t0": 0.0, "a": 0.0, "b": 1.0, "dur": 1.0, "words": [word]}
    ass = shorts.make_ass({"hook": "BIG HOOK"}, [piece])
    assert "Style: Cap,Test Family" in ass and r"\c&H000088FF&" in ass and "&H000088FF&,&H000088FF&" in ass


def test_the_shorts_code_names_no_colour_or_font():
    for name in ("shorts.py", "shortsgfx.py", "shortsapp.py"):
        text = (TOOLS / name).read_text(encoding="utf-8")
        assert not re.search(r"#[0-9a-fA-F]{6}\b|0x[0-9a-fA-F]{6}\b|&H00[0-9A-F]{6}&", text.replace("&H00FFFFFF", "")), name
        assert not re.search(r"Oswald|Impact", text), name
