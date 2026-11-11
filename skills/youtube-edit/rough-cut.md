# Rough cut from recordings

The app builds the first cut from your recordings. It reads `rough-cut.json` (every number named below) each time it makes a cut, and checks a finished cut against the same numbers.

## How a video is built from recordings
- A recording is a section of the outline. The video is the talking recordings in outline order, each from its first complete take to its end, with mistakes removed.
- The outline is the plan; the recordings are what exists. A line with no recording of its own is usually said inside another recording.
- The latest take of a section wins (Intro_3 beats Intro_1) unless it stops short or stumbles. When you say a passage twice in a row, the second time is nearly always the keeper.

## Rules (numbers are in rough-cut.json)
- **Pace.** `"pace": "calm"` uses the numbers in the file as they are. `"pace": "fast"` replaces `beat_min_s`, `beat_max_s`, `punch_hold_s`, `punch_flat_s`, `hook_total_s` and `cold_open_max_s`
  with a rhythm that changes the picture every few seconds (nothing unchanged for much over `beat_max_s`) and allows a longer hook while the picture keeps changing.
  It is an option, not a finding about what works: the fast numbers come from the rhythm of seven maker and tech videos, with no view or retention data behind them.
- **Pauses.** Cut a silence longer than `max_pause_s`. Keep a breath: never cut to nothing. A host who leaves deliberate beats (a joke landing, a reaction, a moment of the build) raises
  `max_pause_s` (about 1.0 keeps them); the videos that do this have 30 to 75 pauses over a second, the tighter ones 5 to 15.
- **Layouts.** Alternate the face with the work (hands, parts, screen, a graphic). When a talking stretch runs past `beat_max_s`, the change of picture should be the work, not only a zoom.
- **Pieces.** A kept piece is at least `min_piece_s` long, so the video never flickers between fragments. Joining pieces of two takes needs at least `splice_min_words` words from the other take.
- **Beats.** A beat (one idea on screen) runs `beat_min_s` to `beat_max_s`. A longer stretch needs a change of picture.
- **Repeats.** The same phrase of `repeat_phrase_words` words within `repeat_phrase_within_s` seconds is a stumble or a retake: keep one.
- **Cutaways.** B-roll covers at most `broll_max_s` seconds at a time and only when the picture shows what is being said.
- **Transitions.** A cutaway comes in and goes out with a preset from `transitions.json` (a web page slides in with a whoosh, other B-roll is a plain cut, unless Settings say otherwise).
  To give one insert its own, put `"transition": "<preset id>"` on that insert in `on_screen.broll`. Use moves sparingly: a whoosh on every cutaway soon feels cheap.
- **Punch-ins.** A slow zoom of `punch_in_zoom` keeps a long shot alive; hold at most `punch_hold_s` before a change.
- **The opening.** The hook, any cold open and the intro together fit `hook_total_s`: the point of the video starts by then.
- **Cold open.** If the real start is later than `cold_open_after_s`, open with `cold_open_min_s` to `cold_open_max_s` seconds of the best line.

## Lessons
(Add a dated line here each time a note on a cut teaches the app something. Turn it into a rule above; the video's times are only evidence.)
