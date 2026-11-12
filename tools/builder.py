"""The Build board's engine (stage 5): build the video section by section, never more than 3 at a time.

A section is built in its own sandbox folder  _editor\\work\\<work>\\sections\\<name>\\<S01>\\ :
    inputs\\        read-only copies the run needs (the section's beat rows, word timings, style notes)
    section.edit.json   the mechanical cut list (tools\\sections.py baseline_edit), rendered at half size by sectionrender.py
    graphics\\      graphics designed for this section (HyperFrames), out\\ the preview, report.md, run.log (live progress)
Two kinds of run, chosen per section by the build plan:
    local   the section has only takes, punch-ins, B-roll and finished graphics: sectionrender.py, no tokens spent
    agent   the section has a graphic that must be designed: ONE headless Claude run (`claude -p`, flags verified on this
            machine 2026-10-21) inside the sandbox. Claude only ever designs; cutting and rendering stay deterministic.
Safety (a Bash permission cannot be confined to a folder, so these are checks, not walls):
    * `--restricted`: file tools can only touch the sandbox; Bash is limited to named commands (render tool, HyperFrames, ffmpeg)
    * before/after fingerprint of everything shared (plan files, tools, models, graphics, the footage folder, the skill);
      anything that changed is shown on the board as "changed outside its folder"
    * a soft budget per run (checked between turns), live progress from the stream, Cancel kills the whole process tree
Status lives in <name>.sections.status.json; the board shows it (review_app/static/build.js). Python stdlib.
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

HERE = Path(os.path.abspath(__file__)).parent
EDITOR = HERE.parent
import config
import skillrules
WORK = config.WORK
SKILLS_DIR = skillrules.SKILLS
SKILL_FAMILY = ("woots-channel", "youtube-script", "youtube-edit", "youtube-graphics", "youtube-publish", "woots-app")   # split from one skill on 2026-10-23
# what a graphic-building run is given to read (inputs/style/): (skill, file)
STYLE_FILES = (("youtube-graphics", "motion-style-reference.md"), ("youtube-graphics", "hyperframes.md"), ("youtube-graphics", "style-guide.md"),
               ("youtube-graphics", "overlays.md"), ("woots-channel", "house-style.md"), ("woots-channel", "brand.md"))
PYV = config.PYTHON
HF = "hyperframes@0.8.172"
GLOBAL_MAX = 3                                   # The creator's rule: never more than 3 sub-agents at a time
sys.path.insert(0, str(HERE))
import sections as plan_mod  # noqa: E402
import workflow  # noqa: E402

_lock = threading.RLock()
_queue: list[tuple] = []                         # (work, name, sid) waiting for a slot
_running: dict[tuple, dict] = {}                 # (work, name, sid) -> {"proc": Popen | None, "cancel": bool}


# ----------------------------------------------------------------------------- small helpers
def _replace(tmp, p):
    """os.replace that survives a reader holding the destination open (Windows: 'Access is denied' while the board polls)."""
    for i in range(8):
        try:
            os.replace(tmp, p)
            return
        except PermissionError:
            if i == 7:
                raise
            time.sleep(0.05 * (i + 1))


def read_json(p: Path, default=None):
    if not p.exists():
        return default
    return json.loads(p.read_text(encoding="utf-8-sig"))


import channel  # noqa: E402  (the channel profile: names in the prompts)
import projectstore  # noqa: E402  (plan-file writes are recorded: ADR 0005)


def write_json(p: Path, data):
    projectstore.write_json(p, data)


def posix(p) -> str:
    return str(p).replace("\\", "/")


def find_claude() -> str:
    exe = shutil.which("claude")
    if exe:
        return exe
    for c in (Path.home() / ".local" / "bin" / "claude.exe", Path.home() / ".local" / "bin" / "claude"):
        if c.exists():
            return str(c)
    raise RuntimeError("the claude command was not found")


def tool_env() -> dict:
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1")
    import platformx
    for p in platformx.ffmpeg_dirs()[:1]:
        env["PATH"] = str(p) + os.pathsep + env.get("PATH", "")
    return env


def status_path(work: str, name: str) -> Path:
    return WORK / work / f"{name}.sections.status.json"


def sandbox_dir(work: str, name: str, sid: str) -> Path:
    if not re.fullmatch(r"S\d{2,3}", sid):
        raise ValueError(f"bad section id {sid!r}")
    return WORK / work / "sections" / name / sid


def settings_of(work: str, name: str) -> dict:
    return workflow.effective(workflow.load(work, name)["settings"])


# ----------------------------------------------------------------------------- status
def load_status(work: str, name: str) -> dict:
    with _lock:                                    # never read while a writer is swapping the file in
        return read_json(status_path(work, name), {"sections": []}) or {"sections": []}


def update(work: str, name: str, sid: str, **fields):
    """Read-modify-write one section's status record (under the lock; the scheduler threads call this)."""
    with _lock:
        st = load_status(work, name)
        rec = next((s for s in st["sections"] if s["id"] == sid), None)
        if rec is None:
            rec = {"id": sid}
            st["sections"].append(rec)
        rec.update(fields)
        st["updated"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        write_json(status_path(work, name), st)
        return rec


def recover():
    """After a server restart no run is alive: mark what was queued/running as interrupted."""
    with _lock:
        if not WORK.exists():
            return
        for p in WORK.glob("*/*.sections.status.json"):
            try:
                st = read_json(p, {})
            except json.JSONDecodeError:
                continue
            changed = False
            for s in st.get("sections", []):
                if s.get("status") in ("running", "queued"):
                    s["status"], s["error"], changed = "interrupted", "the app was closed while this was running", True
            if changed:
                write_json(p, st)


# ----------------------------------------------------------------------------- protected-files audit
def protected_roots(work: str, name: str) -> list[Path]:
    cfg = read_json(WORK / work / f"{name}.footage.json", {}) or {}
    roots = [EDITOR / "tools", EDITOR / "models", EDITOR / "graphics"] + [SKILLS_DIR / s for s in SKILL_FAMILY] + [skillrules.STARTER / s for s in SKILL_FAMILY]
    if cfg.get("folder"):
        roots.append(Path(cfg["folder"]))
    return [r for r in roots if r.exists()]


APP_FILES = (".sections.status.json", ".workflow.json", ".storyboard.marks.json", ".buildplan.json", ".graphics.built.json",
             ".preview-half.mp4", ".stitch.json", ".tmp")


def snapshot_protected(work: str, name: str, limit: int = 8000) -> dict:
    """{path: (size, mtime_ns)} of everything a section run must not touch. Sibling sections' sandboxes are left out
    on purpose: other runs write there legitimately while this one works."""
    snap, n = {}, 0
    for root in protected_roots(work, name):
        depth0 = len(root.parts)
        for dirpath, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs if d not in ("__pycache__", "node_modules", ".git", ".hyperframes")]
            if len(Path(dirpath).parts) - depth0 >= 4:
                dirs[:] = []
            for f in files:
                p = Path(dirpath) / f
                try:
                    st = p.stat()
                except OSError:
                    continue
                snap[str(p)] = (st.st_size, st.st_mtime_ns)
                n += 1
                if n >= limit:
                    return snap
    wd = WORK / work
    for p in wd.iterdir():                                       # the video's own plan files (top level only)
        if p.is_file() and not p.name.endswith(APP_FILES):
            st = p.stat()
            snap[str(p)] = (st.st_size, st.st_mtime_ns)
    return snap


