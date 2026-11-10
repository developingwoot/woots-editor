# Improvement plan: security, models, skills, screens

Draft, 2026-11-10. From a review of the server, the Claude runs, the starter skills, the model choices and the v2 screens (walked in a test server on throwaway data).
It sits next to `quality-plan.md` (footage, rhythm, templates) and does not repeat it.

## How to use this plan
- Each task is small enough for one session. Do them in order inside a phase; phases A and B come first, C and D can be interleaved.
- Every task follows `CLAUDE.md`: Edit tool only, a test for every behaviour change, `python -m pytest` before each commit, no approval gates, plan files through `projectstore`,
  prompts say "the host" and "the channel", no person's name anywhere.
- Check a screen change in a second server on another port with the four `WOOTS_*` variables pointed at a temp folder (`tests/fixtures/make_project.py` builds a demo project). Never on real video folders.
- "Done when" is the acceptance test. If a task turns out to need a decision listed under "Open decisions", stop and ask.

## Decided (2026-11-10)
- **No phone access.** The app listens on this computer only (A1).
- **The older tab screens go**, all of them, now (Phase V). What only they could do is either rebuilt in the v2 screens (D7 to D9) or dropped (the list is in V1).
- **No approval gates anywhere.** The leftovers in code, prompts and docs are removed (V3).
- **The app is for anyone**: a public repository with built releases (Phase R). Nothing in code, prompts or starter skills may assume one channel, one computer or one person.

## Open decisions (the defaults below are used unless the host says otherwise)
1. **Story changes.** Default: Claude's reorder suggestions become one-click notes, applied by the next cut (C3). Alternative: the first cut applies them itself and lists them under "What changed".
2. **A stronger model for story work.** Default: a new "Story" job set to Opus at high effort (B1). It costs more of the plan per cut.
3. **The form of a release.** Default: a zip with a setup script that builds the Python environment on the user's computer (R3). Alternative: a real installer (more work, and the speech packages are about 5 GB either way).
4. **Which systems.** Default: Windows only for the first release, said plainly; the code stops assuming Windows where that is cheap (R7).

---

