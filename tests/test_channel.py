import json

import channel
import outline


def forbidden_names():
    """The first author's names (release/forbidden-names.txt, which is not in the public copy: there the guard tests that use it are skipped)."""
    import pytest
    from pathlib import Path
    f = Path(__file__).resolve().parent.parent / "release" / "forbidden-names.txt"
    if not f.exists():
        pytest.skip("no list of names to look for")
    return [ln.strip() for ln in f.read_text(encoding="utf-8").splitlines() if ln.strip()]


def test_the_profile_names_the_host_the_channel_and_the_cohost():
    assert channel.host() == "the host" and channel.people() == ["the host"]
    channel.save({"name": "Sam", "channel": "Sam's Bench", "topic": "a woodworking channel", "cohost": "Pat"})
    try:
        assert channel.people() == ["Sam", "Pat"] and channel.host() == "Sam"
        out = channel.about()
        assert "The host is Sam." in out and "The channel is Sam's Bench, a woodworking channel." in out and "Pat" in out
    finally:
        channel.save({"name": "", "channel": "", "topic": "", "cohost": ""})
    assert channel.host() == "the host" and channel.about() == ""


def test_save_keeps_other_fields_and_a_blank_removes_one():
    channel.save({"name": "Sam", "voice": "dry"})
    channel.save({"voice": ""})
    try:
        assert json.loads(channel.path().read_text()) == {"name": "Sam"}
        channel.save({"nonsense": "x"})
        assert "nonsense" not in json.loads(channel.path().read_text())
    finally:
        channel.save({"name": ""})


def test_the_channel_paragraph_comes_first_when_the_user_wrote_one():
    assert channel.prompt("The host talks.") == "The host talks."
    channel.save({"audience": "new makers", "voice": "plain, a little dry"})
    try:
        out = channel.prompt("The host talks.")
        assert out.startswith("About the channel") and "new makers" in out and out.endswith("The host talks.")
    finally:
        channel.save({"audience": "", "voice": ""})


def test_an_outline_speech_line_may_use_host_or_any_name_in_the_profile():
    for label in ("SAM (A-ROLL):", "HOST (VO):", "THE HOST:", "host:", "Sam Smith (VO):"):
        assert outline.SPEECH_RE.match(label)
    assert not outline.SPEECH_RE.match("NOTE:") and not outline.SPEECH_RE.match("user:")           # a bare name counts only when the profile has it
    assert outline.TP_VO_RE.search('| VO (Sam): "Pressure advance is..." |').group(1) == "Pressure advance is..."


def test_a_skill_file_the_user_has_replaces_the_starter_file(tmp_path, monkeypatch):
    import skillrules
    monkeypatch.setattr(skillrules, "SKILLS", tmp_path)
    assert skillrules.find("youtube-edit/rough-cut.md").parent.parent == skillrules.STARTER
    (tmp_path / "youtube-edit").mkdir()
    (tmp_path / "youtube-edit" / "rough-cut.md").write_text("mine", encoding="utf-8")
    assert skillrules.find("youtube-edit/rough-cut.md") == tmp_path / "youtube-edit" / "rough-cut.md"
    assert skillrules.find("youtube-edit/cut-rules.md").parent.parent == skillrules.STARTER
    names = [f.name for f in skillrules.files("youtube-edit")]
    assert names == sorted(set(names)) and "rough-cut.md" in names and "cut-rules.md" in names


def test_the_starter_skills_have_every_file_the_app_copies_and_no_names(monkeypatch, tmp_path):
    import builder
    import skillrules
    monkeypatch.setattr(skillrules, "SKILLS", tmp_path)
    for rel in skillrules.FOR_CLAUDE:
        assert skillrules.find(rel), rel
    for skill, f in builder.STYLE_FILES:
        assert skillrules.find(f"{skill}/{f}"), f
    assert skillrules.rules()["beat_min_s"] > 0
    for f in skillrules.STARTER.rglob("*.md"):
        text = f.read_text(encoding="utf-8")
        assert not any(w in text for w in forbidden_names()), f


def test_the_profile_writes_brand_and_house_style_files_into_the_users_skills(tmp_path, monkeypatch):
    import skillrules
    monkeypatch.setattr(skillrules, "SKILLS", tmp_path)
    assert channel.style_files() == {}
    channel.save({"headline_font": "Oswald Bold", "colors": "navy #142C44", "tone": "dry"})
    try:
        brand = (tmp_path / "woots-channel" / "brand.md").read_text(encoding="utf-8")
        assert channel.GENERATED in brand and "Oswald Bold" in brand and "navy #142C44" in brand
        assert "Tone: dry" in (tmp_path / "woots-channel" / "house-style.md").read_text(encoding="utf-8")
        assert skillrules.find("woots-channel/brand.md") == tmp_path / "woots-channel" / "brand.md"
        (tmp_path / "woots-channel" / "brand.md").write_text("my own notes", encoding="utf-8")        # edited by hand: never overwritten
        channel.save({"colors": "orange #E2703A"})
        assert (tmp_path / "woots-channel" / "brand.md").read_text(encoding="utf-8") == "my own notes"
    finally:
        channel.save({k: "" for k in channel.STYLE_KEYS})


def test_setup_is_not_finished_until_the_profile_has_a_name():
    import appsetup
    assert appsetup.view()["first_run"] is True
    channel.save({"name": "Sam"})
    try:
        assert appsetup.view()["first_run"] == appsetup.view()["folders_needed"]
    finally:
        channel.save({"name": ""})


def test_terms_become_caption_fixes_and_prompt_spellings():
    channel.save({"terms": "clipper* => Klipper\nbone => Bowden\nMainsail"})
    try:
        pairs = channel.corrections()
        import re
        assert any(re.match(p, "clippers", re.I) and r == "Klipper" for p, r in pairs)
        assert any(re.match(p, "bone", re.I) for p, r in pairs) and not any(re.match(p, "bones", re.I) for p, r in pairs if r == "Bowden")
        assert channel.spellings() == ["Klipper", "Bowden", "Mainsail"]
        import shorts
        assert shorts.fix_word("Clipper") == "Klipper" and shorts.fix_word("hello") == "hello"
    finally:
        channel.save({"terms": ""})
    assert channel.corrections() == [] and channel.spellings() == []


def test_thumbnail_prompts_use_the_profiles_colours_and_font_or_say_nothing():
    assert channel.thumbnail_style() == ""
    channel.save({"colors": "navy #142C44", "headline_font": "Oswald Bold"})
    try:
        assert channel.thumbnail_style() == ", brand colors navy #142C44, Oswald Bold style text"
    finally:
        channel.save({"colors": "", "headline_font": ""})


def test_no_string_in_the_tools_names_the_first_author():
    """Prompts and messages say "the host" and "the channel"; the names come from the channel profile. Comments and docstrings may still name people."""
    import io
    import re
    import tokenize
    from pathlib import Path
    bad = []
    names = forbidden_names()
    for f in sorted((Path(channel.__file__).parent).glob("*.py")):
        src = f.read_text(encoding="utf-8-sig")
        docs = set()
        import ast
        for node in ast.walk(ast.parse(src)):
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.body:
                first = node.body[0]
                if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
                    docs.update(range(first.lineno, first.end_lineno + 1))
        for tok in tokenize.generate_tokens(io.StringIO(src).readline):
            if tok.type in (tokenize.STRING, tokenize.FSTRING_MIDDLE) and tok.start[0] not in docs and any(w in tok.string for w in names):
                bad.append(f"{f.name}:{tok.start[0]}")
    assert not bad, bad