def diff_snapshots(a: dict, b: dict) -> list[str]:
    out = [f"added: {p}" for p in b if p not in a] + [f"removed: {p}" for p in a if p not in b]
    out += [f"changed: {p}" for p in a if p in b and a[p] != b[p]]
    return sorted(out)


# ----------------------------------------------------------------------------- sandbox + brief
def md_section(text: str, start: str, level_end: str) -> str:
    """The part of a markdown file from the heading `start` to the next heading of the same or higher level."""
    i = text.find(start)
    if i < 0:
        return ""
    m = re.search(level_end, text[i + len(start):])
    return text[i: i + len(start) + (m.start() if m else len(text))]


def prepare(work: str, name: str, psec: dict, bm: dict, cfg: dict) -> Path:
    sb = sandbox_dir(work, name, psec["id"])
    for d in ("inputs/style", "out", "graphics"):
        (sb / d).mkdir(parents=True, exist_ok=True)
    for stale in ("out/preview-half.mp4", "out/render.json", "out/built.json", "report.md"):
        (sb / stale).unlink(missing_ok=True)                    # a failed run must never look finished
    beats = [b for b in bm["beats"] if b["id"] in psec["beats"]]
    write_json(sb / "inputs" / "beats.json", beats)
    words = {}
    for b in beats:
        a = b.get("aroll")
        if b.get("vo"):                                              # times in words.json are seconds inside the voice-over file
            words[b["id"]] = [w for w in b["vo"].get("words", []) if b["vo"]["start"] - 0.05 <= w[1] <= b["vo"]["end"] + 0.05]
            continue
        an = (cfg.get("analysis") or {}).get(a["rel"]) if a else None
        if an:
            rngs = a.get("keep") or [[a["in"], a["out"]]]
            words[b["id"]] = [w for w in an.get("list", []) if any(x - 0.05 <= w[1] <= y + 0.05 for x, y in rngs)]
    write_json(sb / "inputs" / "words.json", words)
    style = sb / "inputs" / "style"
    got = []
    for skill, f in STYLE_FILES:                                 # the graphics skill's files plus the house style and brand (not the long journal)
        src = skillrules.find(f"{skill}/{f}")
        if src:
            shutil.copy2(src, style / f)
            got.append(f)
    if not got:
        (style / "README.md").write_text("(the style files were not found in the skills folder)", encoding="utf-8")
    edit = plan_mod.baseline_edit(beats, cfg.get("folder") or ".", plan_mod.load_built(work, name))
    write_json(sb / "section.edit.json", edit)
    vn = WORK / work / f"{name}.video-notes.md"
    if vn.exists():
        shutil.copy2(vn, sb / "inputs" / "video-notes.md")                 # the facts of this video (gear teeth, ratios, measurements) for the critic
    return sb


PLACES = {"full": "full screen, edge to edge", "left35": "a column down the left side of the frame, 35% of the width, full height",
          "right35": "a column down the right side of the frame, 35% of the width, full height",
          "bl33": "the bottom-left corner of the frame, 33% of the frame width"}


