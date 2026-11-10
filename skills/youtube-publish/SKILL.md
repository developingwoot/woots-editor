---
name: youtube-publish
description: Prepare a video for publishing: title, description, chapters, thumbnail prompts, and filing the finished video.
---
# Publishing

- **Title**: plain words the viewer would search for, with the promise or the surprise; under 60 characters; no all caps.
- **Description**: the hook in the first 200 characters (it is what shows in search), then chapters, credits, links.
- **Chapters**: from the final render's section starts; the first chapter is at 0:00; each title says what the viewer learns.
- **Thumbnail**: one subject, one short phrase (three words or fewer), high contrast, readable at 168 x 94 pixels.
- Credit other creators whose work appears, with a link.
See `metadata.md` for the fields.

## Titles

Numbers are in `publish.json` (title length, how many options, hook length, number of tags, thumbnail words). Each title makes a promise. Four patterns that work:

- **A result**: what the viewer will be able to do or know ("I fixed the wobble in 10 minutes").
- **A question** the viewer already has ("Why does this keep failing?").
- **A wrong belief** turned over ("Everyone sets this up backwards").
- **A number that matters**, only when it is real and in the video.

Test every title: does the first 30 seconds keep this promise? If not, change the title or the opening, never leave the gap.
The title and the thumbnail are one unit: the thumbnail words add something the title does not say (the stakes, the surprise), they do not repeat it.

## Description and tags

- The first line is for search and for the viewer who has not clicked: the topic in plain words, then why to watch. Nothing before it (no greetings, no links).
- Tags are specific phrases a person would type ("fix 3d print stringing"), a dozen at most; one generic word ("video") adds nothing.
- A pinned comment asks one question the viewer can answer in a sentence.
