"""The few places the app depends on the operating system, in one module: hiding console windows, opening a folder, stopping a process and its children,
and where ffmpeg is usually installed. Windows is the supported system; the fallbacks let the code import and most tests run elsewhere (no promise of support)."""
import os
import signal
import subprocess
import sys
from pathlib import Path

IS_WINDOWS = os.name == "nt"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)          # 0 on other systems


def open_folder(path) -> None:
    """Show a folder in the file manager."""
    p = str(path)
    if IS_WINDOWS:
        os.startfile(p)
    else:
        subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", p], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def kill_tree(proc) -> None:
    """Stop a process and everything it started."""
    if not proc or proc.poll() is not None:
        return
    if IS_WINDOWS:
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True)
    else:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except (OSError, ProcessLookupError):
            proc.kill()


def ffmpeg_dirs() -> list[Path]:
    """Folders where a package manager puts ffmpeg when it is not on PATH."""
    base = Path(os.environ.get("LOCALAPPDATA", ""))
    return sorted(base.glob("Microsoft/WinGet/Packages/Gyan.FFmpeg*/*/bin")) if IS_WINDOWS and base.name else []
