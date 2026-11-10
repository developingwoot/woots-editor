"""Prompts and messages are neutral: they say "the host" and never he, his or him; the graphics defaults name no one channel's colours or fonts."""
import ast
import re
from pathlib import Path

TOOLS = Path(__file__).resolve().parent.parent / "tools"
WORDS = re.compile(r"\b(he|his|him|himself)\b", re.I)
SKIP = {"clipmap.py"}                       # a list of stop words, not a prompt


def test_no_string_in_the_tools_says_he_his_or_him():
    bad = []
    for f in sorted(TOOLS.glob("*.py")):
        if f.name in SKIP:
            continue
        tree = ast.parse(f.read_text(encoding="utf-8-sig"))
        docs = {id(n.body[0].value) for n in ast.walk(tree) if isinstance(n, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and n.body
                and isinstance(n.body[0], ast.Expr) and isinstance(getattr(n.body[0], "value", None), ast.Constant)}
        for n in ast.walk(tree):
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docs and WORDS.search(n.value):
                bad.append(f"{f.name}:{n.lineno}")
    assert not bad, bad


def test_the_graphics_defaults_name_no_colour_or_font_of_one_channel():
    import gfxplan
    text = " ".join(s["desc"] for s in gfxplan.STYLES)
    assert not re.search(r"navy|orange|oswald", text, re.I)
    src = (TOOLS / "builder.py").read_text(encoding="utf-8")
    assert "brand-navy" not in src