def brief(work: str, name: str, psec: dict, beats: list, st: dict, sb: Path, built: dict) -> str:
    todo = []
    asked = psec.get("asked") or []
    forced = {n["beat"] for n in asked if n.get("beat")}                  # a graphic the creator asked to change is redone even though it is built
    for b in beats:
        g = plan_mod.live_graphic(b)
        if g and (not plan_mod.graphic_built(g, b["id"], built) or b["id"] in forced):
            todo.append(f"  - beat {b['id']} ({g.get('kind')}): idea “{g.get('idea', '')}”; on the words “{g.get('words', '')}”; "
                        f"on-screen text “{g.get('text', '')}”; about {g.get('dur', 3)} s; why: {g.get('why', '')}"
                        + (f"; a draft still of it is at {posix(g['draft'])}" if g.get("draft") else "")
                        + (f"; the host chose the look “{g['style']}” (see inputs/style/style-guide.md and motion-style-reference.md)" if g.get("style") else "")
                        + (f"; the host's design note: “{g['plan_note']}”" if g.get("plan_note") else "")
                        + (f"; THIS IS A VOICE-OVER BEAT: the sound is {b['vo']['file']} from {b['vo']['start']} s to {b['vo']['end']} s, so the graphic runs the whole {b['vo']['end'] - b['vo']['start']:.1f} s and its local time 0 is {b['vo']['start']} s in that file; the timed words in words.json are seconds in that file; animate each part as its word is said" if b.get("vo") else "")
                        + (f"; PLACEMENT (the host asked for it): {PLACES.get(g['place'])}" if PLACES.get(g.get("place")) else "")
                        + (f"; AFTER SEEING THE LAST VERSION the host asked for this change, which you must apply: “{g['review_note']}”" if g.get("review_note") else ""))
    read_s = f"{st['read_s_per_word']} s per word + {st['read_pad_s']} s"
    ask_text = ""
    if asked:
        lines = [f"  - {('at ' + format(n['t'], '.1f') + ' s into this section, ') if n.get('t') is not None else ''}{('beat ' + n['beat'] + ': ') if n.get('beat') else ''}“{n['text']}”" for n in asked]
        ask_text = ("\nTHE HOST WATCHED THE LAST BUILD OF THIS SECTION AND ASKED FOR THESE CHANGES. Apply every one that is about a graphic (the earlier version of each graphic is in graphics/<beat>/index.html: change it rather than starting over, "
                    "unless the note asks for something new). If a change is NOT about a graphic (the cut, the clip, the timing of the footage), do not try: say so in report.md.\n" + "\n".join(lines) + "\n")
    return f"""You are building ONE section of the video "{name}" for the channel. You are one of at most 3 background runs; stay inside your own folder.

Your working folder is the current directory ({posix(sb)}). You can write ONLY here. Do not try to read or write anywhere else.
Section {psec['id']} "{psec['title']}": beats {', '.join(psec['beats'])} ({psec['dur']:.0f} s of talking).

READ FIRST (all in this folder):
- inputs/beats.json: the plan for these beats (the words said, the take, what is on screen, the graphic, why). Build what it asks and change nothing in it: it is an input, not yours to edit.
- inputs/words.json: word timings in SOURCE seconds for each beat's take, to time a graphic to the exact words.
- inputs/style/*.md: the host's style rules and notes: brand tokens, how graphics move, how HyperFrames compositions are written, what the host likes and dislikes.
- section.edit.json: the cut list, already built. Finished graphics are already overlays in it.

YOUR JOB: design and render these graphics (nothing else needs Claude; cutting and rendering are done by tools):
{chr(10).join(todo) or '  (none)'}
{ask_text}
For each graphic on beat B:
 1. Write graphics/B/index.html: a HyperFrames composition, 1920x1080, 30 fps, TRANSPARENT background (a graphic that sits over the host's footage must leave the host's face visible: keep it in the lower third or a side, as the beat's note says, or in the PLACEMENT the host asked for. EXCEPTION: a title card, an end card (kind title or end) and anything whose PLACEMENT is "full screen" cover the whole frame on purpose: give those an OPAQUE background in the brand's main colour (see inputs/style) over the full 1920x1080, not a transparent one, and do not put a band across the lower third). Follow inputs/style closely; keep it simple, few elements, brand tokens only.
 2. Time it to the words. The take starts at source time aroll.in (see beats.json); the first timed word starts at the time given in words.json. The overlay `at` in section.edit.json is seconds into the BEAT: (first word start - aroll.in) minus the graphic's own lead-in before its key moment.
 3. Render it once, transparent: npx --yes {HF} render graphics/B -o graphics/B/B.mov --format mov --quality draft --fps 30 --quiet
    (replace B with the beat id; HyperFrames cannot render smaller than 1080p: the preview tool shrinks it, and the final render reuses this file)
 4. LOOK at it before you trust it: npx --yes {HF} snapshot graphics/B --at 0.5,1.5,2.5 -o graphics/B/snaps  then open the PNGs with the Read tool. Check: nothing overlaps, text is readable for at least {read_s} (the reading budget), nothing is on screen less than {st['min_visible_s']} s, the animation plays ONCE, nothing sits over a face.
 5. Add to "overlays" in section.edit.json: {{"seg": "B", "file": "<absolute path of the .mov, forward slashes>", "at": <seconds into the beat>, "dur": <seconds>}}
Then render the section at half size:  {posix(PYV)} {posix(HERE)}/sectionrender.py section.edit.json
It writes out/preview-half.mp4 and out/render.json. If it fails, read the message and fix the cause.
Then write out/built.json = {{"B": {{"file": "<absolute .mov path>", "at": <seconds into the beat>}}}} for every graphic you rendered, and report.md (under 200 words): what you built, anything you are unsure about, anything that did not fit.

HOW YOU WORK: create and change every file with the Write or Edit tool (Write makes the folders itself). Bash is allowed ONLY for the commands in steps 3, 4 and the section render above, plus ffprobe: run each one as a single command, never chained with && or ; and never with cd, mkdir, cat, echo or python -c (they are refused, and a refused command wastes a turn). If a command is refused, do not give up: use the Write tool instead, or the allowed command exactly as written above. The overlay cannot outlast its beat (the section render cuts it at the end of the beat): if a graphic is longer than its beat, make it end with the beat and say so in report.md.
RULES: write only inside this folder. Never render at full quality. Do not add a graphic that is not in inputs/beats.json. Do not edit inputs/. No lower-thirds or name titles. If a graphic cannot work (e.g. it must cover the face), do NOT force it: say so in report.md and leave it out.
"""


def agent_command(st: dict, role: str = "builder") -> list[str]:
    """The argument list for a graphics run (the prompt goes in on standard input: clauderun.start)."""
    import clauderun
    if role == "critic":                                                 # looks and writes a report: no editing of graphics, no rendering
        allow = ["Read", "Write", f"Bash(npx --yes {HF} snapshot *)", "Bash(ffprobe *)"]
        return clauderun.command(find_claude(), "Read,Write,Bash", allow, st["critic_budget_usd"], ["--model", st["critic_model"], "--effort", st["critic_effort"]])
    allow = ["Read", "Write", "Edit",                                    # npx: only the two HyperFrames commands the brief uses; ffprobe reads a clip's length
             f"Bash({posix(PYV)} {posix(HERE)}/sectionrender.py *)",
             f"Bash(npx --yes {HF} render *)", f"Bash(npx --yes {HF} snapshot *)", "Bash(ffprobe *)"]
    return clauderun.command(find_claude(), "Read,Write,Edit,Bash", allow, st["build_budget_usd"], ["--model", st["build_model"], "--effort", st["build_effort"]])


FAKE_AGENT = r"""
import json, os, subprocess, sys, time
sb, secs, evil = sys.argv[1], float(sys.argv[2]), sys.argv[3]
print(json.dumps({"type": "system", "subtype": "init"}), flush=True)
print(json.dumps({"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Write", "input": {"file_path": sb + "/graphics/x/index.html"}}]}}), flush=True)
time.sleep(secs)
if evil:
    print(json.dumps({"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Bash", "input": {"command": "python -c open(" + evil + ")"}}]}}), flush=True)
    open(evil, "w").write("not allowed")
r = subprocess.run([sys.argv[4], sys.argv[5], sb + "/section.edit.json"], capture_output=True, text=True)
print(json.dumps({"type": "result", "subtype": "success", "is_error": False, "total_cost_usd": 0.0123, "num_turns": 4, "duration_ms": int(secs * 1000),
                  "session_id": "fake-session", "terminal_reason": "completed", "permission_denials": [], "result": "fake run"}), flush=True)
"""


def short(tool: str, inp: dict, sb: Path) -> str:
    if tool == "Bash":
        return "Bash: " + (inp.get("command") or "")[:110]
    fp = inp.get("file_path") or inp.get("path") or ""
    try:
        fp = str(Path(fp).relative_to(sb))
    except ValueError:
        pass
    return f"{tool} {fp}"[:120]


# ----------------------------------------------------------------------------- one run
def _kill(proc):
    import platformx
    platformx.kill_tree(proc)


def run_local(work, name, sid, sb, key):
    proc = subprocess.Popen([str(PYV), str(HERE / "sectionrender.py"), str(sb / "section.edit.json")], cwd=sb, env=tool_env(),
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, text=True, encoding="utf-8", errors="replace")
    _running[key]["proc"] = proc
    tail = []
    for line in proc.stdout:
        tail = (tail + [line.strip()])[-12:]
        update(work, name, sid, progress=tail[-8:])
    rc = proc.wait()
    return {"ok": rc == 0, "error": None if rc == 0 else "; ".join(tail[-2:])[:300]}


