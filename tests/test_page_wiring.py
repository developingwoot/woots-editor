"""The shared scripts look up page elements by id at load time; a missing one throws and breaks every tab."""
import re
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parent.parent / "tools" / "review_app" / "static"
HTML = (STATIC / "index.html").read_text(encoding="utf-8")


@pytest.mark.parametrize("script", ["core.js", "folderpicker.js"])
def test_ids_used_by_shared_scripts_exist_in_the_page(script):
    ids = set(re.findall(r'\$\("#([A-Za-z][\w-]*)"\)', (STATIC / script).read_text(encoding="utf-8")))
    assert ids, "expected to find id lookups"
    missing = sorted(i for i in ids if f'id="{i}"' not in HTML)
    assert not missing, f"{script} looks up ids that index.html no longer has: {missing}"


def test_every_tab_button_has_a_pane():
    views = re.findall(r'<button data-view="(\w+)"', HTML)
    assert len(views) == 10
    for v in views:
        assert f'data-for="{v}"' in HTML, f"tab {v} has no pane"


def test_every_script_tag_points_at_a_file():
    for src in re.findall(r'<script src="/static/([^"]+)"', HTML):
        assert (STATIC / src).is_file(), src
