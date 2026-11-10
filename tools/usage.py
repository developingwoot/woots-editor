"""Dashboard numbers: how much of the host's Claude plan this application uses, and how much of his time the process saved.

The host is on a Claude plan (Pro). A plan is not billed per token; it has limits (a 5-hour window and a weekly window) and the honest question is "how much of my plan does this
application use?". What can and cannot be known:
  * The plan's own percentages (5-hour, weekly) are shown on the Claude desktop app's usage card. This Python app cannot read them, so Claude writes a SNAPSHOT of them to
    `_editor/plan-usage.json` whenever it checks (the dashboard shows when). Without a snapshot the dashboard still shows the app's own numbers for the last 7 days.
  * Every Claude Code session on this PC is saved on disk with token counts. "This application" = the chat workspace it is built and used in plus the Build board's background
    runs. The rest of the PC's Claude Code use (other chats) is counted in the total so the share is honest. Claude on the web or on a phone is not visible here.
  * Weighted tokens: input x1, cache writes x1.25, cache reads x0.1, output x5 (the usual price ratios): an estimate of how heavy a message was, not a bill.
  * Estimated share of the weekly limit = the plan's weekly percent x (this application's weighted tokens / all Claude Code weighted tokens in the same window). It assumes
    the plan's usage came from Claude Code on this PC; it is labelled an estimate.
  * A video's share = its assigned chat tokens plus its Build board runs, against all of this application's use. A chat cannot be tied to a video automatically, so the host assigns it.
Pure Python, no heavy imports.
"""
import calendar
import json
import os
import re
import sys
import threading
import time
from pathlib import Path

TOOLS = Path(os.path.abspath(__file__)).parent
EDITOR = TOOLS.parent
import config
import config as _cfg_mod
WORK = config.WORK
CFG = config.EDITOR_DATA / "dashboard.json"
PLAN_FILE = config.EDITOR_DATA / "plan-usage.json"
sys.path.insert(0, str(TOOLS))
import workflow  # noqa: E402

WEIGHT = {"input": 1.0, "cache_write": 1.25, "cache_read": 0.1, "output": 5.0}
_msg_cache: dict = {}                         # path -> (size, mtime, rows)
_lock = threading.Lock()


