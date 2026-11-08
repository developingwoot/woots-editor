# How the code is laid out

## The pieces
- `tools/review_app/server.py`: the local web server and every `/api/...` route. `supervisor.py` restarts it when code changes (and when Settings saves new folders, exit code 75).
- `tools/review_app/static/v2/`: the screens (home, outline, footage, review for rough cut and preview, final, settings). `util.js` has the shared helpers.
- `tools/*.py`: one tool per job. Pure logic lives in functions the tests import.

## A video, start to finish
1. `outline.py`, `scriptedit.py`: the outline model (sections, shot ideas, voice-over lines) and versions of it.
2. `transcribe.py`, `brolllib.py`, `tags.py`, `footageview.py`: read recordings into words with times (Parakeet on an Nvidia card, Whisper otherwise), describe b-roll, let the user tag clips.
3. `recut.py`, `takes.py`, `cutreview.py`, `cutcheck.py`, `framing.py`, `coldopen.py`, `shotmatch.py`: the rough cut. The numbers come from `skills/youtube-edit/rough-cut.json`.
4. `locks.py`: sentences the user marked good; no pass changes them.
5. `cutview.py`, `makeversion.py`, `reviewnotes.py`, `watchnotes.py`: the review screen, versions (Cut 1, Cut 2, ...) and the notes Claude applies.
6. `gfxplan.py`, `sections.py`, `builder.py`, `sectionrender.py`, `selfreview.py`: graphics, built in sections by background Claude runs; the preview.
7. `finalrender.py`, `loudness.py`, `publish.py`, `finalize.py`, `resolve_export.py`: the final render, metadata and an export for DaVinci Resolve. `scorecard.py`: how the final compares with
   reference videos (`skills/youtube-edit/references.json` plus the user's own in `_editor/references`), shown on the Final screen.
8. `shortsplan.py`, `shortsapp.py`, `shorts.py`, `shortsgfx.py`: vertical shorts from the finished video, a video file or raw footage; `shortsview.py` feeds the v2 Shorts screen, which also edits the YouTube details and saves the final shorts next to the source (`shortsapp.deliver`). Colours and fonts come from the channel profile through `brandstyle.py`; video encoders through `encoders.py` (NVENC when it opens, else libx264); the numbers and rules from the `youtube-shorts` skill. The host's feedback on shorts (a note on one short, or a general one) is saved in the `.shorts.json`; Claude applies it with `shortsapp.feedback_prompt` / `apply_feedback`, and open notes are also given to the find, tighten, graphics and title prompts.

`claudemodels.py` holds the model and effort chosen in Settings for each kind of Claude run (edit, graphics, critic, fact check, shorts); every `claude -p` call takes its flags from it.

## Setup and configuration
- `config.py`: folders (environment variables, `config.local.json`, the per-user `settings.json`, defaults). `appsetup.py`: the Settings and sign-in logic.
- `channel.py`: the channel profile and what goes in front of every Claude prompt. `skillrules.py`: finds the user's skill files, falling back to `skills/`.
- `hardware.py`, `engines.py`: what the computer can run, the model catalogue and downloads.
- `projectstore.py`: every change to a plan file is recorded with who and when, and can be undone.

## Tests
`tests/` runs without the real data folder: `conftest.py` points every setting at a temp folder. Tests that need ffmpeg are skipped without it; browser tests live in `tests/ui`.
