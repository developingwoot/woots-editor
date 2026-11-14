# Changelog

What changed in each release, written for the people who use the app. Newest first.

## Unreleased

- Changed: nothing automatic covers you showing something. A cutaway is left out where you point at the thing ("these rods right here", "you can see") or where the talking picture already shows your hands at work or the screen you are talking over, whichever step placed it; cutaways you or a note placed stay. Quiet footage of the same recording is now used only over a talking head, and only from within 20 seconds of the very words it plays over (`quiet_near_s`, was 90 seconds from the beat). The version says how many cutaways were left out for this.
- New: when the app's starter skills get a rule or a number that your own copy of a skill does not have, the home screen says so, lists them, and adds them with one button. Nothing you wrote is changed, and the file as it was is kept next to it as `.bak`. Before this, a new rule never reached Claude for anyone with their own copy of the skill.
- New: when you talk while working (an unboxing, a build), the rough cut uses what you were doing between your sentences as B-roll. A long beat with no cutaway gets the quiet footage of its own recording nearest to it, never a moment where something is said and never you just facing the camera. A recording with almost nothing said (the machine running) goes over the beats whose words match what its frames show, in order. On the xTool video the B-roll went from 39 s to 131 s of a 5-minute cut.
- Fixed: a long hands-on recording where the host talks while working (an hour of setting up a machine, about 1,400 words) was taken for a screen recording with some talk, because its words were counted over its whole length. A recording with at least `talk_min_words` (400) words now counts as talking at any rate. When no recording has enough talking, the rough cut stops at once and says which recordings were left out and why, instead of going on to a cold open and a cut that fail on an empty plan.

- Added: each video card on the home screen has a "⋯" menu with Archive and Delete. Archive on a finished video (final render, title and footage folder) runs the Final screen's Finish and archive; on any other video it deletes, for good, the renders, sound files and caches the app can make again, keeps every plan and any final render, and moves the video to an "Archived" list (Unarchive brings it back). Finished videos are listed there too. Delete, after a confirmation, moves the video's work folder to a trash folder in the workspace instead of erasing it; the footage folder is never touched.

- Fixed: chapter names in the description all repeated the section title. Claude now names the chapters from what is said (it is given every place a chapter can start with the words said there); the times are moved onto real cuts, at least 10 seconds apart, and the section names are used only if Claude gives fewer than 3 usable chapters.

- Added: a note can now take an on-screen text that is already there off the screen, or change its words or how long it stays (before, Claude could only add new text and had to give up on notes like "remove that caption" or "shorten it").

- Fixed: a change in how the app draws (the caption and blur fixes) did not reach a preview whose sections were already built: only a changed plan rebuilt a section. Sections with a caption, graphic or blur over a trimmed clip are now rebuilt once by "Make preview N again".

- Fixed: in the preview and the final a blur or black box could let the unblurred picture show for a frame at a jump cut, a couple of times. It now carries straight through the cuts, like captions do. The rough cut was not affected.

- Fixed: in the final, the whoosh of a web page (or any sound effect) could play on long after the page was gone, over and over, when its sound file was long (one swish file is 22 seconds). The rough cut and the preview cut a sound at the end of its clip; the final now does too.

- Fixed: the music stopped part-way through the preview and the final. A beat you trimmed plays as several pieces, and only the first piece found the beat's music, so the song ended after it and the next beat started it again (or nothing did). The song now runs under every piece.

- Fixed: the Preview and Rough cut screens failed to load ("expected bytes") when a version had been recorded with no video, as the live-editor trial does. Such versions are now left out, and the next one is numbered after them.

- A new rough cut or preview can be made with no notes: the button reads "Make cut 2 again" and makes the plan as it is now. Before, it asked for a note first, and typing "render the rough cut" as a note failed because notes are for changes.

- Fixed: a caption or graphic that runs across jump cuts blinked off for a frame at each cut. The cut points are snapped to the speech, so a piece could end a few frames after the caption's share of it. Captions, on-screen text and built graphics now carry straight through, in the rough cut, the preview and the final.

- The voice is now evened out over time. The recording itself drifts by up to 10 dB over tens of seconds (you lean in, speak softer); the app no longer adds swings of its own, but it left yours. A slow, speech-only level curve (about 8 seconds, never more than 8 dB, nothing inside a sentence) now brings those stretches closer: on the Bambu recording the spread of the speech level fell from 2.6 to 1.2 dB. The rough cut, the preview and the final use it. Make a new rough cut to hear it.

- Fixed: the voice got louder and quieter for no reason. The last loudness step rode the volume up and down as it went (a 12 dB difference came out as 4 dB). The rough cut, the preview, the final and shorts with music now get one gain for the whole video, and a limiter that only catches the odd peak.

