"""What this computer can do: the graphics card and its memory, system memory, free disk space, and the programs the editor needs.

No models, no network: `nvidia-smi` and the operating system answer. Used by `engines.recommend` to offer models that fit the card.
"""
import ctypes
import os
import shutil
import subprocess
from pathlib import Path


def gpus() -> list:
    """[{name, vram_gb}] for each Nvidia card; empty when there is none (or the driver is not installed)."""
    exe = shutil.which("nvidia-smi")
    if not exe:
        return []
    try:
        r = subprocess.run([exe, "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=10,
                           creationflags=__import__("platformx").NO_WINDOW)
    except (OSError, subprocess.TimeoutExpired):
        return []
    return parse_gpus(r.stdout) if r.returncode == 0 else []


def parse_gpus(text: str) -> list:
    out = []
    for line in text.strip().splitlines():
        name, _, mem = line.rpartition(",")
        try:
            out.append({"name": name.strip(), "vram_gb": round(float(mem) / 1024, 1)})
        except ValueError:
            continue
    return out


def ram_gb() -> float | None:
    if os.name == "nt":
        class Mem(ctypes.Structure):
            _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong), ("total", ctypes.c_ulonglong), ("avail", ctypes.c_ulonglong),
                        ("tpf", ctypes.c_ulonglong), ("apf", ctypes.c_ulonglong), ("tv", ctypes.c_ulonglong), ("av", ctypes.c_ulonglong), ("ave", ctypes.c_ulonglong)]
        m = Mem()
        m.length = ctypes.sizeof(Mem)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m)):
            return round(m.total / 2**30, 1)
        return None
    try:
        return round(os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 2**30, 1)
    except (ValueError, OSError, AttributeError):
        return None


def free_gb(path) -> float | None:
    """Free space on the drive holding `path` (the nearest folder that exists)."""
    p = Path(os.path.abspath(str(path)))
    while not p.exists() and p != p.parent:
        p = p.parent
    try:
        return round(shutil.disk_usage(p).free / 2**30, 1)
    except OSError:
        return None


def tools() -> dict:
    """The programs the editor starts: {ffmpeg, ffprobe, node, claude}: path or None."""
    import builder
    path = builder.tool_env().get("PATH")                              # the same search path the editor's own tools get (it adds the WinGet ffmpeg folder)
    out = {k: shutil.which(k, path=path) for k in ("ffmpeg", "ffprobe", "node")}
    try:
        out["claude"] = builder.find_claude()
    except RuntimeError:
        out["claude"] = None
    return out


def probe(data_root=None) -> dict:
    import config
    g = gpus()
    return {"gpus": g, "vram_gb": max([x["vram_gb"] for x in g], default=0.0), "ram_gb": ram_gb(), "free_gb": free_gb(data_root or config.DATA_ROOT), "tools": tools()}