def run_agent(work, name, sid, sb, key, st, prompt, role="builder", tag=""):
    fake = os.environ.get("WOOT_BUILD_FAKE")
    if fake:
        cmd = [sys.executable, "-c", FAKE_AGENT, str(sb), os.environ.get("WOOT_BUILD_FAKE_SECS", "2"),
               os.environ.get("WOOT_BUILD_FAKE_EVIL", ""), str(PYV), str(HERE / "sectionrender.py")]
    else:
        cmd = agent_command(st, role)
    (sb / f"BRIEF{tag}.md").write_text(channel.prompt(prompt), encoding="utf-8")
    if fake:
        proc = subprocess.Popen(cmd, cwd=sb, env=tool_env(), stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL, text=True, encoding="utf-8", errors="replace")
    else:
        import clauderun
        proc = clauderun.start(cmd, prompt, sb, tool_env())
    _running[key]["proc"] = proc
    err_chunks = []
    threading.Thread(target=lambda: err_chunks.append(proc.stderr.read()), daemon=True).start()
    result, progress, log, commands = None, [], (sb / f"run{tag}.log").open("w", encoding="utf-8"), []
    last = 0.0
    for line in proc.stdout:
        log.write(line)
        try:
            e = json.loads(line)
        except json.JSONDecodeError:
            continue
        if e.get("type") == "assistant":
            for c in e["message"]["content"]:
                if c.get("type") == "tool_use":
                    commands.append(json.dumps(c.get("input", {}), ensure_ascii=False))
                    progress.append(short(c["name"], c.get("input", {}), sb))
                elif c.get("type") == "text" and c.get("text", "").strip():
                    progress.append("says: " + c["text"].strip()[:100])
        elif e.get("type") == "rate_limit_event":                  # every run reports the plan's real limits: keep them for the Dashboard, free
            try:
                import usage
                usage.save_rate_limit(e.get("rate_limit_info") or {})
            except Exception:
                pass
        elif e.get("type") == "result":
            result = e
        if time.time() - last > 1.0:
            update(work, name, sid, progress=progress[-8:], steps=len(progress))
            last = time.time()
    rc = proc.wait()
    log.close()
    update(work, name, sid, progress=progress[-8:], steps=len(progress))
    out = {"ok": rc == 0 and bool(result) and not result.get("is_error"), "result": result, "error": None, "commands": commands}
    if not out["ok"]:
        out["error"] = (result or {}).get("subtype") or (err_chunks[0].strip()[-300:] if err_chunks and err_chunks[0] else f"exit {rc}")
    return out


CRITIC_KINDS = ("explainer", "ui", "3d")


def critic_brief(name: str, psec: dict, beats: list, targets: list, sb: Path, st: dict) -> str:
    lines = []
    for b in targets:
        g = plan_mod.live_graphic(b)
        lines.append(f"  - beat {b['id']} ({g.get('kind')}): idea “{g.get('idea', '')}”; timed to the words “{g.get('words', '')}”; on-screen text “{g.get('text', '')}”; "
                     f"{g.get('dur', 3)} s; placement {PLACES.get(g.get('place')) or 'automatic (leave the face clear)'}"
                     + (f"; the host's design note: “{g['plan_note']}”" if g.get("plan_note") else "")
                     + (f"; the host asked for this change last time: “{g['review_note']}”" if g.get("review_note") else "")
                     + (f"; VOICE-OVER BEAT, sound is {b['vo']['file']}" if b.get("vo") else ""))
    read_s = f"{st['read_s_per_word']} s per word + {st['read_pad_s']} s"
    return f"""You are the motion-design CRITIC for ONE section of the video "{name}" (the channel). Another Claude built the graphics below. Your job: look at each one the way a viewer will and decide whether it is good enough to show the host. If not, say exactly what to change. You do NOT edit graphics and you do not render.

Your working folder is the current directory ({posix(sb)}); write only here.
READ FIRST: inputs/beats.json (the plan), inputs/words.json (word timings), inputs/style/*.md (brand tokens and how graphics should move), inputs/video-notes.md (the facts of this video: use it to check every number and label), section.edit.json (where each graphic lands).

GRAPHICS TO REVIEW:
{chr(10).join(lines)}

For each graphic:
 1. Look at it: npx --yes {HF} snapshot graphics/<beat> --at 0.4,1.5,3,5,7,9,11 -o graphics/<beat>/critic-snaps   (use times inside its length), then open the PNGs with the Read tool. Also read graphics/<beat>/index.html to see the timing (CONFIG beats) and compare it with inputs/words.json.
 2. Judge it on: (a) nothing overlaps, is cut off or is too small to read; text stays up for its reading budget ({read_s}); (b) it is where the host asked (placement) and nothing sits over the host's face; a full-screen graphic is opaque over the whole frame; (c) it is timed to the words: each part appears as its word is said; (d) the idea reads: what is the viewer supposed to understand, and does the picture teach it? Check every label and number against inputs/video-notes.md: a wrong tooth count, ratio or measurement is a "fix"; (e) the motion: one clear idea, eased, plays once, not busy; brand tokens only; (f) polish: depth, spacing, alignment, hierarchy; does it look designed or merely correct?
 3. Be a tough, fair critic. "fix" = the host would notice and dislike it, or it teaches something wrong or is off the placement the host asked for. "look" = a matter of taste. At most 5 issues per graphic, the most important first. Each issue needs a CONCRETE change the builder can make to index.html (for example "move the swing arm label 40 px right so it clears the gear" or "start the yaw arrow at the word 'yaw', now it starts 1.2 s early").

Write critique.json exactly like this (and nothing else is read): {{"<beat>": {{"verdict": "ok" or "fix", "issues": [{{"severity": "fix" or "look", "what": "...", "fix": "..."}}]}}}} and critique.md (under 150 words: what is good, what you want changed). Verdict "ok" when it has no "fix" issues.
RULES: write only critique.json, critique.md and the snapshots; never edit inputs/ or graphics/<beat>/index.html.
"""


