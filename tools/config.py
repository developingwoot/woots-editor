"""Where the editor's CODE lives versus where its DATA lives.

CODE_ROOT  the folder holding tools/, models/, fonts/, graphics/ (this repo).
DATA_ROOT  the footage share (default <workspace>). Holds the video folders, Music and SFX.
EDITOR_DATA  DATA_ROOT/_editor: the per-video work folders and the app's own state files.

Override, strongest first: environment variable, then config.local.json in the repo root
(git-ignored), then the per-user settings file (written by the app's Settings screen), then the default.
Keys: data_root, work_root, music_dir, sfx_dir, state_dir, python.
Env vars: WOOTS_DATA_ROOT, WOOTS_WORK_ROOT, WOOTS_MUSIC_DIR, WOOTS_SFX_DIR, WOOTS_STATE_DIR, WOOTS_PYTHON.
The per-user file is %APPDATA%\\WootsEditor\\settings.json (~/.config/woots-editor/settings.json elsewhere); WOOTS_SETTINGS_FILE names another.

Paths use abspath, never resolve(): resolve() turns the mapped drive Z:\\ into the UNC name.
"""
import json
import os
import sys
from pathlib import Path

CODE_ROOT = Path(os.path.abspath(__file__)).parent.parent
_DEFAULT_DATA_ROOT = os.path.join(os.path.expanduser("~"), "Documents", "WootsEditor")
FOLDER_KEYS = ("data_root", "music_dir", "sfx_dir")             # the folders the Settings screen asks for


def settings_file() -> Path:
    env = os.environ.get("WOOTS_SETTINGS_FILE")
    if env:
        return Path(os.path.abspath(env))
    if os.name == "nt":
        return Path(os.path.abspath(os.environ.get("APPDATA") or Path.home())) / "WootsEditor" / "settings.json"
    return Path.home() / ".config" / "woots-editor" / "settings.json"


def _read(path: Path) -> dict:
    try:
        v = json.loads(path.read_text(encoding="utf-8"))
        return v if isinstance(v, dict) else {}
    except (OSError, ValueError):
        return {}


def _local() -> dict:
    return _read(CODE_ROOT / "config.local.json")


def user_settings() -> dict:
    return _read(settings_file())


def save_user_settings(values: dict) -> None:
    """Merge `values` into the per-user file; an empty string removes a key. Takes effect when the app restarts."""
    cur = user_settings()
    for k, v in values.items():
        if v in ("", None):
            cur.pop(k, None)
        else:
            cur[k] = str(v)
    p = settings_file()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(cur, indent=2), encoding="utf-8")
    os.replace(tmp, p)


def _pick(env: str, key: str, default) -> Path:
    v = os.environ.get(env) or _local().get(key) or user_settings().get(key) or default
    return Path(os.path.abspath(str(v)))


def needs_setup() -> bool:
    """True on a fresh install: nobody named a data folder and the built-in default is not there."""
    named = os.environ.get("WOOTS_DATA_ROOT") or _local().get("data_root") or user_settings().get("data_root")
    return not named and not Path(_DEFAULT_DATA_ROOT).is_dir()


DATA_ROOT = _pick("WOOTS_DATA_ROOT", "data_root", _DEFAULT_DATA_ROOT)
EDITOR_DATA = _pick("WOOTS_STATE_DIR", "state_dir", DATA_ROOT / "_editor")
WORK = _pick("WOOTS_WORK_ROOT", "work_root", EDITOR_DATA / "work")
MUSIC_DIR = _pick("WOOTS_MUSIC_DIR", "music_dir", DATA_ROOT / "Music")
SFX_DIR = _pick("WOOTS_SFX_DIR", "sfx_dir", DATA_ROOT / "SFX")
PYTHON = _pick("WOOTS_PYTHON", "python", sys.executable)        # the interpreter the app starts its tools with: the one running it, unless set (env var WOOTS_PYTHON or "python" in config.local.json)
