"""The models the editor runs, which of them fit this computer, and fetching the ones the user picks. Nothing is bundled: models download on first use.

Three jobs: `speech` (reads the recordings into words with times), `vision` (describes the footage), `embed` (SigLIP, finds a clip by what it shows; every setup needs it).
The choice is saved per user (`speech_engine`, `vision_engine` in the settings file, see config.py) and read by transcribe.py and brolllib.py.
`built` is false for an entry that is listed but not wired in yet: it is shown and cannot be chosen.
"""
import os
import threading
from pathlib import Path

import config
import hardware

CATALOG = [
    {"id": "parakeet-0.6b", "job": "speech", "name": "Parakeet 0.6B (Nvidia)", "repo": "nvidia/parakeet-tdt-0.6b-v2", "gb": 2.5, "min_vram": 6, "needs_gpu": True,
     "built": True, "note": "Fast, with a time for every word. Needs an Nvidia graphics card."},
    {"id": "whisper-large-v3", "job": "speech", "name": "Whisper large-v3", "repo": "Systran/faster-whisper-large-v3", "gb": 3.1, "min_vram": 6, "needs_gpu": True,
     "built": True, "runner": "whisper", "note": "Accurate, with a time for every word. Runs on an Nvidia card; use it where Parakeet does not work."},
    {"id": "whisper-small", "job": "speech", "name": "Whisper small (any computer)", "repo": "Systran/faster-whisper-small", "gb": 0.5, "min_vram": 0, "needs_gpu": False,
     "built": True, "runner": "whisper", "note": "For computers without an Nvidia card: runs on the processor, slower than real time on long recordings and less exact on technical words."},
    {"id": "qwen3-vl-8b", "job": "vision", "name": "Qwen3-VL 8B", "repo": "Qwen/Qwen3-VL-8B-Instruct", "gb": 17.6, "min_vram": 10, "needs_gpu": True,
     "built": True, "note": "Best descriptions. Loaded in 4-bit, so it fits a 12 GB card; the download is large."},
    {"id": "qwen3-vl-4b", "job": "vision", "name": "Qwen3-VL 4B", "repo": "Qwen/Qwen3-VL-4B-Instruct", "gb": 8.9, "min_vram": 6, "needs_gpu": True,
     "built": True, "note": "Smaller and quicker; descriptions are less detailed (quality not measured yet)."},
    {"id": "qwen3-vl-2b", "job": "vision", "name": "Qwen3-VL 2B", "repo": "Qwen/Qwen3-VL-2B-Instruct", "gb": 4.3, "min_vram": 4, "needs_gpu": True,
     "built": True, "note": "For small cards; short descriptions (quality not measured yet). Tag your footage to make up for it."},
    {"id": "siglip", "job": "embed", "name": "SigLIP (finds clips by what they show)", "repo": "google/siglip-base-patch16-224", "gb": 1.6, "min_vram": 0, "needs_gpu": False,
     "built": True, "note": "Small; every setup uses it."},
]
DEFAULTS = {"speech": "parakeet-0.6b", "vision": "qwen3-vl-8b", "embed": "siglip"}       # what the code ran on before there was a choice
CHOICE_KEYS = {"speech": "speech_engine", "vision": "vision_engine"}


def by_id(eid: str) -> dict:
    for e in CATALOG:
        if e["id"] == eid:
            return e
    raise ValueError(f"unknown model {eid}")


def fits(e: dict, hw: dict) -> tuple[bool, str]:
    if e["needs_gpu"] and not hw["gpus"]:
        return False, "needs an Nvidia graphics card"
    if hw["vram_gb"] < e["min_vram"]:
        return False, f"needs about {e['min_vram']} GB of video memory; this card has {hw['vram_gb']:g}"
    return True, ""


def recommend(job: str, hw: dict) -> str | None:
    """The best entry of `job` that is built and fits: the first in catalog order (best first)."""
    for e in CATALOG:
        if e["job"] == job and e["built"] and fits(e, hw)[0]:
            return e["id"]
    return None


