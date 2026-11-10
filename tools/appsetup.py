"""First-run setup and Settings: where the user's folders are, and whether Claude is installed and signed in.

Folders are saved in the per-user settings file (`config.settings_file()`), never in the repo. Every module reads its
paths from `config` at import, so a saved change takes effect when the app restarts (the supervisor does that on exit code RESTART).
"""
import json
import os
import subprocess
from pathlib import Path

import config

RESTART = 75                                                    # exit code the supervisor treats as "start me again now"
LABELS = {"data_root": "Workspace folder", "music_dir": "Music folder", "sfx_dir": "Sound effects folder"}
HELP = {
    "data_root": "Your footage and every video's work folder live here. Pick or create an empty folder on a drive with room to spare.",
    "music_dir": "Music you have the right to use. The app never ships music.",
    "sfx_dir": "Sound effects you have the right to use. The app never ships sounds.",
}


def current() -> dict:
    """What the app is using now, and where each value came from."""
    out = {}
    env = {"data_root": "WOOTS_DATA_ROOT", "music_dir": "WOOTS_MUSIC_DIR", "sfx_dir": "WOOTS_SFX_DIR"}
    paths = {"data_root": config.DATA_ROOT, "music_dir": config.MUSIC_DIR, "sfx_dir": config.SFX_DIR}
    for k in config.FOLDER_KEYS:
        if os.environ.get(env[k]):
            src = "environment"
        elif config._local().get(k):
            src = "config.local.json"
        elif config.user_settings().get(k):
            src = "settings"
        else:
            src = "default"
        p = Path(config.user_settings()[k]) if src == "settings" else paths[k]       # a saved folder shows at once; the app uses it after the restart
        out[k] = {"label": LABELS[k], "help": HELP[k], "path": str(p), "exists": p.is_dir(), "source": src,
                  "locked": src in ("environment", "config.local.json")}
    return out


def check_folder(path: str, make: bool = False) -> Path:
    """The folder as an absolute path, or ValueError saying what is wrong. `make` creates it (and its parents) when missing."""
    path = (path or "").strip().strip('"')
    if not path:
        raise ValueError("choose a folder")
    p = Path(os.path.abspath(path))
    if p.exists() and not p.is_dir():
        raise ValueError(f"{p} is a file, not a folder")
    if not p.is_dir():
        if not make:
            raise ValueError(f"{p} does not exist")
        try:
            p.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            raise ValueError(f"cannot create {p}: {e.strerror or e}") from e
    probe = p / ".woots-write-test"
    try:
        probe.write_text("x")
        probe.unlink()
    except OSError as e:
        raise ValueError(f"cannot write in {p}: {e.strerror or e}") from e
    return p


def save(values: dict) -> dict:
    """Validate and save folders. A blank value goes back to the default. Raises ValueError with a sentence for the user."""
    clean = {}
    for k, v in values.items():
        if k not in config.FOLDER_KEYS:
            raise ValueError(f"unknown setting {k}")
        if (v or "").strip():
            clean[k] = str(check_folder(v, make=True))
        else:
            clean[k] = ""
    config.save_user_settings(clean)
    return current()


def _run(args, timeout=20):
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout, encoding="utf-8", errors="replace",
                          creationflags=__import__("platformx").NO_WINDOW)


def claude_status() -> dict:
    """{installed, signed_in, detail, how}. `how` is a short instruction for the screen when something is missing."""
    import builder
    try:
        exe = builder.find_claude()
    except RuntimeError:
        return {"installed": False, "signed_in": False, "detail": "The Claude command is not installed.",
                "how": "Install Claude Code from https://claude.com/product/claude-code, then check again."}
    try:
        r = _run([exe, "auth", "status"])
    except (OSError, subprocess.TimeoutExpired) as e:
        return {"installed": True, "signed_in": False, "detail": f"Could not ask Claude: {e}", "how": "Check again, or sign in from a terminal with: claude auth login"}
    text = (r.stdout or "").strip()
    signed = parse_signed_in(text, r.returncode)
    return {"installed": True, "signed_in": signed, "exe": exe,
            "detail": account_line(text) if signed else "Not signed in to Claude.",
            "how": "" if signed else "Press Sign in; a browser window opens to finish."}