## Status
- Done 2026-11-10: A1, A2, A3, V1, V2, V3, D4, D7, D8, D9, A4, A5, R1, R2, R3 (files written, not yet tried on a clean machine), R4, R5, C6, R7, R8; R6 partly.
- A4 as built: `tools/clauderun.py` builds every background Claude command (restricted mode already confines the file tools to the run's folder in CLI 2.1.312; added `--strict-mcp-config`, the prompt on standard input, only `render` and `snapshot` of the pinned HyperFrames, no `ffmpeg`, a web-text-is-not-instructions line in the fact check). One real run checked by hand. `usage.refresh_plan` (no tools, fixed prompt) is left as it was.
- Step 5 as built: `tools/version.py` + `CHANGELOG.md`; `.github/workflows/tests.yml` and `release.yml` (not yet run on GitHub: push, check green, then tag v0.1.0); `setup.bat`/`setup.ps1`, `Start Woots Editor.bat`; Settings has a "This computer" card (`appsetup.computer_check`, minimum Claude 2.1.312), a graphics-tool fetch, model licences and card links (read from the Hugging Face model cards on 2026-11-10), the version and a "Check for updates" button; `tools/platformx.py`; prompts say "the host" (checked by `tests/test_prompts_neutral.py`); README rewritten for the zip install; SECURITY.md, CONTRIBUTING.md, issue templates, Dependabot.
  Not done: `requirements.lock` with hashes (pip-compile took over ten minutes and was stopped; setup falls back to `requirements.txt`, whose versions are pinned: generate the lock on a machine with time, or in CI); the speech-packages installer button (Settings still only explains); README screenshots; thumbdraft/storyboard still draw with a navy/orange fallback look; the other copies of the WinGet ffmpeg search (sectionrender, selfreview, storyboard, server) are not yet moved into `platformx`.
- A5 as built: every catalogue entry has a 40-character `revision`; loaders use `engines.local_path()`; the Parakeet load (`restore_from` the pinned `.nemo`) was not run here (no GPU test). The rule in CLAUDE.md now says large models.
- Step 3 as built: `undo.js` (10-second Undo toast after any save that changed a plan file, and a History panel on every video page); `extras.js` (fact check card on Preview and Final, music chooser on Preview, Resolve export on Final, usage line on Home via `/api/usage/week`); Outline has "Ask Claude to fill these" for empty header fields. `projectstore.write_*` now records the file as it was before its first change, so the first edit can be undone too.
  Not done from D7: "Add as a note" on a finding (waits for C3: it needs a time in the video). Dialogs still use `alert` (D2).
- V1/V2 as built: the 16 older screen files and every route only they used are gone (`/` redirects to `/v2/`); kept routes: everything under `/api/v2/`, `/api/code`, `/api/fs`, `/media/`, `/shortmedia/`, `/api/shorts/frame`, and `/api/history*`, `/api/accuracy`, `/api/music`, `/api/resolve`, `/api/usage`, `/api/dash*` for D4 and D7 to D9. Ten orphan command-line scripts were deleted (catalog_music, contact, doublecuts, intro_previews, pacing, remix_audio, whatsat, splice, speakers, track).
  Not done: `storyboard`, `watchnotes`, `shootplan`, `gfxplan`, `selfreview` and `scriptedit` are still imported by live modules (views, workflow, builder, finalrender, ...), so deleting them means untangling those first; `storyboard` and `watchnotes` have no screen now.
- V3 as built: the state code had no gates left; the words are gone from code, prompts and comments, and `tests/test_no_gates.py` keeps them out.
- Left from A3: the 14 private copies of `_replace` in `tools/` are identical and correct; replacing them with `config.replace_retry` is housekeeping, not security.

## Phase A: security (confirmed on the test server unless marked "by reading")

What was found:
- The server listens on every network interface (`--host` defaults to `0.0.0.0`) with no sign-in. Anyone on the same network can list every folder on the computer (`/api/fs`), point a video at any folder and
  stream its files, start Claude runs that use the plan, read the Claude account's email address (`/api/v2/claude`), and start the archive step that deletes files.
- Any web page open in the host's browser can send commands to the app. A cross-site POST with `Content-Type: text/plain` and a foreign `Origin` and `Host` created a video. There is no check of `Origin`, `Host` or content type.
- `work` and `name` from the request go into file paths unchecked on most routes (`views.split_key`, and `WORK / work / ...` in about 30 tools). `key=..\..~x` was accepted.
- Background Claude runs: `Read` and `Write` are allowed without a folder limit. The fact check also has `WebSearch` and `WebFetch`, so a web page with hidden instructions could have it read a private file and send it out.
  The graphics builder may run `ffmpeg *` and `npx hyperframes *`, which can read and write anywhere (by reading).
- Model downloads are not pinned to a revision (`engines._fetch`, `brolllib.from_pretrained`), so a changed upstream repository changes what runs (by reading).

### A1. Listen on this computer only
- `server.py main()`: bind `127.0.0.1` always. Remove the `--host` option, `lan_ip()`, the "phone:" line it prints and the `# one writer at a time (PC + phone)` wording. `supervisor.py` passes no host.
- `start.bat`: remove the lines about the phone address and the Windows Firewall question (a loopback server never triggers it). `README.md` and `docs/how-it-works.md`: no mention of a phone.
- `tests/ui/conftest.py` passes `--host 127.0.0.1`: drop the argument.
- Done when: a test starts the server and a connection to the machine's own LAN address on that port is refused; `grep -rni "phone\|0\.0\.0\.0\|wi-fi" tools README.md docs` finds nothing.

### A2. One request guard
- New `tools/review_app/guard.py` with a pure function `allowed(method, path, headers, client_ip, port) -> (ok: bool, status: int, why: str)`:
  - `client_ip` must be loopback (belt and braces with A1).
  - `Host` must be `localhost`, `127.0.0.1` or `[::1]`, with the server's port (stops DNS rebinding: a hostile site that points its own name at 127.0.0.1).
  - POST: `Content-Type` must start with `application/json`; if `Origin` is present its host and port must equal `Host`. (v2 `util.js api()` already sends JSON.)
- Call it first in `do_GET` and `do_POST`; on refusal `send_json({"error": why}, status)`.
- Add to every response: `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, and on HTML `Content-Security-Policy: default-src 'self'; img-src 'self' data:; media-src 'self' blob:; style-src 'self' 'unsafe-inline'`.
  Check the v2 screens still load with no console error (the UI tests fail on console errors).
- `body_json`: refuse a body over 2 MB (413). Catch any other exception in both handlers and answer `{"error": "Something went wrong.", "details": <last line>}` with 500 instead of dropping the connection.
- Done when: `tests/test_guard.py` covers each rule; a test posts with `text/plain` and with a foreign `Origin` and gets 403; the UI tests pass.

### A3. Check every `work` and `name`
- One function in `config.py`: `safe_part(s) -> str` raises `ValueError("unknown video")` unless `s` is non-empty, has no `/`, `\`, `:`, NUL, is not `.` or `..`, does not start or end with a space or dot.
- `views.split_key` calls it on both parts. In the handler, before dispatch: for GET the query's `work`, `name`, `key`; for POST the body's `work`, `name`, `key` (when present and strings) go through it.
- `server.work_dir`, the `/static/` route and `footage_path_ok` use `os.path.abspath` and `os.path.commonpath` instead of `Path.resolve()` (the rule in `CLAUDE.md`: resolve turns a mapped drive into its network name).
  Then replace the remaining `.resolve()` calls in `tools/` (about 20; `grep -n "resolve()" tools`) the same way, one commit, no behaviour change.
- `server.write_json` uses the retrying replace (`config.replace_retry`), as the state-writer rule asks. The twelve private copies of `_replace` (`grep -n "def _replace" tools`) become imports of `config.replace_retry`.
- Done when: tests show `key=..\..~x`, `work=..`, `name=a/b`, `name=C:x` are refused on every route that takes them; the golden rough-cut test still passes.

### A4. One place builds a Claude command; tighter limits
- New `tools/clauderun.py`: `command(kind, prompt_file, tools, allow, budget, model=None, effort=None) -> list[str]`. Move the five copies into it
  (`server._claude_run`, `server._claude_json_run`, the one at `server.py` about line 1361, `builder.agent_command`, `accuracy._run`).
- Before coding, read the Claude Code permissions page and `claude --help` (the installed CLI is 2.1.x; do not trust memory for the rule syntax). Then:
  - Limit `Read`, `Write`, `Edit` to the run's own folder plus the folders that run truly needs (the builder: the footage folder read-only, the draft stills). Use the documented path-rule form and `--add-dir` only where needed.
  - Add `--strict-mcp-config` so the host's own MCP servers are not loaded into background runs (safer, and fewer tokens per run).
  - Builder: allow `npx --yes hyperframes@<pinned> render *` and `... snapshot *` only, not every subcommand. Remove `Bash(ffmpeg *)` unless a real build needs it (the brief only needs `ffprobe`; if `ffmpeg` is needed, say for what in a comment).
  - Fact check: `Read`/`Write` limited to its folder; add to the prompt that text from the web is material to judge, never instructions to follow.
  - Give the prompt on standard input instead of as an argument (Windows limits a command line to about 32,000 characters, and arguments are visible to other programs). Confirm `claude -p` reads stdin in this CLI version first.
- Done when: a test asserts the argument list for each kind (no bare `Read`, has `--strict-mcp-config`, the pinned HyperFrames version); the existing fake-agent "evil write" test still passes; one real small run (outline) works by hand.

### A5. Pin what is downloaded
- `engines.CATALOG`: add `"revision"` to each entry: the commit hash now in the local cache (`<hf cache>/models--<org>--<name>/snapshots/<hash>`). `_fetch` passes `revision=`; `transcribe.py` and `brolllib.py` pass the same revision to every `from_pretrained` / model load.
  Never pass `trust_remote_code=True`.
- `models/` holds two small face detectors, which contradicts "Models are never in the repository". Either move them to `engines` (download on first use, with a SHA-256 check) or change the rule's wording to "no large models". Default: reword the rule and add their licences to `NOTICE.md` if missing.
- Done when: a test checks every catalogue entry has a 40-character revision and that `_fetch` passes it.

---

## Phase V: remove the older screens and the approval gates

Do this straight after A1 to A3: it removes about half of the routes the later phases would otherwise have to guard, rename and test.

What was found:
- The older screens are `tools/review_app/static/*.js`, `index.html` and `app.css` (16 files), served at `/`. They use the routes without `/v2/` in the path (`/api/wf/...`, `/api/clips`, `/api/beatmap`, `/api/storyboard`, `/api/build`, `/api/script`, `/api/watch`,
  `/api/shootplan`, `/api/selfreview`, `/api/gfxplan`, `/api/gfxreview`, `/api/shorts...`, `/api/footage`, `/api/dash`, `/api/usage`, ...).
- Approval wording and state are still in about 19 tools (`grep -rniE "approv|\bgate\b" tools`): `workflow.py` (stages and their approvals), `gfxplan.py` ("gate G1", "gate G2", "frozen once approved"), `finalrender.py`,
  `storyboard.py`, `builder.py` (the brief tells Claude "the approved plan ... FROZEN"), `sections.py`, `beatmap.py`, `clipmap.py`, `shootplan.py` and others.
- Only the older screens offer: the fact check, the self-review list, music choice, the Resolve export, undo and history, the usage view, the storyboard, the shoot plan, watch notes, and the graphics plan and review.

### V1. Delete the older screens
- Delete `static/*.js`, `static/index.html`, `static/app.css` (keep `static/v2/`). `/` and `/index.html` answer with a redirect to `/v2/`.
- Kept and rebuilt in v2 later: fact check (D7), music choice (D8), Resolve export and usage (D9), undo and history (D4). Their Python tools and routes stay.
- Dropped with the screens: the storyboard, the shoot plan, watch notes, and the graphics plan and review steps as separate screens (the v2 Preview notes and the graphics list in D5 replace them).
  The self-review checks keep running after a preview is built; their findings move into "What changed" on the Preview screen.
- Done when: `/` redirects; the UI tests pass; `tests/test_page_wiring.py` and any test of the deleted pages are removed or rewritten for v2.

### V2. Delete what nothing uses any more
- For every route in `server.py` without `/v2/`: search `static/v2` and `tests/ui` for it. No use and not in the "kept" list above: delete the route.
- Then for every module in `tools/`: no importer left (`grep -rn "import <name>\|from <name>"` in `tools` and `tests`) and not run as a script by the app: delete it and its tests. Work one module at a time and run the tests between.
  Expect `storyboard.py`, `shootplan.py`, `watchnotes.py` and the older `shorts.js` routes to go; `beatmap.py`, `clipmap.py`, `builder.py`, `sections.py`, `selfreview.py`, `accuracy.py`, `musicaudition.py`, `resolve_export.py`, `usage.py` stay because the pipeline or a later task uses them.
- Update `docs/how-it-works.md` to match what is left.
- Done when: the test suite passes and a route listing (print every path the handler answers) has no path that no screen or test calls.

### V3. Remove the approval gates
- `workflow.py`: remove stage approval state, the functions that set or read it, and settings that only gates used. `views.step_of` already works from "the file exists".
- Reword every prompt and brief that says "approved" or "frozen" ("the plan for these beats: build what it asks"). Remove "gate G1 / G2" from docstrings and comments; delete code paths that only ran on approve or un-approve.
- Old project folders may hold approval fields: reading them must not fail (ignore the fields; add a test with an old-style state file from `tests/fixtures`).
- Add a test that fails when `approv` or the word `gate` appears in `tools/` or `static/v2/` (the UI tests already forbid "approve" on screen).
- `README.md` already says there are no gates; make `docs/` agree.
- Done when: the new test passes and an old-style project opens.

---

## Phase R: a public repository with built releases

What was found:
- The repository is already the cleaned public copy (MIT licence, `NOTICE.md`, no personal data; `tests/test_release.py` skips itself here). There is no version number, no changelog, no automatic test run, and no release build.
- Installing takes six typed commands plus separate installs of ffmpeg, Node, the Claude command line tool and the right torch build. The README says "Windows first".
- Some defaults still describe one channel: `gfxplan.STYLES` ("Navy and orange, Oswald Bold"), the builder brief ("OPAQUE brand-navy background"), and the examples named in C6.
- The Claude runs use command-line options that only recent versions of the Claude tool have (`--restricted`, `--permission-prompts`); an older install fails with an unclear error.
- The graphics tool is fetched by `npx` the first time a graphic is built, in the middle of a job.

### R1. A version
- `tools/version.py`: `__version__ = "0.1.0"`. Shown at the foot of Settings and in `server_version`. `CHANGELOG.md` with one entry per release, written for users.

### R2. Tests run on every push
- `.github/workflows/tests.yml`: `windows-latest`, Python 3.12, `pip install -r requirements.txt`, ffmpeg (for example `choco install ffmpeg`), `playwright install chromium`, `python -m pytest`. Run on push and pull request.
- Done when: the workflow is green on `main`.

### R3. A release anyone can install
- `setup.bat` (calls `setup.ps1`) at the top of the repository: finds Python 3.12 (offers the `winget` command if missing), creates `.venv`, installs `requirements.txt`, then checks ffmpeg, Node 22 and the Claude tool and prints the one command that installs each missing one.
  It never installs system software by itself. A second run is safe.
- `Start Woots Editor.bat` at the top (calls `tools\review_app\start.bat`).
- The speech packages are not installed by setup: Settings gets "Install the tools that read recordings" (a job that runs `pip install` with the torch build that fits the card `hardware.probe` found, with the size shown first). Until then the Footage step explains what is missing instead of failing.
- `.github/workflows/release.yml`: on a tag `v*`, run the tests, build `woots-editor-<version>.zip` from `git archive` (no tests folder needed at run time, but keep it: it is small), write its SHA-256, and attach both to a GitHub Release with the changelog entry as the text.
- Done when: on a clean Windows machine (or a fresh user account) the zip, `setup.bat` and the start file lead to the first-run Settings screen with no typed command.

### R4. "What this computer has" on first run
- One card at the top of Settings: Python, ffmpeg, Node, the Claude tool (with its version and the minimum the app needs; put the minimum in `appsetup.py` and check it in `claude_status`), the graphics card, free disk space. Each row is a tick or one plain sentence with the fix.
- Fetch the pinned HyperFrames package from this card ("Get the graphics tool", a job), so the first graphic build does not start with a download.
- Done when: a test fakes each missing piece and sees its sentence.

### R5. Nothing channel-specific in the defaults
- `gfxplan.STYLES` and the builder brief take colours and fonts from `brandstyle` (the profile), with neutral words when the profile is empty. Sweep `tools/` and `skills/` for other leftovers of one channel (colour names, font names, product names in examples); C6 covers the prompts.
- Starter skill folder `woots-channel` keeps its name only if nothing shows it to the user as a channel name; otherwise rename it `channel` and keep reading the old name from a user's folder.
- Done when: a fresh profile produces a graphics brief with no colour or font the user did not choose.

### R6. Dependencies a stranger can trust
- `requirements.lock` with hashes (`pip-compile --generate-hashes`), used by `setup.ps1`; `requirements.txt` stays the readable list. Dependabot for pip and GitHub Actions.
- Model pins come from A5. Each catalogue entry also gets `"licence"` and a link to its model card, shown before the download button (read each model card; do not write a licence from memory).
- `SECURITY.md` (how to report a problem; the app listens on this computer only and has no accounts), `CONTRIBUTING.md` (the rules in `CLAUDE.md`, how to run the tests), issue templates for a bug and an idea.

### R7. Say which systems work
- First release: Windows 10 and 11 only, stated in the README and checked in `setup.ps1`.
- Cheap steps toward other systems, so the tests could run on Linux later: wrap `os.startfile`, `taskkill`, `CREATE_NO_WINDOW` and the WinGet path search in one module (`tools/platformx.py`) with a fallback for other systems. No promise of support.

### R8. The README for a new user
- Order: what it does (with two screenshots), what you need and what it costs (a Claude plan; no other service), download and install (the release zip), first run, where your files live, privacy (what goes to Anthropic; that the fact check searches the web), updating (download the new zip, run setup again; your data is elsewhere), building from source.
- A "Check for updates" button in Settings that asks the GitHub releases page only when pressed (the app makes no network call on its own).

---

## Phase B: models and Claude runs

What was found:
- One setting ("Editing", Sonnet at medium) covers both judgement work (the outline, reading the cut, choosing the hook, choosing between takes, titles) and mechanical work (picking a shot, framing, applying a note).
  The story is where a stronger model pays; the mechanical runs are fine as they are.
- Each Claude step in the rough cut may fail and the job carries on (`job["ok"] = True` after each run in `start_rough_cut`). That is right, but the host is never told the cut was not read, no hook was looked for, or takes were not compared.
- Budgets are fixed strings in the code (`"0.6"`, `"1.0"`); a dearer model can hit the cap and fail quietly.
- Local models (Parakeet, Whisper, Qwen3-VL, SigLIP) suit the job. The smaller Qwen models are marked "quality not measured yet".

### B1. A "Story" job
- `claudemodels.JOBS`: add `"story": ("Story", "The outline, the hook, reading the cut, choosing between takes, titles.", "opus", "high")`. Narrow the "Editing" help text to what is left.
- Pass `kind="story"` from the outline, cold open, cut review, takes, publish and (C2) story runs. Tests in `test_claudemodels.py`.
- Done when: Settings shows the new row; a test asserts which kind each run uses.

### B2. Budgets follow the model
- `claudemodels.budget(kind, base) -> str`: `base` times a factor per model (`haiku` 0.5, `sonnet` 1, `opus` 3, `fable` 5; put the table next to `MODELS`). Every `budget="..."` call site goes through it.
- When a run ends because of the budget, the job's sentence says so in plain words ("Claude ran out of budget for this step").
- Done when: a unit test covers the table; a fake result with the budget stop reason shows the sentence.

### B3. Say what was skipped
- In `start_rough_cut`, after each Claude step that failed, add a line to `changes`: "Not done: <step in plain words> (<reason>)". Show these first in "What changed", in the warning colour.
- Done when: with `WOOTS_FAKE_CLAUDE` missing one answer file, the kept cut lists the skipped step.

### B4. Measure the small vision models (optional)
- A script that describes the same 20 frames with each installed Qwen size and writes them side by side, so the catalogue notes can say something measured. No app change.

---

## Phase C: skills, toward the stated goal

The goal: graphics that teach and graphics that entertain; the best story from the footage and transcript; a title, description and tags for the final video.

What was found:
- **Publishing ignores its skill.** `publish.brief` gives Claude the outline, not what was said in the final, and copies no skill file. The prompt says titles under 70 characters and up to 15 tags; the skill says 60 and "a few specific phrases".
- **The story is the outline's order.** The cut is the recordings in outline order with mistakes removed. Claude may suggest moving a passage, and the suggestion is listed as "not done". Nothing ranks the best moments of what was actually filmed,
  and a cut cannot be started without an outline.
- **Nothing proposes entertaining graphics.** Graphics come from the outline and from teaching moments. The starter graphics skill says a graphic that neither teaches nor shows should be left out. The kinds `stamp`, `burst`, `kinetic`, `counter` exist but no pass looks for places to use them.
  Long videos get a sound effect only where a beat names one.
- **Runs see few skill files.** Cut runs get four files (`skillrules.FOR_CLAUDE`). Files a host is likely to keep (story patterns, takes and splicing, lessons, director's notes, house style) are not handed over.
- **The starter set is thin** (about 20 KB) and two skills (`youtube-edit`, `youtube-shorts`) have no `SKILL.md`, so they are not real skills when copied to `~/.claude/skills`.
- **Prompts assume a man** ("his", "he", "him": 44 places in `tools/`), and some hold examples from one channel (`accuracy.PROMPT`, `cutreview.brief`).
- **Lessons are added by hand.** `rough-cut.md` has a "Lessons" section; nothing offers a line for it after notes are applied.

### C1. Publishing from the final, by the skill
- New `skills/youtube-publish/publish.json`: `title_max_chars` 60, `titles` 5, `hook_max_chars` 200, `tags_max` 12, `thumb_words_max` 3. Read it with `skillrules.numbers` (add `PUBLISH_DEFAULTS`).
- `publish.brief`: copy `youtube-publish/*.md` and `youtube-script/hook-library.md` into the run folder; write `said.json` (the sentences of the newest cut or final, with times, from the beat map) next to `script.md`; build the limits in the prompt from the numbers.
- Ask for more in the answer: each title with `why` (the promise it makes) and a `thumb_text` that adds to the title instead of repeating it; `pinned_comment` (one question for viewers); tags as specific phrases.
  `apply_answer` enforces the limits in code and keeps the rule "a title the host chose is never replaced".
- Add to `skills/youtube-publish/SKILL.md`: title patterns (result, question, wrong belief, number that matters) with the test "does the first 30 seconds keep this promise?"; title and thumbnail are one unit; the description's first line is for search and for the viewer; how to pick tags.
- Final screen: show the reason under each title option and the pinned comment with a Copy button.
- Done when: tests cover the limits and the files copied; the fake answer in `tests/ui/conftest.py` gains the new fields; the Final screen test still passes.

### C2. The story from the footage
- New `skills/youtube-edit/story.md` (rules) and keys in `rough-cut.json` for any numbers. Rules to write: find the question the video answers and where it is answered; the strongest opening (a result, a failure, a claim) and whether it can be shown, not only said;
  the setback; the payoff; what is weak or repeated; good unplanned moments (a joke, a mistake, a reaction) that the outline did not plan; an order is changed only when a first-time viewer would follow it better.
- New `tools/story.py` (model on `takes.py`): `brief(work, name, fd)` writes every recording's sentences with ids, the outline, the footage descriptions and tags; Claude answers `story.json`:
  `{"logline", "question", "answer_at", "opening": [{ids, why}], "setback": {ids, why}, "keep_moments": [{ids, kind, why}], "weak": [{ids, why}], "order": [{section, before, why}]}`. `apply_answer` validates ids. Add `.story.json` to `projectstore.PLAN_SUFFIXES`.
- Use it: the cold open run reads `opening`; the cut review treats `keep_moments` as locked against drops; `weak` and `order` become suggestions (C3). Runs once per cut version, `kind="story"`, skipped (and reported, B3) when it fails.
- **Outline from footage.** On the Footage screen, when there is no outline: "Write the outline from my recordings". It reads the recordings first, then one run (the story files plus `youtube-script`) writes `outline.md` in the usual format, a section per recording.
  `start_rough_cut` no longer refuses when this can run.
- Done when: unit tests for `story.apply_answer` (bad ids dropped, locked sentences never listed as weak); a job test with a canned `story.json`; the outline-from-footage path works in the UI test with fake Claude.

### C3. Suggestions become one-click notes
- "What changed" lists each suggestion (`cutreview` suggestions, `story` weak and order) with a button "Add as a note". It adds an ordinary note with the suggestion's words and clip range; the next "Make cut N from my notes" applies it. No new state, no approval step.
- Done when: a UI test presses the button and sees the note; the note text names the sentences by their words, not ids.

### C4. Graphics that entertain
- Skill: new `skills/youtube-graphics/moments.md`, and change the line in `SKILL.md` to: a graphic either teaches, shows one thing, or lands a moment the host made. Rules to write: only underline what the host did or said (never add a joke of its own);
  short (about 1 to 1.5 s on screen), one word or one number; kinds `stamp`, `burst`, `kinetic`, `counter`, plus a punch-in and a sound effect; never over a teaching line, never over the face, never two within a few seconds; fewer is funnier.
  Numbers in a new `skills/youtube-graphics/graphics.json`: `moments_per_min_max` 1.5, `moment_gap_s` 8, `moment_max_s` 1.5.
- Code: `tools/moments.py`, the same shape as `teaching.py`: `find_prompt` gives the cut's sentences and the rules, Claude answers `{"moments": [{"beat", "words", "kind": "joke|fail|reveal|opinion|number|callback", "graphic": "stamp|burst|kinetic|counter|none", "text", "sfx": bool, "why"}]}`;
  `import_found` enforces the caps and refuses beats that hold an accepted teaching moment. Add `.moments.json` to `PLAN_SUFFIXES`.
- Screen: a second list under the clip strip on the Rough cut screen, next to teaching moments, with the same yes / no ticks ("Fun moments"). A "yes" puts the graphic on the beat (`graphic.kind`, `text`, `why`) and, when `sfx`, a name in `audio.sfx`.
- Sound: let a long video place effects the way shorts do (`sfxkit`), only on accepted moments and graphic landings, with a cap a minute in the skill. This is the "next step" already written in `quality-plan.md`.
- Shorts: `shortsapp.gfx_prompt` refuses shorts made from raw footage; give them the same planning from their own words (no beat map needed).
- Done when: unit tests for the caps and the teaching clash; the UI test accepts a canned moment and sees it in the plan; a builder brief for a `stamp` carries the moment's text and the 1.5 s limit.

### C5. Each run gets the right files
- `skillrules.RUN_FILES = {"takes": [...], "coldopen": [...], "cutreview": [...], "story": [...], "shots": [...], "publish": [...], "outline": [...], "moments": [...]}`; `copy_into(fd, run)` reads it. Files that do not exist are skipped as now.
  Suggested: every run gets `woots-channel/house-style.md` and `woots-channel/director-notes.md`; takes adds `youtube-edit/takes-and-splicing.md`; cut review and story add `youtube-script/structure.md`, `youtube-script/story-patterns.md`, `youtube-edit/lessons.md`; cold open adds `youtube-script/structure.md`.
- Add general starter versions of `story-patterns.md`, `takes-and-splicing.md` and `lessons.md` (an empty dated list) so a new user has them. Write them fresh, for any talking-head channel.
- Add `SKILL.md` (name, description, which file is for what) to `skills/youtube-edit` and `skills/youtube-shorts`.
- Done when: a test asserts each run's list and that a missing file is skipped; `test_release.py` (no names) passes on the new files.

### C6. Neutral, general prompts
- Replace "he / his / him" for the host with "the host" / "they" / "their" in every prompt and brief (`grep -rnw "his\|he\|him" tools`). Extend the test that fails on a person's name to fail on these words inside prompt strings.
- Move the one-channel examples out of `accuracy.PROMPT` and `cutreview.brief` into general ones (any product names removed).
- Done when: the extended test passes.

### C7. Offer a lesson after notes
- After `makeversion.apply_answer`, the same run may return `"lesson": "<one general sentence, no times, no video names>"` when a note taught something that would apply to other videos. Show it under "What changed" with "Add to my editing rules";
  the button appends a dated line to the Lessons section of the user's `youtube-edit/rough-cut.md` (copy the starter file there first if the user has none).
- Done when: a test appends once, never twice for the same sentence, and never writes into the repository's `skills/`.

---

## Phase D: screens

What was seen in the test server:
- The same button shows two estimates: "Make the rough cut" says about 11 min on Footage and about 3 min on Rough cut.
- New video uses the browser's `prompt()`; errors use `alert()` (29 uses of `alert`/`prompt`/`confirm` in `static/v2`).
- The step bar's dots have no words: nothing says which step is next, and a hollow dot can sit between two green ones.
- Outline: every item has a ✕ that deletes at once with no undo on screen. Logline, thesis and promise say "Click to write" with no help.
- Preview: nothing shows which graphics will be built, or lets one be skipped, before the long build. The clip strip's boxes can be blank.
- Settings is one long page with two Save buttons; the field "subjects" shows its internal name; five effort levels with no hint of cost.
- v2 has no fact check, no undo or history, no music choice, no Resolve export, no usage view. After Phase V nothing on screen offers them until D4 and D7 to D9 are done, so do those early.
- "Shorts" appears in the top bar and as a step, with different content.

### D1. One estimate per job
- `views.py`: the Rough cut screen's button uses the same function as the Footage screen (recordings still to read, footage still to look at), not the fixed `_PIPELINES["cut"]` time. Test both views give the same text for the same project.

### D2. No browser dialogs
- `util.js`: `ask(title, {placeholder, okLabel})` (a small inline dialog built with `<dialog>`), `say(message)` (a toast in the job bar area), `sure(message, okLabel)`. Replace every `prompt`, `alert`, `confirm` in `static/v2`.
- Done when: `grep -n "alert(\|prompt(\|confirm(" static/v2` is empty and the UI tests pass (they already fail on console errors; add one test for New video).

### D3. A step bar that says where you are
- Each step link gets a `title` and `aria-label` from the server ("Outline: done", "Rough cut: next", "Final: not started"); the next step gets a "Next" tag. `views.step_of` already knows the state: derive the dots so a later step is never ahead of an earlier one unless files really exist, and say "made earlier" in that case.

### D4. Undo on every screen
- A quiet "Undo" appears in the job bar for 10 seconds after any change to a plan file, and a "History" link sits in the head row of each video (list from `/api/history`, restore with `/api/history/restore`; both exist).
- Outline: add "Ask Claude to fill these" beside the empty logline, thesis and promise (a note to the existing revise run).
- Done when: UI test deletes an outline line, presses Undo, sees it back.

### D5. Graphics list before the build
- Preview screen, above "Make preview N": a closed block "Graphics in this preview (n)" listing each one in plain words (what it shows, over which words, teach or fun), with a skip tick and the build estimate. Skipping writes the plan through `gfxplan` (status `cut`). Not a gate: the button works without opening it.
- Clip strip: every box shows a frame, the first words and the length; an empty box never renders.

### D6. Settings in sections
- A short list of links at the top (Folders, Your channel, Brand, Claude models, Models, Claude sign-in) and one sticky Save that saves whatever changed. `channel.FIELDS` gains a label for each key so no internal name shows ("What your footage shows").
- Claude models: mark the default with "recommended", add "Back to defaults", and one line under effort: "Higher effort is slower and uses more of your plan."

### D7. Fact check in v2
- Final screen (and Preview): a card "Check the facts" that starts `accuracy.start`, shows the summary and the problems first, each with its source link and "Add as a note" (as in C3).

### D8. Music and sound in v2
- Preview screen: a "Music" block listing each music stretch with the tracks to try (`musicaudition`), play and "Use this".

### D9. Resolve export and usage in v2
- Final screen: "Export for DaVinci Resolve" button (`/api/resolve/export`, then "Open the folder"). Settings or Home: a small "This week's use of your plan" line from `usage.week_summary`.

### D10. Small things
- Top bar "Shorts" becomes "All shorts".
- Every icon-only button (✕, ticks) gets an `aria-label`; visible focus rings; check the muted grey text against the WCAG AA contrast ratio.
- "Finish and archive": the confirm step lists what will be deleted and what is kept, from `/api/v2/archive/preview`.

---

## Housekeeping found on the way
- `CLAUDE.md` says the Python is the repo's `.venv`; `start.bat` also accepts `%USERPROFILE%\.venvs\wootseditor`. Say both.
- `server.py` is 2,200 lines with one long `if` chain per method. After Phase V, move the routes that are left into a table (`ROUTES = {("GET", "/api/v2/home"): fn}`) so the guard, the name check and the lock are applied in one place,
  and give the kept older routes `/api/v2/` paths. No behaviour change; do it in its own commit.
- The file names `static/v2/` and the `/v2/` paths can stay: renaming them gains nothing a user sees.
- The app-specific skill in the user's own skills folder still describes approval gates and the older tabs; it should be brought in line with `CLAUDE.md` (it is outside this repository).
- `CLAUDE.md` itself: remove "(the older tab-based UI is in `tools/review_app/static/`)" after V1, and add the release rules from Phase R (version bump and changelog entry with every release).

## Suggested order
1. Close the holes: A1, A2, A3.
2. Shrink the app: V1, V2, V3, then the route table.
3. Bring back what the older screens had: D4 (undo), D7 (fact check), D8 (music), D9 (Resolve export, usage).
4. Finish security: A4, A5.
5. First public release: R1, R2, R5, C6, R4, R3, R6, R7, R8. Tag `v0.1.0`.
6. Quality of the edit: B3, B1, B2, C1, C5, C2, C3, C4, C7.
7. Screens: D1, D2, D3, D5, D6, D10.