def critic_pass(work, name, sid, sb, key, st, psec, beats, cfg):
    """After the builder finished: an Opus critic looks at the built motion explainers; if it finds "fix" issues the builder runs ONCE more with exactly those fixes.
    Returns None when nothing was reviewed, else {"summary": {...}, "cost": extra USD}."""
    if st.get("critic_model", "off") == "off" or os.environ.get("WOOT_BUILD_FAKE"):
        return None
    built = plan_mod.load_built(work, name)
    targets = []
    for b in beats:
        g = plan_mod.live_graphic(b)
        e = built.get(b["id"])
        if g and g.get("kind") in CRITIC_KINDS and e and Path(str(e.get("file", ""))).exists() and plan_mod.graphic_built(g, b["id"], built):
            targets.append(b)
    if not targets:
        return None
    (sb / "critique.json").unlink(missing_ok=True)
    update(work, name, sid, progress=[f"the {st['critic_model']} critic is looking at {', '.join(b['id'] for b in targets)}…"])
    cr = run_agent(work, name, sid, sb, key, st, critic_brief(name, psec, targets, targets, sb, st), role="critic", tag=".critic")
    cost = ((cr.get("result") or {}).get("total_cost_usd")) or 0.0
    summary = {"model": st["critic_model"], "effort": st["critic_effort"], "cost_usd": round(cost, 4), "verdicts": {}, "fixed": False, "ok": cr["ok"], "error": cr.get("error")}
    cj = read_json(sb / "critique.json", {}) or {}
    asked, fixes = [], 0
    for b in targets:
        v = cj.get(b["id"]) or {}
        issues = [i for i in (v.get("issues") or []) if isinstance(i, dict)]
        summary["verdicts"][b["id"]] = {"verdict": v.get("verdict", "?"), "issues": issues[:6]}
        for i in issues:
            if i.get("severity") == "fix":
                fixes += 1
                asked.append({"beat": b["id"], "t": None, "text": f"CRITIC (apply this): {i.get('what', '')} -> {i.get('fix', '')}"})
    if asked and not _running[key]["cancel"]:
        update(work, name, sid, progress=[f"the builder is applying {fixes} fix(es) from the critic…"])
        psec2 = {**psec, "asked": (psec.get("asked") or []) + asked}
        (sb / "out" / "built.json").unlink(missing_ok=True)
        bres = run_agent(work, name, sid, sb, key, st, brief(work, name, psec2, beats, st, sb, plan_mod.load_built(work, name)), tag=".fix")
        bcost = ((bres.get("result") or {}).get("total_cost_usd")) or 0.0
        cost += bcost
        summary["fix_cost_usd"] = round(bcost, 4)
        if bres["ok"]:
            merge_built(work, name, sb, beats)
            summary["fixed"] = True
        else:
            summary["error"] = bres.get("error")
    return {"summary": summary, "cost": cost}


def classify_changes(diff: list[str], commands: list[str]) -> dict:
    """Split what changed outside the sandbox while a run was going:
    suspicious = the run's own commands/paths mention the file (it probably did it): a RED warning;
    other      = changed during the run but nothing the run did mentions it (most likely the host's or Claude Code's own edits)."""
    blob = " ".join(commands).lower().replace("\\\\", "/").replace("\\", "/")
    sus, other = [], []
    for d in diff:
        path = d.split(": ", 1)[-1].lower().replace("\\", "/")
        (sus if path in blob or path.rsplit("/", 1)[-1] in blob else other).append(d)
    return {"ok": not sus, "suspicious": sus[:20], "other": other[:20], "changed": (sus + other)[:20]}


def merge_built(work: str, name: str, sb: Path, beats: list):
    """Claude's out/built.json -> <name>.graphics.built.json, only for files inside the sandbox that exist."""
    bj = read_json(sb / "out" / "built.json", {}) or {}
    if not bj:
        return []
    done = []
    with _lock:                                    # read-modify-write: two sections can finish at the same moment
        built = plan_mod.load_built(work, name)
        for b in beats:
            e = bj.get(b["id"])
            g = plan_mod.live_graphic(b)
            if not e or not g:
                continue
            f = Path(str(e.get("file", "")))
            try:
                ok = f.exists() and config.inside(sb, f)
            except OSError:
                ok = False
            if ok:
                built[b["id"]] = {"file": str(f), "sig": plan_mod.gsig(g), "at": float(e.get("at", 0.0)), "built": time.strftime("%Y-%m-%dT%H:%M:%S")}
                done.append(b["id"])
        write_json(plan_mod.built_path(work, name), built)
    return done


def run_task(work, name, sid):
    key = (work, name, sid)
    t0 = time.time()
    try:                                                                # the app may have started before the cut-list code changed: use the current one
        import importlib
        importlib.reload(plan_mod)
    except Exception:                                                   # noqa: BLE001 - a failed reload keeps the loaded version
        pass
    rec = {"status": "running", "started": time.strftime("%Y-%m-%dT%H:%M:%S"), "error": None, "progress": [], "audit": None,
           "cost_usd": None, "finished": None}
    try:
        bm = read_json(WORK / work / f"{name}.beatmap.json")
        import gfxplan
        gfxplan.apply(work, name, bm)                                  # the same look, notes and cuts the plan was made with
        cfg = read_json(WORK / work / f"{name}.footage.json", {}) or {}
        plan = plan_mod.plan(work, name, write=False)                  # fresh numbers (built graphics change), no file race
        psec = next(s for s in plan["sections"] if s["id"] == sid)
        st = settings_of(work, name)
        mode = "agent" if psec["needs_agent"] else "local"
        update(work, name, sid, **rec, mode=mode, sig=psec["sig"], title=psec["title"])
        before = snapshot_protected(work, name)
        sb = prepare(work, name, psec, bm, cfg)
        beats = [b for b in bm["beats"] if b["id"] in psec["beats"]]
        if mode == "agent":
            res = run_agent(work, name, sid, sb, key, st, brief(work, name, psec, beats, st, sb, plan_mod.load_built(work, name)))
        else:
            res = run_local(work, name, sid, sb, key)
        if _running[key]["cancel"]:
            update(work, name, sid, status="cancelled", finished=time.strftime("%Y-%m-%dT%H:%M:%S"), error=None)
            return
        fields = {"audit": classify_changes(diff_snapshots(before, snapshot_protected(work, name)), res.get("commands", []))}
        r = res.get("result") or {}
        if r:
            fields.update(cost_usd=r.get("total_cost_usd"), turns=r.get("num_turns"), session_id=r.get("session_id"),
                          usage=r.get("usage"), duration_ms=r.get("duration_ms"),
                          denials=[{"tool": d.get("tool_name"), "input": json.dumps(d.get("tool_input", {}))[:160]} for d in r.get("permission_denials", [])],
                          model=st["build_model"], run_result=(r.get("subtype"), r.get("terminal_reason")))
        ok = res["ok"]
        if mode == "agent" and ok:
            built_ids = merge_built(work, name, sb, beats)
            fields["built"] = built_ids
            crit = critic_pass(work, name, sid, sb, key, st, psec, beats, cfg)          # a stronger Claude looks at the explainers; the builder fixes what it finds, once
            if crit:
                fields["critic"] = crit["summary"]
                fields["critic_cost_usd"] = round(crit["cost"], 4)
                fields["cost_usd"] = round((fields.get("cost_usd") or 0) + crit["cost"], 4)
            lt = plan_mod.live_graphic
            wanted = [b["id"] for b in beats if lt(b) and not plan_mod.graphic_built(lt(b), b["id"], plan_mod.load_built(work, name))]
            if wanted:                                                  # Claude left some out: say so, don't fail the whole section
                fields["left_out"] = wanted
            edit = plan_mod.baseline_edit(beats, cfg.get("folder") or ".", plan_mod.load_built(work, name))
            write_json(sb / "section.edit.json", edit)                  # re-render deterministically from what is really built
            sr = subprocess.run([str(PYV), str(HERE / "sectionrender.py"), str(sb / "section.edit.json")], cwd=sb, env=tool_env(),
                                capture_output=True, text=True, encoding="utf-8", errors="replace", stdin=subprocess.DEVNULL)
            if sr.returncode != 0:
                ok, res["error"] = False, "final render failed: " + (sr.stdout + sr.stderr).strip()[-250:]
        rj = read_json(sb / "out" / "render.json", {}) or {}
        if ok and not (sb / "out" / "preview-half.mp4").exists():
            ok, res["error"] = False, "no preview was produced"
        rp = sb / "report.md"
        fields.update(status="done" if ok else "failed", error=None if ok else res.get("error"), finished=time.strftime("%Y-%m-%dT%H:%M:%S"),
                      elapsed=round(time.time() - t0, 1), preview_dur=rj.get("dur"), notes=rj.get("notes", []),
                      report=rp.read_text(encoding="utf-8")[:2000] if rp.exists() else None, progress=[])
        update(work, name, sid, **fields)
        if ok and mode == "agent":
            mark_notes(work, name, sid, "open", "applied")                 # the section was rebuilt with the creator's notes: he looks again
    except Exception as e:                                              # noqa: BLE001 - show any failure on the board
        update(work, name, sid, status="failed", error=f"{type(e).__name__}: {e}", finished=time.strftime("%Y-%m-%dT%H:%M:%S"),
               elapsed=round(time.time() - t0, 1))
    finally:
        with _lock:
            _running.pop(key, None)
        _pump()


