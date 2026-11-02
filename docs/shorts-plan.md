# Shorts: the plan

Status: planned 2026-11-02; Phases 0 to 7 are done (see "as built" below); nothing else is built yet. Work through the phases in order; each one ends in something the
host can use and a green test run. Read `CLAUDE.md` first: its rules (no approval gates, plan files through `projectstore`, channel data only in the
profile, a test for every behaviour change) all apply here.

## What the host asked for

- Shorts as **their own area** (top level, next to "Your videos") **and** as the **Shorts step** of a video.
- Three ways in:
  1. **From a video made in the app** (the Shorts step): the final, its transcript and beat map are already there.
  2. **From any finished video file**: drop in a file (the test case is a 10 min 15 s, 1280x720, 30 fps talking-head video with b-roll:
     a real one from the channel, kept outside the repo).
  3. **From a pile of raw footage**: point at a folder of recordings and b-roll; the app makes a short from it.
- **Captions: 2 to 3 words at a time** (as `shorts.py` does now), the spoken word popping, in a fun shorts style that **follows the channel's brand**
  (the fonts and palette now picked in Settings).
- **Music and SFX: as much as works.** A music bed under every short, and sound effects on cuts, pops and graphics.

## What already exists (read before writing anything)

| Piece | File | State |
|---|---|---|
| How many shorts and where (10 s to 3 min, favour < 60 s, ~1 per 3.5 min, max 8; strong moments from the beat map; transcript-only fallback) | `tools/shortsplan.py` | built, tested |
| Shorts project: read/edit, Claude picks moments (`find_prompt`/`import_candidates`), tighten, publishing details, deliver | `tools/shortsapp.py` | built |
| Vertical render 1080x1920: dead air cut, a cut or zoom change every 2-3 s, face-following crops, `blur` layout for b-roll, captions (ASS, 1-3 words, spoken word pops), hook title, progress bar, -14 LUFS, NVENC | `tools/shorts.py` | built |
| Graphics plan for a short: Claude proposes ~1 per 6 s, draft stills on the vertical frame, each marked ok/change/cut | `tools/shortsgfx.py` | built; **building the graphics is not** |
| Music and SFX resolving (catalog, "no vocals under dialogue" rule) and the mix (beds at -26 LU, ducked 9 dB under speech, crossfades, SFX scaled to the speech peak) | `tools/finalrender.py` (`resolve_music`, `resolve_sfx`, `mix`), `tools/musicaudition.py` | built for the main video only |
| Transcription (Parakeet, or faster-whisper), word times | `tools/transcribe.py` | built |
| Raw recordings -> a cut (picks the right take, removes restarts and repeats) | `tools/recut.py`, `tools/takes.py` | built for the main video |
| B-roll description and matching | `tools/brolllib.py`, `tools/shotmatch.py`, SigLIP in `tools/engines.py` | built |
| Old Shorts tab UI | `tools/review_app/static/shorts.js` (422 lines), `/api/shorts/*` routes in `server.py` | works, old UI only |
| v2 Shorts step | `static/v2/video.js` | **"coming soon"** |

### Problems in the existing code that the plan fixes

