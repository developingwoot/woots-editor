# Woots Editor

Local web app + Python tools that run a talking-head YouTube workflow: Outline, Footage, Rough cut, Preview, Final, Shorts. Stdlib `ThreadingHTTPServer` in `tools/review_app/server.py`,
the current screens are one JS module per screen in `tools/review_app/static/v2/` (the older tab-based UI is in `tools/review_app/static/`), one Python tool per job in `tools/`.
See `docs/how-it-works.md` for the map of the code.

## Code vs data (read this first)
- **Code** lives in this repository. **Data** (footage, per-video work folders, Music, SFX, the app's state) lives in the workspace folder the user chose in Settings and is NOT in git.
- All data paths come from `tools/config.py` (`DATA_ROOT`, `EDITOR_DATA`, `WORK`, `MUSIC_DIR`, `SFX_DIR`). Never hardcode a drive or a user folder. Override with env vars
  (`WOOTS_DATA_ROOT`, ...), a git-ignored `config.local.json`, or the per-user `settings.json` the Settings screen writes.
- Use `os.path.abspath`, never `Path.resolve()`: resolve turns a mapped drive letter into its network name.
- Channel-specific data (name, channel, audience, voice, brand, misheard terms) lives in the per-user profile (`tools/channel.py`), never in code, prompts or starter skills.
  If a good edit needs a per-user file, first-run setup must create it.

## Run
- App: `tools\review_app\start.bat` (port 8765; the supervisor restarts it when code changes). Python is the repo's `.venv` (`requirements.txt`), or `WOOTS_PYTHON`.
- Tests: `.venv\Scripts\python -m pytest` (about a minute, touches no real data). Run before every commit.
- Manual check of a change: start a second server on another port (`server.py --port 8799`) with `WOOTS_DATA_ROOT`, `WOOTS_SETTINGS_FILE`, `WOOTS_PROFILE_FILE` and `WOOTS_SKILLS_DIR`
  pointed at a temp folder, and drive the real page. Never test on real video folders.

## Rules
- Edit files with the Edit tool; do not patch source with scripts that write `\n` inside strings.
- State writers use atomic writes with retry (`workflow._replace`): `os.replace` fails on Windows while another thread reads.
- There are no approval gates: stages are drafts, done = file exists, the build shows an estimate, the final render only warns. Do not add approval states.
- Plan files (script, clips, beat map, graphics plan, notes, marks, tags, locks; `projectstore.PLAN_SUFFIXES`) are written through `tools/projectstore.py` so every change is recorded and undoable.
  A new kind of plan file goes in `PLAN_SUFFIXES`.
- The user's change notes are applied by Claude, not by the buttons.
- Add or change behaviour => add or change a test in `tests/`. Pure logic goes in a function a test can import.
- The rough cut follows the `youtube-edit` skill: numbers in `skills/youtube-edit/rough-cut.json`, rules in `rough-cut.md` (`tools/skillrules.py` reads them; the user's copy in
  `~/.claude/skills` wins; Claude runs are given copies). When a note teaches something general, update the skill and the code together.
- Prompts say "the host" and "the channel"; `channel.prompt` puts the user's profile in front. A test fails if a string names a person.
- Models are never in the repository: `tools/engines.py` lists them and downloads them on first use.
