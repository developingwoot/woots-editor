# Changelog

What changed in each release, written for the people who use the app. Newest first.

## Unreleased

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