def parse_signed_in(text: str, code: int) -> bool:
    """`claude auth status` prints JSON ({"loggedIn": true, ...}) in current versions; older ones print plain text."""
    try:
        j = json.loads(text)
        if isinstance(j, dict) and "loggedIn" in j:
            return bool(j["loggedIn"])
    except ValueError:
        pass
    low = text.lower()
    if "not logged in" in low or "not signed in" in low or "no account" in low:
        return False
    return code == 0 and bool(text)


def account_line(text: str) -> str:
    try:
        j = json.loads(text)
        who = j.get("email") or j.get("account") or ""
        return f"Signed in to Claude{(' as ' + who) if who else ''}."
    except ValueError:
        return "Signed in to Claude."


_login = {"proc": None}


def start_login() -> dict:
    """Start `claude auth login` (it opens the browser). Returns right away; the screen polls claude_status()."""
    import builder
    exe = builder.find_claude()
    p = _login["proc"]
    if p is not None and p.poll() is None:
        return {"started": False, "detail": "A sign-in is already open in your browser."}
    _login["proc"] = subprocess.Popen([exe, "auth", "login"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                      creationflags=__import__("platformx").NO_WINDOW)
    return {"started": True, "detail": "Finish signing in in the browser window that opened."}


MIN_PYTHON = (3, 12)
MIN_NODE = 22
MIN_CLAUDE = (2, 1, 312)                                        # the Claude tool this app was tested with (--restricted, --permission-prompts)
MIN_FREE_GB = 30


def _ver(text: str) -> tuple:
    import re
    m = re.search(r"(\d+)\.(\d+)(?:\.(\d+))?", text or "")
    return tuple(int(x or 0) for x in m.groups()) if m else ()


def computer_check(run=None, tools=None, gpus=None, free=None, python=None) -> list:
    """What this computer has, one row each: {id, label, ok, detail, fix}. The arguments let a test fake any missing piece."""
    import hardware
    run = run or _run
    tools = tools if tools is not None else hardware.tools()
    gpus = gpus if gpus is not None else hardware.gpus()
    free = free if free is not None else hardware.free_gb(config.DATA_ROOT)
    py = python or tuple(__import__("sys").version_info[:3])
    rows = []

    def row(i, label, ok, detail, fix=""):
        rows.append({"id": i, "label": label, "ok": bool(ok), "detail": detail, "fix": "" if ok else fix})
    row("python", "Python", py >= MIN_PYTHON, ".".join(map(str, py)) if py >= MIN_PYTHON else f"Python {'.'.join(map(str, py))} is too old; this app needs {MIN_PYTHON[0]}.{MIN_PYTHON[1]} or newer.",
        "Install Python 3.12 (winget install Python.Python.3.12) and run setup.bat again.")
    row("ffmpeg", "ffmpeg", tools.get("ffmpeg") and tools.get("ffprobe"), "Found." if tools.get("ffmpeg") and tools.get("ffprobe") else "ffmpeg is not installed.",
        "Install it with: winget install Gyan.FFmpeg, then restart the app.")
    nv = ""
    if tools.get("node"):
        try:
            nv = run([tools["node"], "--version"], 10).stdout
        except (OSError, subprocess.TimeoutExpired):
            nv = ""
    node_ok = bool(nv) and _ver(nv)[:1] >= (MIN_NODE,)
    row("node", "Node", node_ok, nv.strip() if node_ok else (f"Node {nv.strip()} is too old; the graphics tool needs {MIN_NODE} or newer." if nv else "Node is not installed."),
        "Install it with: winget install OpenJS.NodeJS.LTS, then restart the app.")
    cv = ""
    if tools.get("claude"):
        try:
            cv = run([tools["claude"], "--version"], 15).stdout
        except (OSError, subprocess.TimeoutExpired):
            cv = ""
    want = ".".join(map(str, MIN_CLAUDE))
    claude_ok = bool(cv) and _ver(cv) >= MIN_CLAUDE
    row("claude", "Claude Code", claude_ok, ".".join(map(str, _ver(cv))) + " installed." if claude_ok else
        (f"Version {'.'.join(map(str, _ver(cv)))} is older than {want}, which this app needs." if cv else "The Claude command is not installed."),
        "Install or update it from https://claude.com/product/claude-code (or run: claude update).")
    rows.append({"id": "gpu", "label": "Graphics card", "ok": True, "fix": "",
                 "detail": ", ".join(f"{g['name']} ({g['vram_gb']:g} GB)" for g in gpus) if gpus else "No Nvidia card: recordings are read on the processor, which is slower."})
    row("disk", "Free disk space", free is None or free >= MIN_FREE_GB, f"{free:.0f} GB free on the workspace drive." if free is not None else "Could not tell.",
        f"Less than {MIN_FREE_GB} GB is free where your workspace is; models and renders need room. Choose a drive with more space.")
    return rows


_graphics = {"state": "idle", "error": ""}


def graphics_tool() -> dict:
    """Whether the pinned HyperFrames package has been fetched (so the first graphic build does not start with a download)."""
    import builder
    ok = (config.EDITOR_DATA / "hyperframes.ok").exists() and (config.EDITOR_DATA / "hyperframes.ok").read_text(encoding="utf-8").strip() == builder.HF
    return {"ready": ok, "state": "done" if ok else _graphics["state"], "error": _graphics["error"], "package": builder.HF}


def get_graphics_tool() -> dict:
    import builder
    import threading
    if _graphics["state"] == "running":
        return graphics_tool()
    _graphics.update(state="running", error="")

    def run():
        try:
            npx = __import__("shutil").which("npx", path=builder.tool_env().get("PATH")) or "npx"
            r = subprocess.run([npx, "--yes", builder.HF, "--help"], capture_output=True, text=True, timeout=600, encoding="utf-8", errors="replace",
                               stdin=subprocess.DEVNULL, env=builder.tool_env(), creationflags=__import__("platformx").NO_WINDOW)
            if r.returncode != 0:
                raise RuntimeError((r.stderr or r.stdout).strip()[-300:] or "the download failed")
            config.EDITOR_DATA.mkdir(parents=True, exist_ok=True)
            (config.EDITOR_DATA / "hyperframes.ok").write_text(builder.HF, encoding="utf-8")
            _graphics["state"] = "done"
        except Exception as e:                                  # noqa: BLE001 - shown on the card; the button tries again
            _graphics.update(state="error", error=str(e)[:300])
    threading.Thread(target=run, daemon=True, name="get-graphics-tool").start()
    return graphics_tool()


RELEASES = "https://api.github.com/repos/developingwoot/woots-editor/releases/latest"


def check_update(fetch=None) -> dict:
    """Ask the GitHub releases page for the newest version. Only called when the person presses "Check for updates": the app makes no network call on its own."""
    import urllib.request
    from version import __version__
    try:
        if fetch is None:
            req = urllib.request.Request(RELEASES, headers={"User-Agent": "WootsEditor", "Accept": "application/vnd.github+json"})
            fetch = lambda: json.loads(urllib.request.urlopen(req, timeout=15).read().decode("utf-8"))
        j = fetch()
    except Exception as e:                                       # noqa: BLE001 - shown as one sentence
        return {"current": __version__, "error": f"Could not reach the releases page ({type(e).__name__}). Try again later."}
    latest = str(j.get("tag_name", "")).lstrip("v")
    return {"current": __version__, "latest": latest, "newer": bool(_ver(latest)) and _ver(latest) > _ver(__version__), "url": j.get("html_url", ""), "error": ""}


def view() -> dict:
    import channel
    from version import __version__
    return {"version": __version__, "folders": current(), "folders_needed": config.needs_setup(), "first_run": config.needs_setup() or not channel.is_set(), "claude": claude_status(),
            "settings_file": str(config.settings_file())}
