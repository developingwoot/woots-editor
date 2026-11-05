# Quality plan: edits that hold up next to the reference videos

Draft, 2026-11-04. Built from the study of seven maker and tech videos (and the host's shark video) in November 2026. Numbers from that study are guides, not targets: there was no view or retention data.

## What the study says the gap is
1. **Footage, not editing.** The reference videos change the picture every 3 to 4 seconds because they have something to cut to: hands at work, the part close up, an overhead of the bench, the CAD screen, the result.
   The shark video has strong graphics but little footage of the work, so its talking stretches run up to 70 s with one overlay. No editor can cut to a shot that was never filmed.
2. **Rhythm.** Even with one camera, the references change framing 2.3 to 3.5 times a minute while the host talks (crops, a second angle). The shark video: about 1.3.
3. **The opening.** The references open on the thing or the result, in the first frame, and say the stakes in the first half minute.
4. **Graphics are already a strength.** The shark video's diagrams, formula card and recap teach better than any reference. What the references add is many small, quick ones: a big number, a name label, an arrow on footage.

So the order of work is: measure, then help the host film the right things, then make the edit use them, then make graphics quicker and more consistent.

## Phase 1: a scorecard (measure before changing anything)
One panel on the Preview and Final screens, and a command for any video file: picture changes a minute, longest unchanged stretch, share of time on the face, framing changes a minute while talking,
words a minute, how long until the first shot of the thing, seconds of work footage per minute. Each shown next to the range of the reference videos.
- Reuses the study's measurements (scene changes, face detection, transcript), moved into a tool with tests.
- Works on a reference video file too, so the host can add references by dropping a file in a folder (no download, no account).
- Done when: the shark video and two references give the same numbers as the study.

### Phase 1 as built
- `tools/scorecard.py`: measures any video file (picture changes a minute, median shot, longest stretch with no change, time in shots over 15 s, time with a face on screen,
  cuts from one face shot to another a minute, words a minute, first shot with no face) and compares each with the range of the reference videos.
- The references are `skills/youtube-edit/references.json` (eight build videos, measured with this tool) plus any the user adds with `scorecard.py reference <video> [transcript] [label]`,
  kept in `_editor/references/`.
- The Final screen has a "How it compares" card with a Measure button (a job, about 3 min); the result is saved as `<name>.scorecard.json` and says when it was measured on an earlier final.
- What the measuring taught: comparing the face box frame to frame does not measure framing changes (the box jumps on the same shot), so the tool counts cuts with a face on both sides instead.
  The face finder's threshold is a compromise: at 0.4 it finds faces in dogs and machine parts, at 0.7 it misses a host filmed wide; 0.5 is used, so "time with a face" is rough.
- The shark video against the eight: fewer picture changes (9.5 a minute against 11.5 to 33.2), a longer median shot (5.1 s against 1.1 to 4.4) and more time on the face (62% against 28 to 57%);
  inside the range for the longest stretch, cuts between face shots, words a minute and the first shot of the thing.

## Phase 2: film what the edit needs (the biggest gain)
- The outline asks, per section, for work shots: what to show with the hands, a close-up of each part named, an overhead of each step, a screen recording of each program, and one shot of the result for the opening.
  About one shot idea per 10 to 15 s of planned talking at `pace` "fast".
- The Footage screen shows coverage per section: seconds of work footage against seconds of talking, and the missing shots as a checklist the host can take to the bench (it already copies the missing list).
- A one-page filming note in the skill: one overhead camera or phone over the bench running the whole build, a close-up pass at the end of each step, and the finished thing filmed first.
- Done when: a new project's outline lists work shots per section and the Footage screen shows coverage.

## Phase 3: the edit uses everything it has
- Run `pace` "fast" on a real project and fix what breaks (it is only unit-tested now).
- When a talking stretch passes `beat_max_s`, fill it in this order: footage of what is being said, then a graphic (number, label, diagram), then a change of framing (wide, close, offset crop: a "virtual second angle" from one camera).
- Framing on the talking head rotates between two or three crops every 8 to 15 s, never the same crop twice in a row after a cutaway.
- The cold open picks a shot of the result, not only the best line.
- Done when: the scorecard on a real cut lands inside the reference range for picture changes and longest unchanged stretch.

## Phase 4: graphics from templates (quicker, cheaper, consistent)
Not a new graphics engine: HyperFrames already builds good graphics. What is slow and uneven is designing each one from nothing. Add a small set of brand-styled templates that Claude fills in:
- **Number card** (a price, a size, a count), **name label** (a part, a game, a program), **arrow and label on footage**, **step list**, **comparison** (two columns), **recap** (the shark video's rules slide), and the existing pop-ups.
- The graphics plan picks a template and its words; a full custom graphic stays possible for a diagram that teaches.
- A reference sheet in the skill: one still per template from the reference videos and the shark video, so the plan has examples of each kind.
- Done when: a section's graphics build from templates in a fraction of the current time and all match the channel colours and fonts.

## Phase 5: more references, only where they add something
- Five to ten videos from the host's own niche (3D printing, explainers), run through the Phase 1 scorecard, to set the "fast" numbers for this channel instead of maker videos in general.
- If possible, a strong and a weak video from the same kind of channel: the only way to learn what helps rather than what is common.
- More videos like the seven already studied would not change the findings.

## Simplicity rules for all of it
- Every new number goes in a skill file with a default; the host chooses `pace`, nothing else is required.
- No new approval steps: the scorecard and coverage only show, they never block a render.
- One new panel (scorecard), one new column (coverage); everything else changes what the existing buttons produce.

## Sound effects
The host's call (2026-11-04): use effects where they are fun and fit, and stop trying to measure what the reference videos use (a sound classifier could not tell a whoosh from music,
even with the voice taken out). Today a long-form video only plays an effect that a beat names (`audio.sfx`); nothing places them on its own, while shorts have `sfxkit`.
Next step when this comes up: let the long-form edit place effects the way shorts do (a graphic landing, a number card, a reveal of the result, a joke beat; never under a teaching line,
never on every cut), from the files in the SFX folder, with a cap a minute in the skill.

## Not now
- A different graphics engine, multiple cameras (one camera with crops matches four of the seven references), music and sound design (the study could not measure them), loudness changes.
- The real judge is the channel's own retention graph. Reading it into the app is a later step once the scorecard exists.
