"""Keeps Woot's review app running and up to date: start.bat runs this instead of server.py.

It starts server.py, then watches the app's Python files. When one changes it waits until nothing is running (no build, no render, no
Claude run), restarts the server by itself, and the open page reloads itself when it sees the new server. So nobody has to close the
console, run start.bat or press Ctrl+F5 after a code change. Changes to the page files (js, css, html) need no restart at all: the page
reloads itself.

Usage:  python supervisor.py [server.py arguments, e.g. --open --port 8765]
Ctrl+C stops everything. If the server crashes (for example a half-saved file), it is started again every few seconds until it stays up.
"""
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

HERE = Path(os.path.abspath(__file__)).parent
TOOLS = HERE.parent
SERVER = HERE / "server.py"


def py_mtime() -> float:
    newest = 0.0
    for d in (TOOLS, HERE):
        for f in d.glob("*.py"):
            if f.name != "supervisor.py":
                try:
                    newest = max(newest, f.stat().st_mtime)
                except OSError:
                    pass
    return newest


def port_of(args: list[str]) -> int:
    return int(args[args.index("--port") + 1]) if "--port" in args else 8765


def busy(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/code", timeout=3) as r:
            return bool(json.loads(r.read()).get("busy"))
    except Exception:                                     # noqa: BLE001 - not answering: nothing useful is running
        return False


def main():
    args = sys.argv[1:]
    port = port_of(args)
    first = True
    quick_fails = 0
    while True:
        run_args = args if first else [a for a in args if a != "--open"]       # the browser is opened once; the open page reloads itself afterwards
        first = False
        seen = py_mtime()
        env = {**os.environ, "WOOTS_SUPERVISED": "1", "PYTHONIOENCODING": "utf-8"}
        started = time.time()
        proc = subprocess.Popen([sys.executable, str(SERVER), *run_args], env=env)
        restart = False
        try:
            while proc.poll() is None:
                time.sleep(2)
                if py_mtime() > seen:
                    print("\n[supervisor] the app's code changed: waiting for running jobs to finish, then restarting...", flush=True)
                    while busy(port):
                        time.sleep(5)
                    time.sleep(1.0)                                            # let a multi-file edit finish
                    seen = py_mtime()
                    proc.terminate()
                    try:
                        proc.wait(timeout=15)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                    restart = True
                    print("[supervisor] restarting the app", flush=True)
                    break
        except KeyboardInterrupt:
            proc.terminate()
            return
        if restart:
            quick_fails = 0
            continue
        code = proc.returncode
        if code == 75:                                                         # appsetup.RESTART: new folders were saved, start again now
            print("[supervisor] settings saved: restarting the app", flush=True)
            quick_fails = 0
            continue
        if time.time() - started < 6:
            quick_fails += 1
        else:
            quick_fails = 0
        print(f"\n[supervisor] the app stopped (exit {code}). Starting it again in 4 s; press Ctrl+C to quit.", flush=True)
        if code in (0, None) and quick_fails == 0 and time.time() - started > 6:
            # a normal exit from the console (e.g. closing it politely): stop too
            return
        time.sleep(4 if quick_fails < 4 else 15)


if __name__ == "__main__":
    main()