def read_json(p: Path, default=None):
    if not p.exists():
        return default
    try:
        return json.loads(p.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError:
        return default


def write_json(p: Path, data):
    tmp = p.with_name(f"{p.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
    for i in range(8):
        try:
            os.replace(tmp, p)
            return
        except PermissionError:
            if i == 7:
                raise
            time.sleep(0.05 * (i + 1))


def wtok(a: dict) -> float:
    return sum(float(a.get(k, 0) or 0) * w for k, w in WEIGHT.items())


# ----------------------------------------------------------------------------- assignments kept by the dashboard
def config() -> dict:
    c = read_json(CFG, {}) or {}
    c.setdefault("assign", {})
    return c


def assign(session: str, target: str) -> dict:
    """target: a video's slug, 'tools' (building the app and the skills) or '' to clear."""
    c = config()
    if target and target != "tools" and not (WORK / target).is_dir():
        raise ValueError(f"unknown video {target!r}")
    if target:
        c["assign"][session] = target
    else:
        c["assign"].pop(session, None)
    write_json(CFG, c)
    return c


def set_plan_snapshot(plan: dict) -> dict:
    """Store the plan limits as read from the desktop app's usage card: {plan, windows: [{label, percentUsed, resetsAt}], extraUsage}."""
    snap = {"checked": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()), "plan": plan.get("plan"), "windows": plan.get("windows", []), "extraUsage": plan.get("extraUsage")}
    write_json(PLAN_FILE, snap)
    return snap


# ----------------------------------------------------------------------------- every Claude Code session on this machine
def _epoch(ts: str) -> float:
    try:
        return float(calendar.timegm(time.strptime(ts[:19], "%Y-%m-%dT%H:%M:%S")))      # the saved timestamps are UTC
    except (ValueError, TypeError):
        return 0.0


def machine_messages(since: float) -> list:
    """[(message_id, session_id, epoch, project_dir, weighted_tokens)] for assistant messages from every saved Claude Code session on this PC
    (this workspace's chats, other chats and the Build board's background runs) in files touched since `since`. One message counts once even if it is saved twice."""
    proj = Path.home() / ".claude" / "projects"
    if not proj.is_dir():
        return []
    seen = {}
    for f in proj.rglob("*.jsonl"):
        try:
            st = f.stat()
        except OSError:
            continue
        if st.st_mtime < since:
            continue
        key = str(f)
        with _lock:
            hit = _msg_cache.get(key)
        if hit and hit[0] == st.st_size and hit[1] == st.st_mtime:
            rows = hit[2]
        else:
            uniq = {}
            try:
                with open(f, encoding="utf-8", errors="replace") as fh:
                    for line in fh:
                        if '"usage"' not in line:
                            continue
                        try:
                            d = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        m = d.get("message") or {}
                        u = m.get("usage")
                        if not u or d.get("type") != "assistant":
                            continue
                        uniq[m.get("id") or d.get("uuid")] = (d.get("timestamp") or "", u)       # later lines of one message carry the final counts
            except OSError:
                continue
            top = f.relative_to(proj).parts
            pdir = top[0]
            sess = f.stem if len(top) == 2 else top[1]                                          # sub-agent files live in <project>/<session>/subagents
            rows = []
            for mid, (ts, u) in uniq.items():
                a = {"input": u.get("input_tokens") or 0, "cache_write": u.get("cache_creation_input_tokens") or 0,
                     "cache_read": u.get("cache_read_input_tokens") or 0, "output": u.get("output_tokens") or 0}
                rows.append((mid, sess, _epoch(ts), pdir, wtok(a)))
            with _lock:
                _msg_cache[key] = (st.st_size, st.st_mtime, rows)
        for mid, sess, ep, pdir, w in rows:
            if ep >= since:
                seen[mid] = (sess, ep, pdir, w)
    return [(mid, *v) for mid, v in seen.items()]


def _work_prefix() -> str:
    """How Claude Code names the project folder of a run started in the work folders (the path with every character that is not a letter or digit turned into a dash)."""
    return re.sub(r"[^A-Za-z0-9]", "-", str(WORK)) + "-"


def is_app_project(pdir: str) -> bool:
    """This application = the chat workspace it is built and used in, plus the Build board's background runs."""
    return pdir.startswith(_work_prefix()) or any(k in pdir for k in (_cfg_mod._local().get("chat_projects") or []))


def plan_snapshot() -> dict | None:
    j = read_json(PLAN_FILE)
    if not j:
        return None
    ep = _epoch(j.get("checked", ""))
    j["age_minutes"] = max(0, int((time.time() - ep) / 60)) if ep else None
    now = time.time()
    for w in j.get("windows", []):
        left = _epoch(w.get("resetsAt", "")) - now
        w["resetsIn"] = "reset since" if left <= 0 else f"{int(left // 86400)}d {int(left % 86400 // 3600)}h" if left >= 86400 else f"{int(left // 3600)}h {int(left % 3600 // 60)}m"
    return j


def week_window(snap: dict | None) -> tuple[float, float, str]:
    """(start, end, source): the plan's weekly window if a snapshot knows when it resets, else the last 7 days."""
    now = time.time()
    for w in (snap or {}).get("windows", []):
        if str(w.get("label", "")).lower().startswith("weekly") and w.get("resetsAt"):
            end = _epoch(w["resetsAt"])
            if end >= now:
                return end - 7 * 86400, end, "plan"
            return now - 7 * 86400, now, "expired"                  # the plan window the snapshot describes has reset since: its percentages no longer apply
    return now - 7 * 86400, now, "last7"


# ----------------------------------------------------------------------------- the plan's limits, read from a headless Claude run
def _iso(ep: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ep))