- Fun moments can come more often (up to 3 a minute, 4 seconds apart; they were 1.5 a minute, 8 seconds apart), and teaching moments are spaced out: Claude keeps them at least 60 seconds apart, the one a newcomer needs more where two fall closer. Both are in the youtube-graphics skill's graphics.json.

- The Preview screen has a "Make the preview" button for the first preview: it builds the graphics (the fun moments and teaching moments you ticked too) and puts the whole video together. Before, there was no way to start it from this screen, so ticked fun moments seemed to do nothing.

- Fixed: after a few rough cuts in a row the bar at the top could stay on "Making the rough cut" when the cut was done. Each old cut's player kept downloading its video in the background and took up the browser's connections to the app; old players now stop, and the bar's check gives up after 8 seconds and asks again.

- Blur on the rough cut: pause on the first frame where a name, an address or a screen shows, draw a box over it, and the app follows it through the clip (the camera can move). The box shows over the player so you can check it; where it drifts, pause there and use "Fix from here". Choose a blur or a black box, and "Ends here" stops it early. The rough cut, the preview and the final all hide it. A note can ask for one too ("blur my username here"); you then place the box.
- Frame by frame: the comma and full stop keys (or the buttons under the player) step one frame back or on, and the time under the player shows the frame.
- Notes can take a few words out of a clip ("cut 'or at least not right now' at 2:05"), even a clip you marked good, and can lay any recording from the footage folder over the picture ("put the timelapse here", sped up if you like): its own sound is not needed.
- The rough cut now plays your sound effects (and the whoosh of a transition) and shows the graphics that are already built for the current plan. A graphic not built yet is still left out: the rough cut never waits for one.
- Notes can ask for background music ("put some calm music under the intro"): Claude now gets your Music folder and picks a track. The rough cut now plays the music too (it used to be heard only from the preview on), under your voice and ducked while you talk, like the preview and the final.

- B-roll from a web page: on any clip of the rough cut, paste a page's address (and the words to highlight) and the page is captured as a short clip over that clip, scrolling to the words or as a still with a slow zoom. Only public pages; the address goes into the description's credits.
- Show the source: the fact check now keeps the words on each source page that back a claim. For a claim it found right, "Show the source" captures that page, scrolled to those words and highlighted, over the clip where you say it.
- Transitions: a web page now slides in with a whoosh and slides out again; other B-roll stays a plain cut. Settings has a Transitions section (cut, dissolve, slide, slide up, whip, pop, flash), the web page panel can pick one for that page, and you can add your own presets in the youtube-edit skill's transitions.json. The sound comes from your sound effects folder.
- Stingers: four short animations in your colours, font and channel name (brand sweep, stripes, circle, channel name) that cover the cut into and out of a cutaway. Make them once under Settings > Transitions (about a minute, on your computer); they are made again when your brand changes. Add your own templates in the youtube-graphics skill's stingers folder.
- Notes can ask for a web page ("go to this address here"), a sound effect ("a negative sound when I say…") or another camera angle ("use the other shot with this clip's sound"): the app does them itself. Another angle is lined up with your take by its sound. When Claude cannot apply a note, the message now says why.
- B-roll and on-screen text ideas on the rough cut: "Ask Claude for ideas" suggests shots from your own footage, web pages, shots to film next time (a tick adds them to the shoot plan's pickups), and on-screen text: a correction where you misspoke ("*0.4 mm nozzle, not 0.6", found with the fact check and your outline) or a short detail (a price, a model number). A tick says yes and the next cut shows it; you can change the words first.
- Fixed: the times of ideas, teaching and fun moments, and of what a note asks for (a web page, a sound, on-screen text) now match the rough cut you watched. They were taken from the plan's estimates, which still counted clips the cut had taken out.
- On-screen text: misspoke? Pause the rough cut where it happens, type the right words and press Add at the playhead. The text shows for a few seconds in a box in your colours and font, in the rough cut already. A note works too ("put *0.4 mm on screen here").
- Notes can be about the whole video ("too long, be pickier").
- New recordings can be read on the Footage screen without making a cut.

## 0.1.0 (first public release)

- The whole workflow in one local app: Outline, Footage, Rough cut, Preview, Final and Shorts.
- The app answers on your computer only. Other computers on your network cannot reach it.
- Every change to a plan is recorded: Undo for ten seconds after a change, and a History list for each video.
- Check the facts, choose music, and export the cut for DaVinci Resolve from the screens of each video.
- Models you download are pinned to one tested version.
- Windows 10 and 11 only for now.
