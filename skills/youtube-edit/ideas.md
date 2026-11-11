# B-roll and on-screen text ideas

Suggestions for the rough cut. The host says yes or no to each one; nothing goes into the cut without a yes. Few and good beats many and weak.

## B-roll

- Suggest a cutaway only where the picture would SHOW what is being said: the part, the setting, the result, the screen. Never decoration.
- Not where the host's face or hands carry the moment (a reaction, a joke, the hook), and not on a clip that already has B-roll.
- A cutaway lasts at most `broll_max_s` seconds (rough-cut.json).
- Three kinds, best first:
  - `footage`: a moment of the host's own footage from footage.txt (its recording and second). Only recordings and times that are in footage.txt.
  - `web`: a public page that shows the thing (the product page, the spec sheet, the official docs). Give the address, and a few words that are on the page to scroll to.
  - `film`: nothing the host has fits and it is worth filming next time (a pickup). Say exactly what to film in one short line.

## On-screen text

- `correction`: the host misspoke or got a fact wrong (a wrong number, a wrong name, a mis-said word). The text is the correct version, starting with an asterisk, in the host's voice: "*0.4 mm nozzle, not 0.6".
  Use the fact check (factcheck.json) and the script (script.md) to find them. Never "correct" the host's opinion.
- `detail`: a short fact a viewer would want on screen while the host talks: a price, a model number, a setting, a measurement, a link to find later. Only when it is not already said clearly.
- At most about 8 words. Shown for about `text_card_s` seconds (rough-cut.json) near the bottom left of the picture.
- Not on top of a graphic, and never two on one clip.