def save_rate_limit(info: dict) -> dict | None:
    """A headless `claude -p` run emits a rate_limit_event with the plan's real limits ({unifiedWindows: {five_hour|seven_day: {utilization 0-1, resetsAt epoch}}}).
    Every run the app starts passes one through here, so the Dashboard's plan numbers stay fresh without a separate check."""
    uw = (info or {}).get("unifiedWindows") or {}
    windows = []
    for key, label in (("five_hour", "5-hour limit"), ("seven_day", "Weekly · all models")):
        w = uw.get(key)
        if w and w.get("resetsAt"):
            windows.append({"label": label, "percentUsed": round(float(w.get("utilization") or 0) * 100), "resetsAt": _iso(float(w["resetsAt"]))})
    if not windows:
        return None
    old = read_json(PLAN_FILE, {}) or {}
    snap = {"checked": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()), "plan": old.get("plan") or "plan", "windows": windows,
            "extraUsage": old.get("extraUsage"), "source": "a Claude run started by the app", "overage": info.get("overageStatus")}
    write_json(PLAN_FILE, snap)
    return snap


def refresh_plan() -> dict:
    """Ask Claude for nothing but the plan's limits: one tiny haiku call with no tools (about 4,000 tokens, a fraction of a percent of a window)."""
    import subprocess
    import tempfile
    import builder
    cmd = [builder.find_claude(), "-p", "Reply with the single word ok.", "--model", "haiku", "--output-format", "stream-json", "--verbose", "--max-turns", "1", "--tools", ""]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=tempfile.gettempdir(), stdin=subprocess.DEVNULL, timeout=120)
    for line in r.stdout.splitlines():
        if '"rate_limit_event"' in line:
            try:
                snap = save_rate_limit(json.loads(line).get("rate_limit_info") or {})
            except json.JSONDecodeError:
                continue
            if snap:
                return snap
    raise ValueError("Claude did not report the plan limits (is it signed in?): " + (r.stderr or r.stdout or "")[-200:])


# ----------------------------------------------------------------------------- Claude runs the app starts (Build board)
def claude_runs(work: str, name: str) -> dict:
    j = read_json(WORK / work / f"{name}.sections.status.json", {}) or {}
    runs = []
    for s in j.get("sections", []):
        if s.get("mode") != "agent" and s.get("cost_usd") is None:
            continue
        u = s.get("usage") or {}
        a = {"input": u.get("input_tokens") or 0, "cache_write": u.get("cache_creation_input_tokens") or 0,
             "cache_read": u.get("cache_read_input_tokens") or 0, "output": u.get("output_tokens") or 0}
        runs.append({"id": s.get("id"), "title": s.get("title"), "status": s.get("status"), "cost_usd": s.get("cost_usd") or 0.0,
                     "turns": s.get("turns"), "model": s.get("model"), "started": s.get("started"), "finished": s.get("finished"),
                     "duration_s": round(s["duration_ms"] / 1000, 1) if s.get("duration_ms") else None,
                     "tokens_in": a["input"] + a["cache_write"] + a["cache_read"] if u else None, "tokens_out": a["output"] if u else None})
    local = [s for s in j.get("sections", []) if s.get("mode") == "local" and s.get("status") == "done"]
    return {"runs": runs, "cost_usd": round(sum(r["cost_usd"] for r in runs), 4), "local_sections": len(local)}


