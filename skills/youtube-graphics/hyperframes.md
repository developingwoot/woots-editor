# Building a graphic with HyperFrames

HyperFrames renders an HTML page frame by frame (`npx --yes hyperframes@0.8.172 <command>`; needs Node 22 or later and FFmpeg).

- One folder per graphic with an `index.html`. The root div carries `data-composition-id`, `data-start="0"`, `data-duration`, `data-width="1920"`, `data-height="1080"`, `data-fps="30"`.
- Scenes are `class="clip"` divs with `data-start`, `data-duration` and `data-track-index`. Animate with a paused GSAP timeline registered as `window.__timelines[<composition-id>]`.
- Sync to speech: take the anchor (source seconds) from the word times; a beat is local t = source - anchor. Time each animation beat to the word it illustrates.
- Keep a CONFIG block between `// CONFIG:BEGIN` and `// CONFIG:END` (`const CONFIG = {...}` as strict JSON): `beats`, `beatWords`, `clips`, `text`, `roles`, `pos`, `params`. The timeline uses only `B.<beat>` and offsets from beats, so moving a beat moves its group. HyperFrames reads `data-start`/`data-duration` and font glyphs from the static markup, so the markup mirrors CONFIG.
