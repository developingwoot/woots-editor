"""Which Claude model, and how hard it thinks, for each kind of background run. Chosen in Settings, saved in the per-user settings file.

Jobs:  edit      the cut, outline, takes, cold open, shot matching, framing, publishing text: everything that is not graphics or shorts
       graphics  the Claude run that designs and builds a graphic
       critic    the second Claude that looks at a built graphic ("off" = no critic pass)
       accuracy  the fact check of the script and graphics
       shorts    choosing, tightening, planning and titling shorts, and applying the host's feedback on them

A video can still keep its own graphics model in its workflow settings (the older Dashboard tab); this is the default for every video.
Stored as flat keys (`model_<job>`, `effort_<job>`) because config.save_user_settings keeps strings.
"""
import config

MODELS = ("sonnet", "opus", "haiku", "fable")
EFFORTS = ("low", "medium", "high", "xhigh", "max")
JOBS = {
    "edit": ("Editing", "The rough cut, outline, takes, hooks, shot matching, framing and publishing text.", "sonnet", "medium"),
    "graphics": ("Graphics", "Designing and building each graphic.", "sonnet", "medium"),
    "critic": ("Graphics critic", "Looks at each built graphic and lists what to fix. Off skips this pass.", "opus", "medium"),
    "accuracy": ("Fact check", "Checks the claims in the script and graphics against the web.", "opus", "high"),
    "shorts": ("Shorts", "Choosing shorts, tightening them, planning graphics, writing titles and applying your feedback.", "sonnet", "medium"),
}
OFF_OK = ("critic",)


def default(job: str) -> tuple:
    d = JOBS[job]
    return d[2], d[3]


def get(job: str) -> tuple:
    """(model, effort) for a job: the user's choice if it is a valid one, else the default."""
    if job not in JOBS:
        raise ValueError(f"unknown job {job!r}")
    us = config.user_settings()
    model, effort = default(job)
    m = us.get(f"model_{job}")
    if m in MODELS or (m == "off" and job in OFF_OK):
        model = m
    e = us.get(f"effort_{job}")
    if e in EFFORTS:
        effort = e
    return model, effort


def flags(job: str) -> list:
    """The `claude -p` arguments for a job."""
    model, effort = get(job)
    return ["--model", model, "--effort", effort]


def view() -> dict:
    """What the Settings screen shows."""
    rows = []
    for job, (label, help_, dm, de) in JOBS.items():
        model, effort = get(job)
        rows.append({"job": job, "label": label, "help": help_, "model": model, "effort": effort, "default_model": dm, "default_effort": de,
                     "models": (["off"] if job in OFF_OK else []) + list(MODELS)})
    return {"jobs": rows, "efforts": list(EFFORTS)}


def save(choices: dict) -> dict:
    """choices = {job: {"model": ..., "effort": ...}}; anything invalid is refused and nothing is saved."""
    out = {}
    for job, c in (choices or {}).items():
        if job not in JOBS:
            raise ValueError(f"unknown job {job!r}")
        if "model" in c:
            if c["model"] not in MODELS and not (c["model"] == "off" and job in OFF_OK):
                raise ValueError(f"{JOBS[job][0]}: the model must be one of {', '.join(MODELS)}")
            out[f"model_{job}"] = c["model"]
        if "effort" in c:
            if c["effort"] not in EFFORTS:
                raise ValueError(f"{JOBS[job][0]}: the effort must be one of {', '.join(EFFORTS)}")
            out[f"effort_{job}"] = c["effort"]
    config.save_user_settings(out)
    return view()


def graphics_defaults() -> dict:
    """The graphics settings a video gets unless it saved its own (read by workflow)."""
    bm, be = get("graphics")
    cm, ce = get("critic")
    return {"build_model": bm, "build_effort": be, "critic_model": cm, "critic_effort": ce}