def local_work(work: str, name: str) -> list[dict]:
    wd = WORK / work
    out = []
    for f in sorted(wd.glob("* v*(1080p).final.json")):
        j = read_json(f, {}) or {}
        if j.get("elapsed"):
            out.append({"what": f"Final render v{j.get('version', '?')}", "seconds": j["elapsed"], "when": j.get("created")})
    sr = read_json(wd / f"{name}.selfreview.json", None)
    if sr:
        out.append({"what": "Self-review (8 checks)", "seconds": None, "when": sr.get("created") or sr.get("t")})
    if (wd / f"{name}.clips.json").exists():
        out.append({"what": "Transcribed and matched the takes (Parakeet)", "seconds": None, "when": None})
    if (wd / "storyboard").is_dir():
        out.append({"what": "Storyboard frames", "seconds": None, "when": None})
    return out


def savings(s: dict) -> dict | None:
    before, actual = float(s.get("manual_hours_before") or 0), float(s.get("hours_actual") or 0)
    if not before:
        return None
    saved = before - actual
    rate = float(s.get("hourly_rate_usd") or 0)
    return {"before": before, "actual": actual, "saved": round(saved, 1), "value_usd": round(saved * rate, 2) if rate else None, "rate": rate or None}


# ----------------------------------------------------------------------------- the week
def week_summary() -> dict:
    """What this application used in the plan's current weekly window, against everything Claude Code used on this PC in the same window."""
    c = config()
    snap = plan_snapshot()
    start, end, src = week_window(snap)
    inwin = [m for m in machine_messages(start) if start <= m[2] <= end + 3600]
    machine = sum(m[4] for m in inwin)
    sessions: dict = {}
    for mid, sess, ep, pdir, w in inwin:
        if not is_app_project(pdir):
            continue
        s = sessions.setdefault(sess, {"id": sess, "first": ep, "last": ep, "messages": 0, "weighted": 0.0, "background": pdir.startswith(_work_prefix())})
        s["first"], s["last"] = min(s["first"], ep), max(s["last"], ep)
        s["messages"] += 1
        s["weighted"] += w
    vids = [(w["work"], n) for w in workflow.list_videos() for n in w["names"]]
    per = {w: {"work": w, "name": n, "chat": 0.0, "app": 0.0, "app_usd": 0.0, "runs": 0} for w, n in vids}
    tools = unassigned = 0.0
    rows = []
    iso = lambda ep: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ep))
    for sid, s in sessions.items():
        if s["background"]:
            continue
        tgt = c["assign"].get(sid, "")
        rows.append({"id": sid, "messages": s["messages"], "weighted": round(s["weighted"]), "assigned": tgt, "first": iso(s["first"]), "last": iso(s["last"])})
        if tgt == "tools":
            tools += s["weighted"]
        elif tgt in per:
            per[tgt]["chat"] += s["weighted"]
        else:
            unassigned += s["weighted"]
    bg = sum(s["weighted"] for s in sessions.values() if s["background"])
    for w, n in vids:
        for r in claude_runs(w, n)["runs"]:
            per[w]["app_usd"] += r["cost_usd"]
            per[w]["runs"] += 1
    app_total = sum(s["weighted"] for s in sessions.values())
    wk = next((w for w in (snap or {}).get("windows", []) if str(w.get("label", "")).lower().startswith("weekly")), None)
    if src == "expired":
        wk = None
    share = app_total / machine if machine else 0.0
    # the background runs are saved as their own sessions: split them over the videos by the Build board's records is not possible, so they stay one line
    for p in per.values():
        p["weighted"] = p["chat"]
        p["share"] = round(p["weighted"] / app_total, 4) if app_total else 0.0
        p["pct_of_plan"] = round(wk["percentUsed"] * p["weighted"] / machine, 1) if wk and machine else None
    return {"snapshot": snap, "window": {"start": iso(start), "end": iso(end), "source": src}, "machine": round(machine), "app": round(app_total), "app_share": round(share, 4),
            "weekly_pct": wk["percentUsed"] if wk else None, "app_pct_of_plan": round(wk["percentUsed"] * share, 1) if wk else None,
            "background": round(bg), "tools": round(tools), "unassigned": round(unassigned), "videos": per, "sessions": sorted(rows, key=lambda r: r["last"], reverse=True),
            "weights": WEIGHT, "app_usd": round(sum(p["app_usd"] for p in per.values()), 4)}