# ----------------------------------------------------------------------------- the creator's change requests on built sections
def _notes_write(work: str, name: str, notes: list):
    write_json(plan_mod.notes_path(work, name), {"notes": notes})


def mark_notes(work: str, name: str, sid: str, old: str, new: str):
    with _lock:
        notes = plan_mod.read_notes(work, name)
        for n in notes:
            if n["sid"] == sid and n.get("kind") == "graphic" and n.get("status") == old:
                n["status"] = new
        _notes_write(work, name, notes)


def add_note(work: str, name: str, sid: str, text: str, kind: str, t=None) -> dict:
    """kind 'graphic' = Claude redesigns the graphics of this section on the next build; 'plan' = a change to the cut, clip or timing: Claude changes the plan in chat."""
    text = (text or "").strip()
    if not text:
        raise ValueError("write what should change")
    if kind not in ("graphic", "plan"):
        raise ValueError("kind must be graphic or plan")
    plan = plan_mod.plan(work, name, write=False)
    ps = next((s for s in plan["sections"] if s["id"] == sid), None)
    if not ps:
        raise ValueError(f"unknown section {sid}")
    beat = None
    if t is not None:
        t = round(float(t), 1)
        rj = read_json(sandbox_dir(work, name, sid) / "out" / "render.json", {}) or {}
        for sg in rj.get("segments", []):
            if sg["out_start"] <= t < sg["out_start"] + sg["out_dur"]:
                beat = str(sg["id"]).split(".")[0]
                break
    with _lock:
        notes = plan_mod.read_notes(work, name)
        nid = max([n["id"] for n in notes], default=0) + 1
        notes.append({"id": nid, "sid": sid, "kind": kind, "text": text, "t": t, "beat": beat, "status": "open", "created": time.strftime("%Y-%m-%dT%H:%M:%S")})
        _notes_write(work, name, notes)
    return state(work, name)


def note_status(work: str, name: str, nid: int, status: str) -> dict:
    if status not in ("open", "applied", "done", "delete"):
        raise ValueError("bad status")
    with _lock:
        notes = plan_mod.read_notes(work, name)
        if status == "delete":
            notes = [n for n in notes if n["id"] != nid]
        else:
            for n in notes:
                if n["id"] == nid:
                    n["status"] = status
        _notes_write(work, name, notes)
    return state(work, name)


# ----------------------------------------------------------------------------- scheduler
def _pump():
    """Start queued sections while slots are free: at most GLOBAL_MAX at once, and at most the video's own setting."""
    with _lock:
        i = 0
        while i < len(_queue) and len(_running) < GLOBAL_MAX:
            work, name, sid = _queue[i]
            limit = min(GLOBAL_MAX, int(settings_of(work, name)["max_parallel"]))
            if sum(1 for k in _running if k[:2] == (work, name)) >= limit:
                i += 1
                continue
            _queue.pop(i)
            _running[(work, name, sid)] = {"proc": None, "cancel": False}
            threading.Thread(target=run_task, args=(work, name, sid), daemon=True).start()


def can_build(work: str, name: str):
    """Building needs a beat map and nothing else."""
    if not (WORK / work / f"{name}.beatmap.json").exists():
        return False, "no beat map yet: build one in the Beat map tab"
    return True, ""


def start(work: str, name: str, ids: list[str] | None = None) -> dict:
    ok, why = can_build(work, name)
    if not ok:
        raise ValueError(why)
    try:                                                    # remember the plan this build starts from: the Beat map tab shows what changed since
        import beatmap
        beatmap.snapshot_for_build(work, name)
        projectstore.mark(WORK / work, name, "build")
    except Exception:                                       # noqa: BLE001 - a snapshot is a convenience
        pass
    plan = plan_mod.plan(work, name)
    st = {s["id"]: s for s in load_status(work, name)["sections"]}
    want = ids or [s["id"] for s in plan["sections"] if not (st.get(s["id"], {}).get("status") == "done" and st[s["id"]].get("sig") == s["sig"])]
    known = {s["id"] for s in plan["sections"]}
    with _lock:
        for sid in want:
            if sid not in known:
                raise ValueError(f"unknown section {sid}")
            key = (work, name, sid)
            if key in _running or key in _queue:
                continue
            update(work, name, sid, status="queued", error=None, title=next(s["title"] for s in plan["sections"] if s["id"] == sid))
            _queue.append(key)
    _pump()
    return state(work, name)


def cancel(work: str, name: str, sid: str) -> dict:
    with _lock:
        key = (work, name, sid)
        if key in _queue:
            _queue.remove(key)
            update(work, name, sid, status="cancelled", error=None)
        elif key in _running:
            _running[key]["cancel"] = True
            _kill(_running[key].get("proc"))
    return state(work, name)


