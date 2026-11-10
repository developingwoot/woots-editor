import subprocess
import sys

import platformx


def test_kill_tree_stops_a_running_process():
    p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    platformx.kill_tree(p)
    assert p.wait(10) is not None
    platformx.kill_tree(p)                              # already gone: nothing happens


def test_the_operating_system_calls_are_only_in_platformx():
    from pathlib import Path
    for f in (Path(platformx.__file__).parent).glob("*.py"):
        if f.name == "platformx.py":
            continue
        text = f.read_text(encoding="utf-8-sig")
        assert "os.startfile" not in text and "taskkill" not in text, f.name
