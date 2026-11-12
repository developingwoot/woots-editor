# Live timeline editor: plan

A timeline on the Preview screen where the host fine-tunes the video before the final render: every clip, B-roll, graphic, text card, blur, sound
effect and music bed is visible and editable, and the video above it plays the edit **live**, without a render. Later the rough cut uses the same editor.

Status: planned, not built. Build one phase at a time; each phase ends with both test suites green and a commit. Read `CLAUDE.md` and
`docs/how-it-works.md` first; every rule there applies (plan files through `projectstore`, a test per behaviour, no approval gates, never test on real video folders).

## Decisions already made (do not reopen)

| Topic | Decision |
|---|---|
| Live vs render | The editor plays the plan live in the browser. It is **very close**; the ffmpeg render stays the **exact** final. A "Render this part exactly" button checks a stretch. |
| One edit list | The live player and ffmpeg read the **same** edit list (`sections.baseline_edit` output). Cut points are stored as output frame numbers at 30 fps so both cut on the same frame. |
| Source playback | No proxies by default. The server rewraps the asked-for stretch of a recording into fragmented MP4 by stream copy (no re-encode, nothing stored). A small 540p proxy is made only for a recording the browser cannot play. |
| Graphics | Built graphics are HyperFrames HTML compositions (a paused GSAP timeline in `window.__timelines[id]`). The live player runs the composition itself over the video and seeks its timeline; no MOV in the browser. |
| Ripple | Like CapCut: the main track never has a gap. Trimming or removing a clip pulls everything after it up. |
| Attached items | Text cards, stickers, B-roll, sound effects and blurs belong to the clip they start on and move with it. They may run on over the following clips. If their clip is removed they move to the next clip and the timeline says so. |
| Teaching graphics | Locked to their voice-over: they move with it and cannot be dragged off it. Their length can change inside it. |
| Trim snapping | Trims snap to word boundaries (the words show on the clip); a modifier key trims freely by frame. |
| Lengthening a sticker | Changes the composition's duration (live, instant). The exact render rebuilds that graphic; the editor says so. |
| Audio | Per clip: voice volume, mute, fade in/out. Per music bed: volume, start, end, track. Per sound effect: volume, move, remove. |
| Out of scope (v1) | Reordering clips, adding new clips from the footage (rough cut and notes do these). A native app or Tauri shell (may come later; it does not change playback). Colour matching. |
| Notes | Stay. The editor is for exact changes; notes are for what Claude should do. |
| Rough cut | Goes live with the same editor after the preview editor has proved itself (last phase). |

## How it fits the code

- The plan is the beat map (`<name>.beatmap.json`). Everything the editor shows is already there: `aroll.in/out/keep` (clip and its kept stretches),
  `on_screen.broll`, `on_screen.text`, `on_screen.blur`, `graphic`, `audio.music`, `audio.sfx`. New fields go on the beat, written through `projectstore` (undo comes with it).
- `tools/sections.py baseline_edit()` turns beats into the edit list (`segments`, `broll`, `overlays`, `blurs`, `sfx`); `tools/sectionrender.py` renders it. The live player consumes the same structure, served as JSON.
- `makeversion.clip_times()` and `noteactions.beat_at()` map times to clips today from rendered versions; with a live timeline the times come from the edit list itself.
- Screens are one JS module each in `tools/review_app/static/v2/`; the review screen is `review.js`. The editor is new modules (`timeline.js`, `liveplayer.js`, `liveaudio.js`), not more code in `review.js`.
- Blur paths are tracked on a rendered cut today (`tools/blur.py`). Phase 5 moves tracking to the source recording so a path survives a trim.

## Data added to the plan

```
beat.aroll.gain_db_user   number, added to the recording's own gain (default 0)
beat.aroll.mute           true to silence the clip's voice
beat.aroll.fade_in / fade_out   seconds
beat.audio.music_db       number, added to the bed's level for this run of clips
beat.audio.sfx            entries become {"name", "at", "db"} (the old "name @ t" strings are still read)
on_screen.text[i] / graphic / broll[i] / blur[i]: "dur" may run past the clip's end (spill)
```
`sections.baseline_edit` must lay a spilling item over the following segments (`_spread_overlay` does this inside one beat today).
`sections.beat_sig` already covers these fields, so sections go out of date by themselves.

## Phases