1. **Brand is hardcoded** in `shorts.py`: `ORANGE_ASS` (#E2703A), `NAVY_BGR` (#142C44), `FONT_FILE = "Oswald-Bold.ttf"`, the orange progress bar, the
   navy pad colour, and graphic detection by "navy corners". That breaks the rule that channel data lives only in the profile; another user gets this
   channel's look.
2. **Approval states**: shorts have `proposed/approved/rejected`, and the graphics plan refuses to run until a short is "approved". `CLAUDE.md` says
   there are no approval gates, and the v2 clutter check rejects the word "approve" on screen.
3. **`.shorts.json` is not a plan file**: it is written by `shortsapp.save_raw`, not through `projectstore`, so changes are not recorded or undoable.
4. **One source per project**: a short's `ranges` are seconds in a single `source` file. Raw footage needs ranges from several files.
5. **Shorts rules are constants in code** (`MIN_S`, `FAVOUR_S`, ...). The rough cut keeps its numbers in a skill (`skills/youtube-edit/rough-cut.json`,
   read by `tools/skillrules.py`); shorts should do the same.

## Decisions taken

- Captions stay **2-3 words per line** (`chunks_of`), the spoken word highlighted and popping. Style comes from the profile.
- **Music on every short, SFX generously** (see phase 5 for the rules that keep "more" from turning into noise).
- A short is **kept** or **dropped** by the host; a dropped short is hidden, not deleted. Nothing waits on that choice: graphics can be planned for
  any short, the final render only warns about shorts the host has not looked at.
- Shorts numbers and rules move to a new skill, **`skills/youtube-shorts/`** (`shorts.json` for numbers, `shorts.md` for rules), read through
  `skillrules.py`; the user's copy in `~/.claude/skills` wins.

## Phases

### Phase 0: try the existing pipeline on a real video (no code changes)

Goal: see what the current code makes of a real video before building on it, so the later phases fix what actually looks wrong.

- Work in a temp workspace (`WOOTS_DATA_ROOT` etc. pointed at a temp folder, per `CLAUDE.md`). Never write next to the source file.
- Transcribe it (`transcribe.py`). Use the speech model Settings picks for the machine: time how long it takes and check the word times by ear.
- Create a project with `shortsapp.new_project`, run `video_plan` (expect: no beat map, ~3 shorts for 10 min), pick one or two moments by hand,
  render with `shorts.py render` and make the contact sheet (`shorts.py sheet`).
- Write down, in this file under "Phase 0 findings": crop quality on talking head and on b-roll, how the 720p source looks blown up to 1080x1920
  (a 9:16 crop of 720p is 405x720, a 2.7x upscale), caption timing, and anything that broke.

Done when: findings are written here and each one is mapped to a phase below (or a new item).

### Phase 1: foundations (no new screens)

1. **Brand from the profile.** A new `tools/brandstyle.py` turns the profile into what renderers need:
   `palette()` -> `{"primary", "accent", "light", "dark", "extra": [...]}` from the `colors` text (the roles the Settings palette writes;
   sensible fallbacks when the profile is empty: white text, black outline, a neutral accent), and `font(role)` -> `{name, family, file}` for
   `headline_font` / `label_font`. `sysfonts.installed()` gains the font **file path** (the registry value data on Windows, `fc-list` `file` on
   Linux) because libass needs the file in `fontsdir`.
   `shorts.py` reads all colours and the font from `brandstyle`. Graphic detection stops looking for navy: use the palette's primary colour, or
   (better, if Phase 0 shows it works) "a flat, static frame with large uniform areas".
   Tests: palette parsing (roles, names, missing hex, empty profile), font lookup, and a test that `shorts.py`/`shortsgfx.py` contain no hex colour or
   font name literals.
2. **Kept/dropped instead of approved.** Statuses become `""` (not looked at), `kept`, `dropped`. Old files are read with `approved -> kept`,
   `rejected -> dropped`, `proposed -> ""`. Remove the "approve the short first" gate in `server.py`. Update tests.
3. **`.shorts.json` becomes a plan file**: add it to `projectstore.PLAN_SUFFIXES` and write it through `projectstore` (who, why, undo).
4. **Several sources per project.** Format v2: `"sources": [{"id": "a", "path": ..., "transcript": ..., "kind": "talk|broll"}]`, and each range is
   `{"src": "a", "a": 20.6, "b": 40.6}`. A file in the old format (`source` + `[[a, b]]` ranges) is read as one source `a`. `build_pieces`,
   `kept_words`, crops, captions and the render work per range source. Tests: old-format files load unchanged; a two-source short renders the right
   frames (synthetic clips, ffmpeg-gated like the other render tests).
5. **Real source sizes** (phase 0 finding 1): ffprobe each source and replace the `SRC_W/SRC_H` constants. Test with a synthetic 1280x720 clip.
6. **One encoder helper** (phase 0 finding 2): `tools/encoders.py` probes NVENC once and falls back to libx264; every renderer calls it instead of
   hardcoding `h264_nvenc`. This is app-wide, not only shorts, so it also fixes the main video's renders on any computer whose Nvidia driver is too old for the installed ffmpeg.
7. **The `youtube-shorts` skill**: move the numbers from `shortsplan.py` and the caption/pace numbers from `shorts.py` into
   `skills/youtube-shorts/shorts.json`, and the prose rules (from `shortsplan.find_rules`, ADR 0006 notes in the code) into `shorts.md`.
   No names or channel facts in it (the existing name-guard test must pass).

Done when: the full test suite passes and a render of an existing shorts project looks the same as before (except colours/font now come from Settings).

### Phase 2: the Shorts area and the Shorts step in v2

One screen module, `static/v2/shorts.js`, used two ways:

- **Top level**: a "Shorts" link next to "Your videos" (`#/shorts`). Lists shorts projects (from videos and standalone), plus two buttons:
  "Shorts from a video file" (phase 3) and "A short from raw footage" (phase 4).
- **Step of a video**: `#/v/<key>/shorts` replaces "coming soon" in `video.js`, opening that video's shorts project (created on first visit
  from the final + transcript + beat map; if there is no final yet, say what is needed and link the Final step).