# ----------------------------------------------------------------------------- state for the board
def state(work: str, name: str) -> dict:
    bm_p = WORK / work / f"{name}.beatmap.json"
    out = {"beatmap_ready": bm_p.exists(), "plan": None, "plan_stale": False, "sections": [], "settings": settings_of(work, name),
           "can_build": False, "why_not": "", "running": 0, "queued": 0, "totals": {}, "stitch": None, "max_global": GLOBAL_MAX}
    out["can_build"], out["why_not"] = can_build(work, name)
    if not bm_p.exists():
        return out
    plan = read_json(plan_mod.plan_path(work, name))
    sha = hashlib.sha256(bm_p.read_bytes()).hexdigest()[:16]
    if not plan:
        try:
            plan = plan_mod.plan(work, name)
        except ValueError:
            return out
    out["plan"] = {"generated": plan["generated"], "beatmap_version": plan["beatmap_version"]}
    out["plan_stale"] = plan.get("beatmap_sha") != sha
    stat = {s["id"]: s for s in load_status(work, name)["sections"]}
    cost, done, agent_costs = 0.0, 0, []
    for ps in plan["sections"]:
        s = stat.get(ps["id"], {})
        sb = sandbox_dir(work, name, ps["id"])
        status = s.get("status", "todo")
        outdated = bool(s.get("sig")) and s["sig"] != ps["sig"] and status == "done"
        rep = sb / "report.md"
        rec = {**ps, **{k: v for k, v in s.items() if k not in ("id", "title")}, "status": "outdated" if outdated else status,
               "has_preview": (sb / "out" / "preview-half.mp4").exists() and status == "done",
               "report": rep.read_text(encoding="utf-8")[:2000] if rep.exists() else s.get("report")}
        out["sections"].append(rec)
        cost += s.get("cost_usd") or 0
        done += 1 if rec["status"] == "done" else 0
        if s.get("mode") == "agent" and s.get("cost_usd") and status == "done":
            agent_costs.append(s["cost_usd"])
    with _lock:
        out["running"] = sum(1 for k in _running if k[:2] == (work, name))
        out["queued"] = sum(1 for k in _queue if k[:2] == (work, name))
    todo_agent = sum(1 for s in out["sections"] if s["needs_agent"] and s["status"] in ("todo", "outdated", "failed", "cancelled", "interrupted"))
    avg = sum(agent_costs) / len(agent_costs) if agent_costs else None
    out["totals"] = {"sections": len(plan["sections"]), "done": done, "cost_usd": round(cost, 4), "agent_sections_left": todo_agent,
                     "avg_agent_cost": round(avg, 4) if avg else None, "estimate_usd": round(avg * todo_agent, 2) if avg else None,
                     "dur": round(sum(s["dur"] for s in out["sections"]), 1)}
    out["stitch"] = read_json(WORK / work / f"{name}.stitch.json")
    out["notes"] = plan_mod.read_notes(work, name)
    return out


# ----------------------------------------------------------------------------- stitch
def music_beds(work: str, name: str, secs: list) -> list:
    """Runs of consecutive beats with the same audio.music name, on the stitched timeline. secs = [{"beats": [ids], "dur": the section preview's length}] in order."""
    bm = read_json(WORK / work / f"{name}.beatmap.json") or {"beats": []}
    B = {b["id"]: b for b in bm["beats"]}
    beds, t, cur = [], 0.0, None
    for s in secs:
        t0 = t
        for bid in s["beats"]:
            b = B.get(bid)
            if not b or b.get("skip"):
                continue
            nm = ((b.get("audio") or {}).get("music") or "").strip()
            if nm and cur and cur["name"] == nm and abs(cur["end"] - t) < 0.35:
                cur["end"] = t + b["dur"]
                cur["beats"].append(bid)
            elif nm:
                cur = {"name": nm, "start": t, "end": t + b["dur"], "beats": [bid]}
                beds.append(cur)
            else:
                cur = None
            t += b["dur"]
        t = t0 + float(s.get("dur") or (t - t0))                   # a section's real length wins over the sum of its beats
        if cur and cur["end"] > t:
            cur["end"] = t
    return beds


def _decode_timed(p: Path, cache: Path, exe: str, ff: dict):
    """A preview's sound as 48 kHz stereo, placed by the file's TIMESTAMPS (aresample async), the way a player plays it. Decoding the samples one after the other
    instead let every cut inside a section add its few hundredths of a second of extra sound, so later in a section the sound ran 0.1-0.2 s behind the picture."""
    import soundfile as sf
    st = p.stat()
    key = hashlib.sha1(f"timed|{p}|{st.st_size}|{int(st.st_mtime)}".encode()).hexdigest()[:12]
    wav = cache / f"timed_{key}.wav"
    if not wav.exists():
        r = subprocess.run([exe, "-nostdin", "-y", "-v", "error", "-i", str(p), "-vn", "-af", "aresample=async=1000:first_pts=0", "-ac", "2", "-ar", "48000", "-c:a", "pcm_f32le", str(wav)],
                           capture_output=True, text=True, env=ff)
        if r.returncode != 0:
            raise ValueError(f"could not read the sound of {p.parent.parent.name}: {r.stderr.strip()[-200:]}")
    a, _ = sf.read(str(wav), dtype="float32", always_2d=True)
    return a


def _vinfo(p: Path, ff: dict) -> tuple:
    """(frame count, fps) of a preview's picture."""
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-count_frames", "-show_entries", "stream=nb_read_frames,r_frame_rate", "-of", "json", str(p)],
                       capture_output=True, text=True, env=ff)
    s = json.loads(r.stdout)["streams"][0]
    a, _, b = s["r_frame_rate"].partition("/")
    return int(s["nb_read_frames"]), float(a) / float(b or 1)


def _music_mix(work: str, name: str, st: dict, durs: list, speech, cache: Path) -> tuple:
    """Mix the beat map's music beds under the stitched speech, the way the final render does (finalrender.mix: below the speech by the music_below_speech_db
    setting, ducked while the host talks, crossfaded). Beds are the runs of consecutive beats with the same audio.music name (music_beds), on the stitched timeline."""
    import finalrender as fr
    beds = music_beds(work, name, [{"beats": x["beats"], "dur": d} for x, d in zip(st["sections"], durs)])
    missing, plan_beds = [], []
    for bd in beds:
        f, why = fr.resolve_music(bd["name"])
        if f:
            plan_beds.append({"file": str(f), "start": bd["start"], "end": bd["end"], "name": bd["name"]})
        else:
            missing.append(f"{bd['name']}: {why}")
    if not plan_beds:
        return speech, {"ran": False, "note": "no music beds in the beat map" + (": " + "; ".join(missing) if missing else "")}
    mixed, _ = fr.mix(speech, {"beds": plan_beds, "sfx": []}, settings_of(work, name), cache)
    peak = float(abs(mixed).max() or 1.0)
    if peak > 0.95:
        mixed = mixed * (0.95 / peak)
    return mixed, {"ran": True, "beds": [{"name": b["name"], "start": round(b["start"], 1), "end": round(b["end"], 1)} for b in plan_beds], "missing": missing,
                   "note": f"{len(plan_beds)} music bed(s) mixed in" + (f"; NOT found: {'; '.join(missing)}" if missing else "")}