### Phase 0: trial (decides whether to go on)
Goal: prove live playback on real-shaped footage before anything else is built. Throwaway UI is fine; the server parts are kept.
1. `GET /api/v2/live/edit?key=` returns the edit list for the whole video (reuse `cutview.edit_for`), with each segment's `in`/`out` snapped to output frames.
2. `GET /api/v2/live/media?key=&rel=&from=&to=` streams that stretch of a recording as fragmented MP4 by stream copy (`-c copy -movflags frag_keyframe+empty_moov+default_base_moof`), starting on the keyframe before `from`. Only files inside the footage folder (`config.inside`).
3. `liveplayer.js`: two `<video>` elements swapped at each cut (the next one is seeked and paused ahead of time), driven by one clock; B-roll as a third layer; the voice through Web Audio.
4. One HyperFrames composition over the picture in an iframe, seeked from the clock.
Pass when, on a test project with an MKV (H.264, 60 fps), an MP4 and an HEVC clip: a cut lands within one frame of the ffmpeg render (compare a frame grabbed from the page with the same output frame from `sectionrender`), playback over 20 jump cuts does not stall, and sound stays in sync within 40 ms.
If it fails: stop and report what failed; the fallback is the same timeline with an "Update preview" button that rebuilds only the touched sections.

### Phase 1: timeline, read only
The timeline under the live player on the Preview screen: main track of clips (thumbnails, words on the clip, waveform), lanes for B-roll, graphics and text, blurs, sound effects, music. Zoom (ctrl+wheel and buttons), scroll, playhead, click to seek, frame stepping (comma and full stop exist). Waveforms: `GET /api/v2/live/wave?key=&rel=` returns peaks, cached in the work folder.
Done when the timeline matches the edit list in a UI test and stays usable at 10 minutes and 40 clips.

### Phase 2: clip edits
Trim a clip's start or end (word snap, modifier for frames), remove a clip, ripple. Undo and redo (ctrl+Z, ctrl+shift+Z and buttons) on top of `projectstore` history. Attached items follow their clip; a removed clip hands its items to the next clip with a notice. Pure logic in a Python module a test can import (`tools/timeline.py`): `trim`, `remove`, `ripple`, `reattach`.

### Phase 3: attached items
Drag to move, drag an edge to lengthen, delete: text cards, stickers, B-roll, sound effects, blurs. Spill over following clips, in the live player and in `baseline_edit` + `sectionrender` (a test renders a text card across a cut). Teaching graphics locked to their voice-over. Each edit shows what it costs: "free" (timing only) or "this graphic is rebuilt for the final".

### Phase 4: audio
Per clip volume, mute, fades; music bed volume, start, end, track; sound effect volume. Live in `liveaudio.js` (gain nodes; ducking from the same envelope `audiomix.mix` uses, sent by the server). The same fields applied in `sectionrender`, `audiomix` and `finalrender`. One steady gain for the whole video stays (`finalrender.steady_gain`): never bring back a loudness filter that rides the volume.

### Phase 5: exact renders and state
- Badges: "N graphics to build" and "The final is older than your edits". No "make the preview" wait for timing edits.
- "Render this part exactly": renders the sections under the selection with `sectionrender` and plays the result beside the live view.
- Versions become snapshots of the plan (a `projectstore` marker), not video files; "Apply my notes" replaces "Make preview N from my notes" and updates the timeline when Claude is done.
- Blur tracking moves to the source recording (`blur.follow` on the take, the path stored in take time).
- The final render reads the plan as edited (it already goes through `baseline_edit`); a test compares a live frame and a final frame at five sample times.

### Phase 6: the rough cut goes live
The Rough cut screen uses the same player and timeline (clips, B-roll, text, blurs, music, sound effects; graphics when built). "Make cut N" becomes applying notes to the plan. Keep Keep / Replace / Trim / Remove on a clip, now instant.

## Risks to watch

- **Mixed frame rates.** Sources are 60, 30 and 24 fps; the output is 30. The live player must show the frame ffmpeg would pick (`fps=30` picks the nearest earlier source frame); seek by output frame, never by source time alone.
- **Keyframe distance.** A stream copy starts on a keyframe, so a stretch may begin up to a few seconds early; the player seeks inside it. If OBS recordings have very long keyframe gaps, seeking is slow: measure in phase 0.
- **Six connections per host.** A player taken off the page must release its source (`releasePlayer` in `review.js`); media requests must not starve the job check.
- **Two renderers drifting.** Every new field is implemented in both and covered by a test that renders it with ffmpeg and reads it back in the page.
- **HyperFrames live.** Compositions must be loaded from the graphic's own folder with no network access and no access to the app's API (sandboxed iframe).
- **Windows command length.** Long filter graphs already go to a file (`-/filter_complex`); keep that.

## For the session that builds this

- Model: Sonnet. One phase per session; start from this file and the phase's section.
- Phase 0 first, and stop for the host's go-ahead after reporting its three measurements.
- Tests: `.venv\Scripts\python -m pytest` and the same with `-m ui`, both before each commit. Manual checks only on a temp data root.
- Do not edit the host's own skill copies in `~/.claude/skills`. Do not push.