def video(work: str, name: str) -> dict:
    s = workflow.state(work, name)["settings"]
    m = week_summary()
    return {"work": work, "name": name, "claude": claude_runs(work, name), "local": local_work(work, name), "savings": savings(s),
            "week": {**m["videos"].get(work, {}), "app": m["app"], "weekly_pct": m["weekly_pct"]}}


def all_videos() -> dict:
    vids = [(w["work"], n) for w in workflow.list_videos() for n in w["names"]]
    per = []
    for work, name in vids:
        c = claude_runs(work, name)
        s = workflow.state(work, name)["settings"]
        per.append({"work": work, "name": name, "cost_usd": c["cost_usd"], "runs": len(c["runs"]), "savings": savings(s)})
    sav = [p["savings"] for p in per if p["savings"]]
    return {"videos": per, "cost_usd": round(sum(p["cost_usd"] for p in per), 4), "runs": sum(p["runs"] for p in per),
            "saved_hours": round(sum(x["saved"] for x in sav), 1) if sav else None,
            "saved_usd": round(sum(x["value_usd"] or 0 for x in sav), 2) if sav and any(x["value_usd"] for x in sav) else None}


# ----------------------------------------------------------------------------- the video cards on the Dashboard
STAGE_DOTS = ["script", "shootplan", "clips", "beatmap", "storyboard", "graphicsplan", "build", "graphicsreview", "selfreview", "review", "final"]
STAGE_LABEL = {"script": "Script", "shootplan": "Shoot plan", "clips": "Clips", "beatmap": "Beat map", "storyboard": "Storyboard",
               "graphicsplan": "Graphics plan", "build": "Build", "graphicsreview": "Graphics review", "selfreview": "Self-review", "review": "Your review", "final": "Final"}


def thumb_path(work: str, name: str) -> Path | None:
    """The video's own thumbnail if the project folder has one, else its first storyboard frame."""
    try:
        import shootplan
        folder, _ = shootplan.footage_folder(work, name)
    except Exception:
        folder = None
    if folder:
        for pat in ("thumbnail*.png", "thumbnail*.jpg", "thumbnail*.jpeg", "thumbnail*.webp", "*thumbnail*.png", "*thumbnail*.jpg"):
            hit = sorted(Path(folder).glob(pat))
            if hit:
                return hit[0]
    sb = WORK / work / "storyboard"
    if sb.is_dir():
        imgs = sorted(p for p in sb.iterdir() if p.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp"))
        if imgs:
            return imgs[0]
    return None


def cards() -> dict:
    m = week_summary()
    out = []
    for w in workflow.list_videos():
        for n in w["names"]:
            try:
                st = workflow.state(w["work"], n)
            except Exception as e:                                  # one broken video must not blank the dashboard
                out.append({"work": w["work"], "name": n, "title": n, "error": str(e), "dots": [], "next": None, "warnings": 0, "share": 0})
                continue
            by = {r["id"]: r for r in st["stages"]}
            dots = [{"id": i, "label": STAGE_LABEL[i], "status": (by.get(i) or {}).get("status", "missing")} for i in STAGE_DOTS]
            title = (read_json(WORK / w["work"] / f"{n}.workflow.json", {}) or {}).get("title") or n
            current = next((d["id"] for d in dots if d["status"] != "done"), "final")
            out.append({"work": w["work"], "name": n, "title": title, "dots": dots, "current": current, "next": st["next"],
                        "warnings": sum(len(r["warnings"]) for r in st["stages"]), "has_thumb": thumb_path(w["work"], n) is not None,
                        "share": m["videos"].get(w["work"], {}).get("share", 0.0)})
    return {"videos": out, "week": m}


if __name__ == "__main__":
    print(json.dumps(week_summary(), indent=1)[:2500])
