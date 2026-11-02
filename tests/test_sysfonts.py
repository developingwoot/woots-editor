import sysfonts


def test_a_font_name_is_split_into_family_weight_and_slant():
    assert sysfonts.parse("Oswald Bold (TrueType)") == {"name": "Oswald Bold", "family": "Oswald", "weight": 700, "italic": False}
    assert sysfonts.parse("Segoe UI Semibold Italic") == {"name": "Segoe UI Semibold Italic", "family": "Segoe UI", "weight": 600, "italic": True}
    assert sysfonts.parse("Arial Narrow Bold")["family"] == "Arial Narrow"
    assert sysfonts.parse("Georgia") == {"name": "Georgia", "family": "Georgia", "weight": 400, "italic": False}


def test_a_name_that_is_only_a_style_word_is_kept_as_the_family():
    assert sysfonts.parse("Bold")["family"] == "Bold"


def test_symbol_fonts_and_empty_names_are_left_out():
    assert sysfonts.parse("Wingdings (TrueType)") is None and sysfonts.parse("Segoe MDL2 Assets (TrueType)") is None and sysfonts.parse("  ") is None


def test_the_list_has_one_entry_per_name_sorted_by_family(monkeypatch):
    monkeypatch.setattr(sysfonts, "_windows_names", lambda: ["Zilla Bold", "Arial Bold", "Arial", "arial", "Wingdings"])
    monkeypatch.setattr(sysfonts, "_fc_names", lambda: ["Zilla Bold", "Arial Bold", "Arial", "arial", "Wingdings"])
    assert [f["name"] for f in sysfonts.installed()] == ["Arial", "Arial Bold", "Zilla Bold"]