def stitch(work: str, name: str) -> dict:
    """Join the section previews. The PICTURE is joined by stream copy. The SOUND is rebuilt: each section's sound is cut to exactly the length of its picture (frames / fps)
    before the sections are laid end to end, because a section's sound is a few hundredths of a second longer than its picture, and joining the files as they are let
    that add up (lips drifting more and more across the video). Then -14 LUFS (two passes), then the music beds (setting music_in_preview)."""
    import finalrender as fr
    import numpy as np
    import soundfile as sf
    st = state(work, name)
    bad = [s["id"] for s in st["sections"] if s["status"] != "done" or not s["has_preview"]]
    if bad:
        raise ValueError(f"these sections are not built yet: {', '.join(bad)}")
    ff = tool_env()
    exe = shutil.which("ffmpeg", path=ff["PATH"]) or "ffmpeg"
    prevs = [sandbox_dir(work, name, s["id"]) / "out" / "preview-half.mp4" for s in st["sections"]]
    lst = WORK / work / "sections" / name / "stitch.txt"
    counts = [_vinfo(p, ff) for p in prevs]
    lst.write_text("".join(f"file '{posix(p)}'\nduration {n / fps:.6f}\n" for p, (n, fps) in zip(prevs, counts)), encoding="utf-8")     # exact lengths: each section starts where the last one's frames end
    final = WORK / work / f"{name}.preview-half.{time.strftime('%m%d-%H%M%S')}.mp4"        # a new name each time: a player holding the last one open (Windows) cannot block a stitch
    tmp = final.with_name(final.stem + ".part.mp4")
    vtmp = final.with_name(final.stem + ".video.mp4")
    r = subprocess.run([exe, "-nostdin", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(lst), "-an", "-c", "copy", "-movflags", "+faststart", str(vtmp)],
                       capture_output=True, text=True, env=ff)
    if r.returncode != 0:
        raise ValueError("stitching failed: " + r.stderr.strip()[-300:])
    cache = WORK / work / "sections" / name / "musiccache"
    cache.mkdir(parents=True, exist_ok=True)
    parts, durs = [], []
    for p, (n, fps) in zip(prevs, counts):
        durs.append(n / fps)
        need = int(round(n / fps * fr.SR))
        a = _decode_timed(p, cache, exe, ff)
        a = a[:need] if len(a) >= need else np.concatenate([a, np.zeros((need - len(a), a.shape[1]), a.dtype)])
        parts.append(a)
    speech = np.concatenate(parts)
    raw = cache / "speech-raw.wav"
    sf.write(str(raw), speech, fr.SR, subtype="PCM_16")
    norm = cache / "speech.wav"
    try:                                                              # the whole preview to -14 LUFS (two passes): it should sound like the final will
        p1 = subprocess.run([exe, "-nostdin", "-hide_banner", "-i", str(raw), "-af", "loudnorm=I=-14:TP=-1.5:LRA=11:print_format=json", "-f", "null", "-"],
                            capture_output=True, text=True, env=ff)
        meas = json.loads(re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", p1.stderr, re.S).group(0))
        af = fr.steady_gain(meas)                                    # one gain for the whole preview, never riding the volume
        p2 = subprocess.run([exe, "-nostdin", "-y", "-v", "error", "-i", str(raw), "-af", af, "-ar", str(fr.SR), "-c:a", "pcm_s16le", str(norm)], capture_output=True, text=True, env=ff)
        if p2.returncode != 0:
            raise ValueError(p2.stderr)
    except (ValueError, KeyError, AttributeError, OSError):
        shutil.copyfile(raw, norm)                                    # an un-normalized preview is still a preview
    speech, _ = sf.read(str(norm), dtype="float32", always_2d=True)    # the sound without music: the audition list mixes candidates over it
    need = int(round(sum(durs) * fr.SR))
    speech = speech[:need] if len(speech) >= need else np.concatenate([speech, np.zeros((need - len(speech), speech.shape[1]), speech.dtype)])
    sf.write(str(norm), speech, fr.SR, subtype="PCM_16")
    music = {"ran": False, "note": "music in the preview is off (setting music_in_preview)"}
    mixed = speech
    if settings_of(work, name).get("music_in_preview", True):
        try:
            mixed, music = _music_mix(work, name, st, durs, speech, cache)
        except Exception as e:                                        # noqa: BLE001  (a preview without music is still a preview)
            music = {"ran": False, "note": f"music could not be mixed: {type(e).__name__}: {e}"}
    wav = cache / "preview-mix.wav"
    sf.write(str(wav), mixed, fr.SR, subtype="PCM_16")
    r = subprocess.run([exe, "-nostdin", "-y", "-v", "error", "-i", str(vtmp), "-i", str(wav), "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a", "aac", "-b:a", "160k",
                        "-movflags", "+faststart", str(tmp)], capture_output=True, text=True, env=ff)
    if r.returncode != 0:
        raise ValueError("joining picture and sound failed: " + r.stderr.strip()[-300:])
    vtmp.unlink(missing_ok=True)
    os.replace(tmp, final)
    for old in WORK.joinpath(work).glob(f"{name}.preview-half*.mp4"):          # earlier stitches: removed when nothing holds them open (else the next stitch removes them)
        if old != final:
            try:
                old.unlink()
            except OSError:
                pass
    offs, t = [], 0.0
    for s, d in zip(st["sections"], durs):
        offs.append({"id": s["id"], "title": s["title"], "start": round(t, 3), "dur": round(d, 3), "beats": s["beats"]})
        t += d
    info = {"stitched": time.strftime("%Y-%m-%dT%H:%M:%S"), "file": final.name, "dur": round(t, 3), "sections": offs, "music": music}
    write_json(WORK / work / f"{name}.stitch.json", info)
    projectstore.mark(WORK / work, name, "stitch")
    return state(work, name)


if __name__ == "__main__":
    work, name = sys.argv[1], sys.argv[2]
    print(json.dumps(state(work, name), indent=1)[:4000])
