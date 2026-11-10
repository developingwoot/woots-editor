# Woots Editor

A local app that turns your raw recordings and an outline into a rough cut, a preview and a final render, with Claude doing the judgment work and ffmpeg doing the cutting.

It is made for talking-head YouTube channels: you write (or have Claude draft) an outline, record yourself and your b-roll, and the app finds the best take of every line, cuts the pauses and mistakes, picks cutaways from your own footage, adds graphics, music and sound effects, and renders the result. You review each step, leave notes, and Claude applies them. Nothing is posted anywhere.

> Status: first release (0.1.0). Windows 10 and 11 only for now. It was built for one channel's workflow and is being opened up; expect rough edges, and please open an issue when you find one.

## What it does

1. **Outline**: write or draft the video's outline (sections, shot ideas, voice-over notes).
2. **Footage**: point it at your recordings. It reads them into words with times, describes your b-roll, and lets you tag clips yourself ("console tab, dashboard").
3. **Rough cut**: the best take of each line, mistakes and long pauses removed, repeats resolved, cutaways chosen. You keep, replace, trim or remove clips, mark sentences as good (they are never touched again), and leave notes.
4. **Preview**: graphics, music and sound effects added; you watch it and leave notes.
5. **Final**: the full-quality render, loudness-matched, with chapters and a description draft.
6. **Shorts**: vertical cuts of the finished video.

Every plan file is recorded and undoable. There are no approval gates: each step is a draft until you render the next one.

## What you need

- Windows 10 or 11 (other systems are not supported yet).
- A Claude plan, with the [Claude Code](https://claude.com/claude-code) command line tool signed in (version 2.1.312 or newer). That is the only paid service: the app asks Claude to read your outline, transcripts and notes and to write plans, and some steps look at still frames. How much of your plan a video uses is shown on the Home screen.
- Python 3.12, [ffmpeg](https://ffmpeg.org) and Node 22 or newer. `setup.bat` checks all three and prints the one command that installs any that is missing.
- Optional but recommended: an Nvidia graphics card. Without one the app reads recordings with a small Whisper model on the processor, which is slower and less exact.
- Disk space: models download on first use (a few GB to about 20 GB depending on your card; Settings shows each size and licence before you download).

## Install and start

1. Download `woots-editor-<version>.zip` from the [Releases page](https://github.com/developingwoot/woots-editor/releases) and unzip it somewhere you keep programs (not your recordings folder). The `.sha256` file next to it lets you check the download.
2. Double-click `setup.bat`. It makes a private Python environment and checks the programs above. It installs no system software by itself. Run it again after installing anything it listed, and after every update.
3. Double-click `Start Woots Editor.bat`. The app opens at http://localhost:8765/v2/. It answers on this computer only: nothing else on your network can reach it.

The first run opens Settings: pick your workspace folder, tell it about your channel (name, audience, voice, brand colours), and sign in to Claude. The **This computer** card shows what is ready and what is missing, with the fix for each, and has a button that fetches the graphics tool ahead of time. Nothing downloads until you press Download.
Reading recordings on an Nvidia card needs the packages in `requirements-speech.txt`; Settings explains when they are needed.

Music and sound effects are not included: put your own in the Music and SFX folders you choose in Settings.

## Updating

Settings has a **Check for updates** button. It asks the GitHub releases page only when you press it; the app makes no network calls on its own. To update, download the new zip, unzip it over a new folder, run `setup.bat` again. Your projects and settings are stored elsewhere, so they are not touched.

## Building from source

```bash
git clone https://github.com/developingwoot/woots-editor.git
cd woots-editor
setup.bat
```

or by hand: `python -m venv .venv`, `.venv\Scripts\pip install -r requirements.txt`, then `tools\review_app\start.bat`.

## Where your files live

The code and your data are kept apart. Your recordings, project folders, music and sound effects live in the workspace folder you choose in Settings, never inside this repository. Your channel profile and settings are saved in your user folder (`%APPDATA%\WootsEditor`). To teach Claude your style, put your own copy of any file from `skills/` in `~/.claude/skills/<skill>/`; your file is used instead of the starter one.

## Privacy

The app runs on your computer. Recordings are read by models that run locally. The Claude steps send text (your outline, transcripts, notes) and some still frames to Anthropic through your Claude Code sign-in. The fact check also lets Claude search the web for sources. The app itself calls no other service, except to download a model when you press Download and to look for a new version when you press Check for updates. Model files download from their publishers on first use.

## Tests

```bash
.venv\Scripts\python -m pytest
```

The suite takes about a minute and touches none of your real data. See [docs/how-it-works.md](docs/how-it-works.md) for the layout of the code and [CLAUDE.md](CLAUDE.md) for the rules for changing it (also read by coding agents).

## Licence

MIT, see [LICENSE](LICENSE). Third-party material is listed in [NOTICE.md](NOTICE.md).