def chosen(job: str) -> dict:
    """The catalog entry in use for `job`: the user's saved choice if it is a built entry of that job, else the default."""
    want = config.user_settings().get(CHOICE_KEYS.get(job, ""), "")
    for e in CATALOG:
        if e["id"] == want and e["job"] == job and e["built"]:
            return e
    return by_id(DEFAULTS[job])


def choose(job: str, eid: str):
    e = by_id(eid)
    if e["job"] != job or job not in CHOICE_KEYS:
        raise ValueError("that model is not for this job")
    if not e["built"]:
        raise ValueError(f"{e['name']} is not available yet")
    config.save_user_settings({CHOICE_KEYS[job]: eid})


# ----------------------------------------------------------------------------- what is on disk
def cache_root() -> Path:
    try:
        from huggingface_hub import constants
        return Path(constants.HF_HUB_CACHE)
    except ImportError:
        return Path(os.environ.get("HF_HOME", Path.home() / ".cache" / "huggingface")) / "hub"


def cached_bytes(repo: str) -> int:
    """Bytes of the model in the cache: the finished files of the newest snapshot (real files on Windows, links into blobs elsewhere) plus downloads still in progress."""
    root = cache_root() / ("models--" + repo.replace("/", "--"))
    done = 0
    try:
        snaps = [d for d in (root / "snapshots").iterdir() if d.is_dir()]
        done = max((sum(f.stat().st_size for f in d.rglob("*") if f.is_file()) for d in snaps), default=0)
    except OSError:
        pass
    try:
        part = sum(f.stat().st_size for f in (root / "blobs").iterdir() if f.name.endswith(".incomplete"))
    except OSError:
        part = 0
    return done + part


def installed(e: dict) -> bool:
    return cached_bytes(e["repo"]) >= 0.9 * e["gb"] * 1e9 and not _running(e["repo"])


# ----------------------------------------------------------------------------- downloads
_dl: dict = {}
_lock = threading.Lock()


def _running(repo: str) -> bool:
    return _dl.get(repo, {}).get("state") == "running"


def _fetch(repo: str):
    from huggingface_hub import snapshot_download
    snapshot_download(repo)


def download(eid: str) -> dict:
    e = by_id(eid)
    free = hardware.free_gb(cache_root())
    with _lock:
        if _running(e["repo"]):
            return status(e)
        if installed(e):
            return status(e)
        need = e["gb"] * 1.1 - cached_bytes(e["repo"]) / 1e9
        if free is not None and free < need:
            raise ValueError(f"not enough free space: {e['name']} needs about {need:.0f} GB and {free:.0f} GB is free on the drive that holds the model cache")
        _dl[e["repo"]] = {"state": "running", "error": ""}

    def run():
        try:
            _fetch(e["repo"])
            _dl[e["repo"]] = {"state": "done", "error": ""}
        except Exception as ex:                                    # noqa: BLE001 - shown to the user; the next press retries and resumes
            _dl[e["repo"]] = {"state": "error", "error": str(ex)[:300]}
    threading.Thread(target=run, daemon=True, name=f"download-{eid}").start()
    return status(e)


def status(e: dict) -> dict:
    d = _dl.get(e["repo"], {})
    got = cached_bytes(e["repo"])
    state = "running" if d.get("state") == "running" else "installed" if installed(e) else "error" if d.get("state") == "error" else "partial" if got > 0.02 * e["gb"] * 1e9 else "missing"
    return {"state": state, "progress": min(1.0, got / (e["gb"] * 1e9)), "error": d.get("error", "") if state == "error" else ""}


def view(hw: dict | None = None) -> dict:
    """What the Settings screen shows: the machine, and for each job its models with fit, state and the choice."""
    hw = hw or hardware.probe()
    jobs = {}
    for job in ("speech", "vision", "embed"):
        pick = chosen(job)["id"]
        rec = recommend(job, hw)
        rows = []
        for e in (x for x in CATALOG if x["job"] == job):
            ok, why = fits(e, hw)
            rows.append({"id": e["id"], "name": e["name"], "gb": e["gb"], "note": e["note"], "built": e["built"], "fits": ok, "why": "" if ok else why,
                         "recommended": e["id"] == rec, "chosen": e["id"] == pick, **status(e)})
        jobs[job] = rows
    return {"hardware": hw, "jobs": jobs}