The project screen (one layout for every source):
- The recommendation sentence ("This video has strong moments for about 3 shorts") and a "Find shorts" button (Claude, `find_prompt`).
- A card per short: a frame, title, length, the hook, Keep / Drop, Play the quick preview.
- Opening a short: the player (vertical preview), the word strip with the cuts (drop words or ranges, the existing `apply_op` ops), the hook text,
  layout per piece (face crop / blur / fit), the caption style (phase 5), music and SFX (phase 5), graphics (phase 6), and "Make the final".
- Notes on a short go to Claude, like the review screen ("Tighten it", "make the hook stronger").
- Long jobs (transcribe, find, render) run as app jobs with the existing job bar.

Plain words only on screen (the UI clutter check). Browser tests in `tests/ui/test_shorts_screen.py`: the area lists projects, the step opens the
video's project, keep/drop, a preview render appears (fake Claude answers, like the other UI tests).

### Phase 3: shorts from any finished video file

- "Shorts from a video file" -> a file picker (extend `folder.js`, which only picks folders today, to list video files too) -> a new standalone project in `WORK/_shorts/<slug>/`.
  The file is **referenced, not copied** (big files; same idea as footage folders).
- Job: transcribe (the chosen speech engine), then look at the frames (the chosen vision model, as `brolllib` does) so pieces without a face are
  known to be b-roll before any crop is guessed. Then the recommendation and "Find shorts" as in phase 2.
- Without a beat map, `shortsplan` has no "strong moments"; add a transcript+vision score instead: questions, numbers, contrasts ("but", "instead",
  "the fix"), a payoff after a setup, and b-roll stretches (visual) score higher. Pure function, tested.
- The 720p case: when the source is under 1080 px tall, prefer the `blur` layout (sharp 16:9 in the middle) for b-roll and a gentler zoom on the
  talking head, and show a small note ("The video is 720p, so close crops look soft"). Thresholds go in the skill.

Done when: the test video goes from file to 2-3 found shorts with previews, with no hand editing of JSON.

### Phase 4: a short from raw footage

The biggest phase; start it only after phases 1-3 work on the test video.

