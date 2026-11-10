"""The screens are ES modules: a missing file or a misspelled import breaks the whole app, so check the wiring without a browser."""
import re
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parent.parent / "tools" / "review_app" / "static"
V2 = STATIC / "v2"
MODULES = sorted(V2.glob("*.js"))


def test_the_page_loads_the_app_module_and_its_style():
    html = (V2 / "index.html").read_text(encoding="utf-8")
    assert '<script type="module" src="/static/v2/app.js">' in html
    for href in re.findall(r'<link rel="stylesheet" href="/static/([^"]+)"', html):
        assert (STATIC / href).is_file(), href


@pytest.mark.parametrize("module", MODULES, ids=lambda p: p.name)
def test_every_import_points_at_a_file_and_a_name_it_exports(module):
    text = module.read_text(encoding="utf-8")
    for names, src in re.findall(r"import\s+(.+?)\s+from\s+'(\./[^']+)'", text):
        target = V2 / src[2:]
        assert target.is_file(), f"{module.name} imports {src}"
        code = target.read_text(encoding="utf-8")
        if "{" in names:
            for n in (x.split(" as ")[0].strip() for x in names.strip("{} ").split(",") if x.strip()):
                e = re.escape(n)
                assert re.search(r"export\s+(async\s+)?(function|const|let|class)\s+%s(?![\w$])|export\s*\{[^}]*(?<![\w$])%s(?![\w$])" % (e, e), code), f"{module.name}: {src} does not export {n}"
