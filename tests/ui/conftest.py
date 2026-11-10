"""Browser tests: the real server on a free port against the throwaway data root, one page per test, console errors fail the test."""
import json
import os
import re
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SERVER = REPO / "tools" / "review_app" / "server.py"

# Text that must never show on a main view (plan rule 2). Allowed only inside a closed "Details" block.
FORBIDDEN = [r"\.json", r"\.mp4", r"\b[SBG]\d{2}\b", r"TP\d", r"\$\d", r"\d+\.\d{2,}", r"Traceback", r"\bbeat", r"stitch", r"approve", r"\bstale", r"sandbox", r"\bnull\b", r"\bundefined\b"]


def clutter(text: str) -> list[str]:
    """The forbidden patterns found in the visible text."""
    return [p for p in FORBIDDEN if re.search(p, text, re.IGNORECASE)]


OUTLINE_ANSWER = "\n".join([
    "YouTube Video Script: Gears", "", "Title: Why my gears failed", "",
    "🎬 Intro: The hook", "", "[VISUAL: Sam holds a broken gear]", "", "SAM (A-ROLL):", '"My gears kept breaking, so I changed one thing."', "",
    "⚙️ Part 1: The fix", "", "[VISUAL: close-up of the new gear]", "", "SAM (VO):", '"It was the tooth shape."', ""])


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def base(tmp_path_factory):
    fake = tmp_path_factory.mktemp("fake-claude")                  # Claude's canned answers: no tokens in tests
    (fake / "answer.json").write_text(json.dumps({"applied": [{"id": 1, "summary": "Moved the shirt clip earlier"}]}), encoding="utf-8")
    (fake / "teaching.json").write_text(json.dumps({"moments": [{"beat": "B02", "term": "retraction", "why": "A newcomer does not know the word"}]}), encoding="utf-8")
    (fake / "options.json").write_text(json.dumps({"options": [{"rel": "take2.mp4", "start": 0.0, "end": 3.0, "why": "He says it again here"}]}), encoding="utf-8")
    (fake / "publish.json").write_text(json.dumps({"titles": ["Why my first linkage failed", "I built a linkage and it broke"], "hook": "Why did my 3D printed linkage fail?",
                                                    "summary": "I redesigned it until it worked.", "credits": [], "tags": ["linkage", "3d printing"],
                                                    "thumbnail_prompts": ["Sam holding a broken gear, navy and orange, Oswald Bold text"], "thumbnail_text": ["IT BROKE"]}), encoding="utf-8")
    (fake / "outline.md").write_text(OUTLINE_ANSWER, encoding="utf-8")
    log_path = fake / "server.log"                                  # an unread PIPE would fill up and freeze the server
    log = open(log_path, "w")
    port = free_port()
    p = subprocess.Popen([sys.executable, str(SERVER), "--port", str(port)], env={**os.environ, "WOOTS_FAKE_CLAUDE": str(fake), "WOOTS_FAKE_VISION": "1", "WOOTS_MIN_WORDS": "5", "WOOTS_MIN_PIECE": "1"},
                         stdout=subprocess.DEVNULL, stderr=log)
    url = f"http://127.0.0.1:{port}"
    try:
        for _ in range(80):
            if p.poll() is not None:
                pytest.fail("server exited: " + log_path.read_text(errors="replace")[-800:])
            try:
                urllib.request.urlopen(url + "/", timeout=1).read()
                break
            except OSError:
                time.sleep(0.25)
        else:
            pytest.fail("server did not start")
        yield url
    finally:
        p.terminate()
        try:
            p.wait(5)
        except subprocess.TimeoutExpired:
            p.kill()


@pytest.fixture
def screen(base, page):
    """Open a v2 path and return the page; any console error or uncaught exception fails the test afterwards."""
    import channel
    channel.save({"name": "Sam"})                                   # without a profile the app opens the first-run Settings screen instead of the page asked for
    errors = []
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.set_viewport_size({"width": 1440, "height": 900})

    def go(path="/v2/"):
        page.goto(base + path)
        page.wait_for_load_state("networkidle")
        return page
    yield go
    assert not errors, errors


def visible_text(page) -> str:
    """Text a person can see: Details blocks that are closed are hidden by innerText already."""
    return page.inner_text("body")