- "A short from raw footage" -> choose a folder -> every file is transcribed and looked at (reuse the Footage step's code: `footageview`,
  `brolllib`, `transcribe`), talking recordings and b-roll are told apart (`recut`'s MIN_WORDS / MIN_RATE rule).
- Claude gets the transcripts of the talking recordings (with `takes.py`'s repeats and restarts marked) and the b-roll descriptions, and writes
  1-3 short candidates as **a script of ranges across sources**: the best take of each line (never a restarted or abandoned take, the `recut`
  rules), plus b-roll ranges laid over named words. Output into the phase 1 multi-source format; checked by code (lengths, every range inside its
  file, no line from an abandoned take) before it is shown.
- B-roll over talking: a b-roll range plays picture-only while the talking range's sound continues (new piece field `audio_from`).
  The renderer needs to support this; test it with synthetic clips.
- Optional for this phase, decide after the first results: Claude may ask for a **pickup line** to record ("you need one sentence that says what
  the fix was"), shown as a missing-shot list like the Footage step does.

Done when: a folder of real raw footage gives at least one watchable short without hand edits.

### Phase 5: the fun layer: brand captions, music, SFX

Captions (all in `shorts.make_ass`, styles from `brandstyle` and the skill):
- Keep 2-3 words per line. Add **caption styles** the host picks per short (default in the skill): `pop` (today's: the spoken word in the accent
  colour, scaled up then settling), `box` (the spoken word gets an accent-coloured box behind it), `bounce` (each new line drops in), `plain`.
- **Emphasis words**: numbers, the channel's key terms (profile `terms`), and words Claude marks in the find/tighten step get the accent colour and
  are bigger for their whole line. Keep it to about one emphasis word per 3 seconds.
- Font: the profile's headline font (file from `sysfonts`); the hook title uses the label font if set.
- Safe zones on 1080x1920: captions between y=1050 and y=1450, nothing in the bottom 380 px or the right 150 px (YouTube's buttons and title).
  Numbers in the skill. Test: no caption or hook position outside the zone.

Music:
- Every short gets a bed from the Music folder: chosen by Claude from `music_catalog.json` (mood, tempo; never a track with vocals, the existing
  rule) or by the host from a list with a play button (`musicaudition.py`).
- Mix with the main video's recipe (move `finalrender.mix` into a shared `audiomix.py` that both renderers call): bed under the speech,
  ducked while the host talks, a short swell where there is no speech, fade out at the end. Final loudness stays -14 LUFS.

SFX ("the more the better", with rules so it stays fun and not noisy):
- An **SFX kit**: roles -> files from the SFX folder, guessed from file names (`whoosh`, `swoosh`, `pop`, `click`, `ding`, `riser`, `hit`, `boom`,
  `glitch`, `typing`) and editable in Settings. Saved per user, not in the repo.
- Placed by code, not by Claude: a whoosh on each zoom change / cut between pieces, a pop on each emphasis word, a hit when a graphic lands,
  a riser into the payoff line, a ding on numbers. Rules in the skill: at least 0.4 s between SFX, never on top of the first word after a cut,
  scaled to the speech peak (existing rule), at most N per 10 s (start at 6).
- Each placed SFX shows on the word strip and can be removed or swapped by the host.
- If the Music or SFX folder is empty, the short renders without them and the screen says what is missing (never blocks).

Tests: the SFX placement function (spacing, caps, roles), the music choice never picks a vocal track, the shared mix gives the same output for the
main video as before (a regression test on synthetic audio).

### Phase 6: build the graphics

`shortsgfx` already plans graphics with draft stills; build the ones marked OK.
- `kinetic` key-word pop-ups first (they are the most common and the simplest): rendered as ASS or a short transparent clip, in brand colours.
- Explainer looks next: reuse the main video's graphics builder (`builder.py`, `sectionrender.py`, the `youtube-graphics` skill) at 1080x1920
  for `place: full|top|bottom` regions (`shortsgfx.REGIONS`).
- Each built graphic gets a hit SFX (phase 5) and is overlaid at its time in the render.

### Phase 7: finish

- Final render (1080x1920, best quality) of kept shorts, publishing details (`publish_prompt`/`apply_publish` exist), deliver to the footage
  folder or a chosen folder.
- Update `docs/how-it-works.md` (the Shorts line) and this file's status.

## Phase 1 as built (2026-11-02)

- `tools/encoders.py`: `adapt(args)` keeps NVENC flags when `h264_nvenc` opens (probed once) and otherwise rewrites them for libx264; `render.py`, `assemble.py`, `splice.py`, `shorts.py` use it
  (`sectionrender.py` already had its own fallback).
- `tools/brandstyle.py`: `palette()`, `font()`, colour formats; `sysfonts.file_for()` and `family_of_file()`. `shorts.py` and `shortsgfx.py` hold no colour or font literal (a test checks it).
  Graphic-card detection uses the palette's primary colour. With an empty profile: white text, black outline, a neutral dark primary, a yellow accent, and the Oswald file that ships in `fonts/`.
- Statuses are `""`, `kept`, `dropped` (old files are read as before); no approval gate; graphics, the final render and delivery work on every short that is not dropped.
- `.shorts.json` is a plan file written through `projectstore` (history and undo).
- `shorts.py` reads each source's real size (`probe_size`); crops, graphic cards and the `blur` layout use it. Pieces carry `src`, `sw`, `sh`, `noaudio`.
- Several sources: `sources` plus `{"src", "a", "b"}` ranges load, pick words, cut, caption and render per source (tested with two clips of different sizes). **Not done yet** (they belong to
  the phases that need them): Claude's find/tighten prompts, `shortsplan.validate`, the old tab's range editor and the graphics plan still assume one source; a `broll` source has no
  words, so it only produces pieces once Phase 4 adds ranges laid over words (`audio_from`).
- The `youtube-shorts` skill holds the numbers (`shorts.json`: lengths, count, strength, caption size, hook time) and the rules text of the find prompt (`shorts.md`); the user's copy wins.
  Pace presets (`PACES`) stay in code: they are choices the host picks per short.
- Left in `shorts.py` for Phase 5: caption sizes/positions, the hook box position and the -14 LUFS target are still literals.

## Phase 2 as built (2026-11-02)

- `static/v2/shorts.js` is the screen: `#/shorts` (the area: every video with shorts or a final) and `#/v/<key>/shorts` (the step). `tools/shortsview.py` makes its data in plain words;
  the routes are `/api/v2/shorts/*` in `server.py` (keep, drop, hook, title, pace, cut a word, preview, tighten, make, find, finish). Long jobs show their own sentence in the job bar.
- The step: no final -> says so and links to Final; a final but no project -> "Make the shorts" (reads the final, then Claude chooses); a project -> the recommendation sentence, "Find more shorts",
  "Make the final shorts", one card per short (frame, title, length, hook, Keep / Drop / Open), dropped shorts under "Dropped" with Bring back. An opened short has its preview (or "Make a preview"),
  the hook, the pace, "Tighten it", and the words (click to cut or restore). Shorts nobody kept or dropped are still made, with a line saying so.
- **Not built yet**: notes to Claude on a short, layout per piece, caption style / music / SFX / graphics panels (Phases 5 and 6), and the two buttons for a video file (Phase 3) and raw footage (Phase 4).
- Also fixed: `channel.save` and the settings writer retry `os.replace` (`config.replace_retry`), which failed intermittently on Windows while the server read the file.

## Phase 3 as built (2026-11-02)

- "Shorts from a video file" on the Shorts area opens a file picker (`pickFolder({files: true})`, starting in the folder used last), then a job: read the file word by word (the chosen speech
  engine), write a project in `WORK/_shorts-<slug>/` (the file stays where it is), and Claude chooses the shorts. The project opens at `#/shorts/<key>`.
- No beat map: `shortsplan.spoken_moments()` scores windows of speech (questions, numbers, a turn such as "but" / "the fix", a payoff at the end) and the best non-overlapping ones become
  the moments in the sentence and in Claude's prompt. Numbers (`moment_*`, `soft_below_px`, `broll_similarity`) are in the `youtube-shorts` skill.
- A frame with no face that looks nothing like the frames where the speaker was found (colour histogram) is b-roll and gets the `blur` layout instead of a guessed crop.
- A source under 1080p shows "The video is 720p, so close crops look soft."
- Finished shorts of a standalone project go to a `Shorts` folder next to the source file (the existing delivery); change it if you would rather have one folder in the workspace.
- **Not built**: looking at frames with the vision model (the colour test stands in for it), and a score that uses what is on screen.

## Phase 4 as built (2026-11-02)

- "A short from raw footage" on the Shorts area: choose a folder (the files stay where they are; sub-folders are not entered). Every file with sound is read word by word; a recording with at least
  `raw_min_words` words said at `raw_min_words_per_s` or faster is a talking recording, anything else is b-roll. The project is `<name>.shorts.json` with `mode: "raw"`, talking sources `t1, t2 ...`,
  b-roll `b1, b2 ...`, and per talking source `mistakes` (`rawshorts.mistakes`: recut's restart / repeated phrase / repeated sentence / stammer finders; the later take stays).
- Claude (`rawshorts.prompt`) gets each talking recording's transcript with the mistakes marked and, for each b-roll clip, a strip of four frames (`shorts/_find/broll/<id>.jpg`) to look at.
  It answers with `ranges` ({src, a, b}: the best take of each line), `overlays` and an optional `missing` line. Up to `raw_max_shorts` shorts.
- `rawshorts.check` stops a short whose range is not in a talking recording, runs past its file, is mostly an abandoned take, is too short / long, plays one part twice or has no setup / point / payoff.
  An overlay that does not fit (not a b-roll clip, used twice, outside the clip, under `overlay_min_s`, at a word that is not in the short, over the first two seconds) is left out alone;
  one over `overlay_max_s` is shortened. What was left out is shown in `last_find`. The mistakes inside a short's ranges are written into its `drop`, so a click on the word brings them back.
- Rendering: `shorts.apply_overlays` splits the pieces at the overlay and gives the covered part `over` (b-roll file and seconds, `blur` layout). `filter_graph` takes that part's picture from the
  b-roll input and its sound from the talking recording, so the voice never breaks. Captions and the other pieces keep their times. Overlays are part of the render signature.
- **J and L cuts**: the b-roll picture comes in `overlay_lead_s` (0.15 s) before the word it illustrates (a J cut), and it can run on past the end of a sentence (an L cut) because Claude sets its length.
  A shift between two talking-head pieces (different takes) is **not** built: the frames either side of such a cut show the speaker's mouth moving to other words, so it only works with a cutaway.
- **Pickup lines**: the app only uses what is there. When Claude says a line is missing it is added to the short's "why" as "Missing: ..." and nothing is requested from the host.
- **Not built**: the notes box and per-piece layout of Phase 2, picking a different b-roll clip for an overlay in the UI, searching b-roll by meaning (`brolllib`, SigLIP: Claude looks at the strip instead),
  and a real run on the host's raw footage.

## Phase 5 as built (2026-11-02)

- **Shared mix**: `tools/audiomix.py` holds `mix`, `decode`, `ff` and `SR`; `finalrender` imports them, so the main video's output is unchanged (checked on synthetic audio: identical samples before and after the move).
- **Captions**: four styles picked per short in the Sound panel (`caption_style`; default `caption_style` in the skill): `pop`, `box` (accent box behind the spoken word), `bounce` (each line drops in), `plain`.
  **Emphasis** (`shorts.emphasis`): numbers, the profile's terms and the words in the short's `emphasis` list get the accent colour and a bigger size for the whole line, at most one per `emphasis_gap_s`.
  **Safe zone** (`caption_pos`, `caption_size`): lines sit between y = 1050 and 380 px above the bottom; a line stays centred when its right edge clears the right 150 px, moves left when it does not,
  and shrinks (its own ASS style) when it is too wide for the zone. The hook is placed with the same rule. One caption at a time: a line ends where the next starts (the Phase 0 overlap).
- **Sound effects** (`tools/sfxkit.py`): roles whoosh, pop, ding, hit, riser guessed from the file names in the SFX folder; the user's choice per role is saved in `<state>/sfx_kit.json`
  (`POST /api/v2/shorts/kit`, `GET /api/v2/shorts/sounds`). Placed by code (`sfxkit.place`, events from `shortsaudio.events`): a whoosh on each cut or zoom step, a hit when a graphic lands,
  a pop on an emphasised word, a ding on a number, a riser a second before the last piece. Rules from the skill: `sfx_gap_s` apart, at most `sfx_max_per_10s` in ten seconds, nothing on the first word
  after a cut; when there is no room the more important sound wins; the same role rotates through its files.
- **Music** (`tools/shortsaudio.py`): the host's choice, "No music", or a track the app picks (steady, near 110 bpm, different from short to short) from the Music folder. A track the catalog marks as
  having vocals is never offered or used. The bed is mixed with the main video's recipe: `music_below_speech_db` under the voice, `duck_db` further down while the host talks, faded in and out, then -14 LUFS again.
- Rendering (`shorts.render`) mixes after the picture is made and reports what it did (`audio`: track, number of SFX, what was missing) into `<id>.render.json`; the Sound panel shows it.
  A missing Music or SFX folder is said, never a failure.
- **Not built**: the SFX list on the word strip with remove / swap per sound (the kit is per role), a kit editor in Settings (the API and the file exist), Claude choosing the track or the emphasis words in
  the find / tighten step (the `emphasis` list exists and is used when something fills it), a swell in music where nobody talks, `glitch` and `typing` roles, and a real run on a real Music / SFX library.

## Phase 6 as built (2026-11-02)

- `tools/shortsgfxbuild.py` builds what `shortsgfx` planned, in the channel's colours and font (`brandstyle`), when a short is rendered: every graphic the host has not cut (no OK step; a graphic
  is built unless it is cut), for a short made from one recording.
- **Kinetic** (`look: kinetic`): the one to three words pop in the accent colour, in the graphic's region, as ASS events drawn with the captions.
- **Every other look is a card**: a panel in the region (`top`, `full` opaque, `bottom`) with the headline (the first line of the graphic's `text`) and, one at a time while the words are said,
  up to four items (the other lines). The picture of each step is made with PIL and laid over the video at its time (fade in with a small rise, fade out). The plan prompt now asks Claude for list items on separate lines.
- Each built graphic gets a `hit` (card) or `pop` (key word) sound at its start through `shortsaudio.events`.
- The open short has a Graphics panel: Plan graphics (the Claude run that already existed), each planned graphic with Cut / Bring back, and the plan's note; the preview is rebuilt with them.
- **Not built**: the main video's own graphics builder (`builder.py`, `sectionrender.py`, the `youtube-graphics` skill: Claude-written animated scenes) for diagrams and UI mockups at 1080x1920,
  graphics for a short joined from several recordings, the draft stills in the v2 panel, "change" notes on a graphic, and moving a graphic's time or place.

## Ideas to think about (from the host)

- **Cuts timed to the music's beat.** With a music bed (Phase 5), snap cut points and zoom steps to the nearest beat when a beat is within a few tenths of a second, and keep SFX on the beat.
  Needs a beat tracker (librosa is already a dependency); the rule and its tolerance belong in the `youtube-shorts` skill.
- **J and L cuts.** The sound leads the picture (J) or trails it (L): the next line's voice starts under the end of the last shot, or the last line's voice keeps going over the next shot.
  The renderer already treats audio and picture of a piece separately in places; Phase 4 needs `audio_from` (b-roll over talking), which is the same mechanism. Plan: add an `audio_offset`
  per cut in the piece (a few tenths of a second, set by rule in the skill, adjustable per short), use it between a talking piece and the next, and always for b-roll over speech.

## Open questions (ask the host when the phase starts)

- Phase 3: where should standalone projects' finished shorts go: next to the source file, or a Shorts folder in the workspace?
- Phase 4: is a pickup-line request useful? (Built as: the app only uses what is there, and shows Claude's "missing line" note. Say if you want a recording request.)
- Phase 5: which caption style should be the default? Any SFX that must never be used?
- Transcription speed on small cards: phase 0 showed Whisper large-v3 in 8-bit runs fine on a 4 GB card (about 6x faster than real time).

## Phase 0 findings (2026-11-02)

Run on a real one from the channel, kept outside the repo (10:15, 1280x720, 30 fps, one speaker, b-roll), in a temp workspace, with three shorts
picked by hand from the transcript (41 s, 35 s, 29 s; the third joins two ranges).

**Worked**
- **Transcription**: Whisper large-v3 on a 4 GB Nvidia laptop card (8-bit weights) read the 10.2 min video in **62 s** (80 s with start-up): 1647 words, word times
  good, no misheard words in the parts read. So the 4 GB laptop is fine for transcription; Parakeet is not needed (see below).
- `shortsplan` recommended 3 shorts, confidence "low" (no beat map: the length only), as designed.
- Planning all three shorts took 1 to 7 s; **every piece was found as the single speaker** and the face-following crop worked on the talking head
  (2 zoom levels alternating every 2-3 s, as designed). Previews (540x960, x264) rendered in 5-15 s each.
- Captions (2-3 words, the spoken word in the accent colour and popping), the orange hook box (first 2.8 s) and the progress bar all look right.

**Broken or wrong**
1. **A 720p source crashes planning**: `shorts.SRC_W, SRC_H = 1920, 1080` is a constant, so `auto_classify` reads pixels outside the 1280x720 frame
   (`IndexError`). Crop maths, the graphic-corner test and the `blur` layout all assume 1080p. Fix in phase 1: read each source's size with ffprobe and
   use it everywhere (`crop_box`, `auto_classify`, `filter_graph`). The trial used an upscaled 1080p copy to get past it.
2. **NVENC does not open on a PC with an older Nvidia driver**: the current ffmpeg wants NVENC API 13.1 (driver 610+) and this driver gave API 12.2, so every
   `h264_nvenc` call fails. That is 8 files (`shorts.py`, `render.py`, `assemble.py`, `sectionrender.py`, `splice.py`, ...), not only shorts.
   Fix in phase 1: one helper `encoders.video(quality)` that probes once (`ffmpeg -f lavfi -i nullsrc -frames:v 1 -c:v h264_nvenc -f null -`) and falls
   back to libx264 with matching flags; every renderer uses it. Test: the helper's flag lists, with the probe faked both ways.
3. **B-roll is treated as a talking head**: the b-roll pieces (a mechanism on a ruler, a printed model) were marked `live` and cropped to a centred 9:16
   window, which cut the subject in half. Fix: phase 3 looks at frames first; a piece with no face is b-roll and uses `blur` (sharp 16:9 in the middle
   with a blurred copy behind) or a subject-aware crop.
4. **Caption lines overlap at some chunk boundaries**: "POINT THIS" was drawn over "WHERE I" (visible in the s3 hook-time frame). A chunk's last word
   is held for `+0.12 s` past its end while the next chunk can already be starting. Fix in phase 5: end every caption event at the next event's start.
5. **The brand is hardcoded** (confirmed): the orange and navy came from constants in `shorts.py` although this trial had an empty profile.

**Not checked yet**: audio levels and the loudness target, the final-quality (1080x1920) render, how soft the 2.7x upscale of 720p looks at full
size, vision-model descriptions of the b-roll, anything with music or SFX.

**Parakeet**: not an option here. A 4 GB card is under the app's 6 GB for Parakeet, and that venv had a CPU-only torch and a NeMo that did not
import. `engines.py` now lists Whisper large-v3 at 4 GB and `transcribe.py` loads it in 8-bit on cards under 8 GB, whatever the machine.
The Whisper CUDA libraries for a CPU-torch install are an optional block in `requirements-speech.txt`.

## Phase 7 as built (2026-11-02)

- The backend already wrote titles (`publish_prompt`/`apply_publish`), rendered finals and delivered; the v2 screen now reaches all of it. An opened short has a "YouTube details" panel
  (title, description, tags, file name: edited by hand, saved when you leave the box, or "Write them for me" for Claude). The step has a "Full video link" box (put in each description)
  and "Write all the titles". A card says "Saved" once its final is in the folder, or "Saved, changed since" when the short was edited after.
- "Make the final shorts" renders every short that is not dropped at 1080x1920 unless its final is current, then copies each into `Shorts` next to the source with a `.txt` of its details
  (never overwrites; an identical file is not copied twice). The screen names that folder. A standalone project uses the folder of its source file; a different folder is not a setting yet.
- `docs/how-it-works.md` describes the Shorts step. Tests: `tests/test_shorts_finish.py`, one UI test.
- Phases 0 to 7 are done. The ideas and open questions above are what is left.
