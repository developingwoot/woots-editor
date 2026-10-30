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
                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


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
                                      creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return {"started": True, "detail": "Finish signing in in the browser window that opened."}


def view() -> dict:
    import channel
    return {"folders": current(), "folders_needed": config.needs_setup(), "first_run": config.needs_setup() or not channel.is_set(), "claude": claude_status(),
            "settings_file": str(config.settings_file())}
