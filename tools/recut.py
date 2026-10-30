"""Rough cut from whole recordings (ADR 0009): the video is the talking recordings in outline order, each with its mistakes taken out.

The host's published CAD video was built exactly like that (checked against the footage): Intro_3 (the last of three intro takes), then TinkerCAD.mkv from its
first complete take to the end, Onshape.mkv, Fusion.mkv ..., Plasticity 2.mkv (not Plasticity.mkv), Outro_2.mkv. Matching one take per outline line (the first
design) lost the flow: lines without a take left holes, one recording was cut up between different programs, an early take could win.

  plan(work, name) -> {"recordings": [{rel, series, take, position, heading, keep_words, kept_s, ...}], "left_out": [{rel, why}]}
  build_beats(work, name) -> writes <name>.beatmap.json (a backup of the old one is kept) with one beat per ~8-25 s of kept speech
  place_broll(work, name) -> puts the chosen footage for each shot idea over the beat where that line is said

What counts as a talking recording: at least MIN_WORDS words said at MIN_RATE words a second or more (screen recordings with a few words do not).
Which one of several: the latest of a numbered series (Intro_1/2/3, Plasticity and Plasticity 2); a recording whose words are mostly inside another is a repeat.
Mistakes taken out: a take abandoned before a restart, a take restarted at once (its opening words come again), a phrase said again within a few seconds,
dead air. Everything else stays, in recording order. Python stdlib only.
"""
import json
import os
import re
import time
from pathlib import Path

import beatmap
import brolllib
import clipmap
import config
import footage_cfg
import locks
import tags
import outline
import shotmatch
import silence
import skillrules

WORK = config.WORK
MIN_WORDS, MIN_RATE = 60, 0.8   # set from the skill by reload_rules(): words, and words a second over the whole recording
SAME_GRAMS = 0.25                # share of a recording's 4-word runs found in another one, or
SAME_PLACE = 3                   # lines apart in the outline for two numbered takes to be the same thing
SAME_CONTAINED = 0.6             # share of the SHORTER recording's content words found in the other: a retake of a part of it (a short intro attempt, then the long recording that starts again)
SAME_WORDS = 0.45                # share of their content words in common: the two are takes of the same thing
REPEAT_N, REPEAT_WORDS, REPEAT_S = 4, 40, 20.0
EARLY_SHARE = 0.6
CHUNK_MIN, CHUNK_MAX = 15.0, 30.0  # s of kept speech per beat: a visible change every 15-30 s (youtube-edit)
MIN_PIECE_S = 3.0                # no cut leaves a piece on screen for less than this (the creator, 2026-10-29)
SEGUE = re.compile(r"next up|first up|last on the list|up next|moving on", re.I)
SAID_TWICE, SAID_TWICE_FAR, SAID_TWICE_S = 0.5, 0.7, 60.0   # share of the shorter sentence's content words found in another sentence within this many seconds: said twice
BROLL_MAX = 8.0
SILENCE_PAD_S, SILENCE_LEAD_S = 0.3, 0.1      # of a cut silence this much stays after the speech (the quiet end of a word) and before the next word
MAX_PAUSE_S = 0.5            # a silence longer than this is cut out (set from the skill)

SERIES_RE = re.compile(r"^(.*?[A-Za-z])[\s_\-]*(\d{1,2})$")
INTRO_OUTRO = ("intro", "outro")


def reload_rules():
    """Take the numbers from the youtube-edit skill (rough-cut.json). Tests override a few with environment variables (their recordings are 3 s long)."""
    global MIN_WORDS, MIN_RATE, REPEAT_N, REPEAT_WORDS, REPEAT_S, CHUNK_MIN, CHUNK_MAX, MIN_PIECE_S, SAID_TWICE, SAID_TWICE_FAR, SAID_TWICE_S, BROLL_MAX, MAX_PAUSE_S, BROLL_MIN_BEAT_S, SAME_CONTAINED
    r = skillrules.rules()
    MIN_WORDS, MIN_RATE = int(os.environ.get("WOOTS_MIN_WORDS", r["min_words"])), r["min_words_per_s"]
    REPEAT_N, REPEAT_WORDS, REPEAT_S = r["repeat_phrase_words"], r["repeat_phrase_within_words"], r["repeat_phrase_within_s"]
    CHUNK_MIN, CHUNK_MAX = r["beat_min_s"], r["beat_max_s"]
    MIN_PIECE_S = float(os.environ.get("WOOTS_MIN_PIECE", r["min_piece_s"]))
    SAID_TWICE, SAID_TWICE_FAR, SAID_TWICE_S = r["repeat_sentence_share"], r["repeat_sentence_far_share"], r["repeat_sentence_s"]
    BROLL_MAX = r["broll_max_s"]
    MAX_PAUSE_S = r["max_pause_s"]
    BROLL_MIN_BEAT_S = r["broll_min_beat_s"]
    SAME_CONTAINED = r["retake_share"]


reload_rules()


# ----------------------------------------------------------------------------- which recordings
def series_of(rel: str) -> tuple[str, int]:
    """('intro', 3) for Intro_3.mkv, ('plasticity', 2) for 'Plasticity 2.mkv', (the whole name, 1) for anything else."""
    stem = Path(rel).stem
    m = SERIES_RE.match(stem)
    if m:
        return footage_cfg.norm_name(m.group(1)), int(m.group(2))
    return footage_cfg.norm_name(stem), 1


def is_talking(an: dict) -> bool:
    dur = float(an.get("dur") or 0)
    return (an.get("words") or 0) >= MIN_WORDS and dur > 0 and (an["words"] / dur) >= MIN_RATE and bool(an.get("list"))


def _grams(tokens: list, n: int = REPEAT_N) -> set:
    return {tuple(tokens[i:i + n]) for i in range(len(tokens) - n + 1)}


def _tokens(an: dict) -> list:
    return [t for w in an.get("list", []) for t in clipmap.tokens_of(w[0])]


def choose_recordings(analysis: dict, cfg: dict, pos: dict | None = None, n_lines: int = 0) -> tuple[list, list]:
    """(talking recordings to use, [{rel, why}] for the ones left out). `pos` = {rel: place in the outline}: numbered takes of the same name
    that belong in the same place are takes of one thing (Intro_1/2/3, Outro_1/2), whatever the words."""
    left, talk = [], {}
    for rel, an in sorted(analysis.items()):
        if footage_cfg.is_ignored(cfg, rel):
            continue
        if is_talking(an):
            talk[rel] = an
        elif (an.get("words") or 0) >= 20:
            left.append({"rel": rel, "why": "too little speech to be a talking recording"})
    tol = min(SAME_PLACE, n_lines // 10)                 # a short outline: only the very same place
    sets = {rel: set(_content(" ".join(w[0] for w in talk[rel]["list"]))) for rel in talk}
    grams = {rel: _grams(_tokens(talk[rel])) for rel in talk}

    def same_thing(a: str, b: str) -> bool:
        """Two recordings that say much the same words: takes of the same thing."""
        ga, gb = grams[a], grams[b]
        inter = len(ga & gb)
        contain = max(inter / len(ga) if ga else 0, inter / len(gb) if gb else 0)
        jac = len(sets[a] & sets[b]) / max(1, len(sets[a] | sets[b]))
        if pos is not None and series_of(a)[0] == series_of(b)[0] and abs(pos.get(a, 0) - pos.get(b, 99)) <= tol:
            return True
        inside = len(sets[a] & sets[b]) / max(1, min(len(sets[a]), len(sets[b])))
        return contain >= SAME_GRAMS or jac >= SAME_WORDS or inside >= SAME_CONTAINED

    keep: list = []
    for rel in sorted(talk, key=lambda r: (series_of(r)[1], len(grams[r])), reverse=True):      # the later (or longer) one is looked at first
        twin = next((o for o in keep if same_thing(rel, o)), None)
        if twin:
            left.append({"rel": rel, "why": f"an earlier take: {Path(twin).name} says the same and comes later" if series_of(twin)[1] > series_of(rel)[1]
                         else f"mostly said again in {Path(twin).name}"})
        else:
            keep.append(rel)
    return sorted(keep), left


# ----------------------------------------------------------------------------- where each belongs in the outline
STOP = clipmap.STOP


def _content(s: str) -> list:
    return [t.replace("'", "") for t in clipmap.tokens_of(s) if t.replace("'", "") not in STOP and len(t) > 1]


class Likeness:
    """idf-weighted word likeness between texts (0..1), over a fixed set of documents."""

    def __init__(self, docs: list):
        self.df: dict = {}
        for d in docs:
            for t in set(_content(d)):
                self.df[t] = self.df.get(t, 0) + 1
        self.n = max(1, len(docs))

    def vec(self, text: str, boost: dict | None = None) -> dict:
        v: dict = {}
        for t in _content(text):
            v[t] = v.get(t, 0) + 1
        for t, w in (boost or {}).items():
            v[t] = v.get(t, 0) + w
        v = {t: c * (1 + (self.n / (1 + self.df.get(t, 0))) ** 0.5) for t, c in v.items()}
        norm = sum(x * x for x in v.values()) ** 0.5
        return {t: x / norm for t, x in v.items()} if norm else {}

    @staticmethod
    def cos(a: dict, b: dict) -> float:
        return sum(x * b.get(t, 0) for t, x in a.items())


def position_of(rel: str, an: dict, lines: list, like: Likeness) -> tuple[float, dict]:
    """(place in the outline, the line it is most like): intro first, outro last; the others by the spoken line their words (and file name) fit best."""
    key, _ = series_of(rel)
    if key in INTRO_OUTRO:
        return (-1.0 if key == "intro" else float(len(lines) + 1)), (lines[0] if key == "intro" else lines[-1]) if lines else {}
    name_words = {t: 6 for t in _content(re.sub(r"[_\-]", " ", Path(rel).stem))}
    text = " ".join(w[0] for w in an.get("list", []))
    rv = like.vec(text, name_words)
    scores = [like.cos(rv, like.vec(ln["said"])) for ln in lines]
    top = max(scores, default=0.0)
    best = next((i for i, sc in enumerate(scores) if top > 0 and sc >= EARLY_SHARE * top), None)     # the earliest line nearly as good: a tier-list recap mentions every program
    return (float(best) if best is not None else float(len(lines))), (lines[best] if best is not None else {})


# ----------------------------------------------------------------------------- mistakes taken out
def _tok_at(words: list) -> tuple[list, list]:
    toks, widx = [], []
    for i, w in enumerate(words):
        for t in clipmap.tokens_of(w[0]):
            toks.append(t)
            widx.append(i)
    return toks, widx


def restart_span(words: list, toks: list, widx: list, first: dict, j: int, i: int) -> tuple:
    """(first word, end word) to drop for a phrase said again at token i that was said at token j. Normally the span from j to i. But when a sentence between them
    begins again like an earlier sentence (a clean restart of the whole passage: "Now the G-code viewer, I must say..." ... "The G-code viewer is an area..."), the restart
    is the telling that stays: everything from the earlier sentence it repeats up to the restart goes, and what follows the restart is kept."""
    for k in range(j + 1, i):
        w = widx[k]
        if k == 0 or w == widx[k - 1] or not re.search(r"[.?!]$", words[w - 1][0]):
            continue                                                              # a restart begins a sentence
        g = tuple(toks[k:k + REPEAT_N])
        p = first.get(g)
        if p is None or p >= j or k - p > 2 * REPEAT_WORDS or words[w][1] - words[widx[p]][1] > 2 * REPEAT_S or sum(1 for t in g if t not in LOOSE_WORDS) < 2:
            continue
        a = widx[p]
        while a > 0 and not re.search(r"[.?!]$", words[a - 1][0]):                # back to the start of that sentence
            a -= 1
        if SEGUE.search(" ".join(x[0] for x in words[a:w])):
            return widx[j], widx[i]
        return a, w
    return widx[j], widx[i]


LOOSE_WORDS = {"the", "and", "you", "can", "that", "this", "for", "with", "are", "was", "have", "has", "your", "but", "not", "its", "i", "it", "a", "to", "of", "in", "is", "on", "so", "if"}


def repeated_phrase_drops(words: list) -> set:
    """Word positions to drop: when the same REPEAT_N words come again within REPEAT_WORDS words and REPEAT_S seconds, everything from the first
    attempt up to the second one is a stumble or a retake ('And if I'm doing something for CAD, anything I use, I'll use anything but plasticity.
    And if I'm doing something with CAD, I'm sorry...'). The later one stays. Takes and pauses do not matter: a retake after a pause is the same thing."""
    toks, widx = _tok_at(words)
    first: dict = {}
    for k in range(len(toks) - REPEAT_N + 1):
        first.setdefault(tuple(toks[k:k + REPEAT_N]), k)
    seen: dict = {}
    drop: set = set()
    i = 0
    while i < len(toks) - REPEAT_N + 1:
        g = tuple(toks[i:i + REPEAT_N])
        j = seen.get(g)
        if j is not None and i - j <= REPEAT_WORDS and words[widx[i]][1] - words[widx[j]][1] <= REPEAT_S and widx[i] > widx[j]:
            start, end = restart_span(words, toks, widx, first, j, i)
            drop.update(range(start, end))
            seen = {}
        seen[g] = i
        i += 1
    return drop


def repeated_sentence_drops(words: list, skip: set = frozenset()) -> set:
    """Word positions of a sentence said again in other words within SAID_TWICE_S ('...I was able to design the scraper in about 20 minutes, which is
    fantastic.' then 'When you consider in 20 minutes, I had a functional part, that's fantastic.'). The first goes, the later one stays."""
    sents, cur = [], []
    for i, w in enumerate(words):
        if i in skip:
            continue
        cur.append(i)
        if re.search(r"[.?!]$", w[0]) or len(cur) >= 40:
            sents.append(cur)
            cur = []
    if cur:
        sents.append(cur)
    info = [(ix, set(_content(" ".join(words[i][0] for i in ix))), words[ix[0]][1], words[ix[-1]][2]) for ix in sents]
    drop: set = set()
    for a in range(len(info)):
        ia, sa, _, ea = info[a]
        if len(sa) < 5 or a == 0 or SEGUE.search(" ".join(words[i][0] for i in ia)):                  # the opener that tells the viewer which program comes next stays
            continue
        for b in range(a + 1, len(info)):
            ib, sb, tb, _ = info[b]
            if tb - ea > SAID_TWICE_S:
                break
            if len(sb) < 5:
                continue
            shared = len(sa & sb)
            if shared >= 3 and shared / min(len(sa), len(sb)) >= (SAID_TWICE if b == a + 1 else SAID_TWICE_FAR):   # said again right away, or built on later
                drop.update(ia)
                break
    return drop


STAMMER_OK = {"had", "that", "very", "really", "so", "no"}          # words that are said twice on purpose
ORPHAN_WORDS = 2


def stammer_drops(words: list, drop: set) -> set:
    """A word said twice in a row ('work work', 'the the') loses its first copy; a scrap of one or two words left beside what was cut (the 'work.'
    that was left over from a restarted sentence) goes too."""
    out = set()
    norm = lambda w: re.sub(r"[^a-z0-9']", "", w.lower())
    for i in range(1, len(words)):
        if i - 1 not in drop and i not in drop and norm(words[i][0]) and norm(words[i][0]) == norm(words[i - 1][0]) \
                and norm(words[i][0]) not in STAMMER_OK and words[i][1] - words[i - 1][2] < 0.6:
            out.add(i - 1)
    gone = drop | out
    i = 0
    while i < len(words):
        if i in gone:
            i += 1
            continue
        j = i
        while j + 1 < len(words) and j + 1 not in gone and words[j + 1][1] - words[j][2] < 0.5:
            j += 1
        if j - i + 1 <= ORPHAN_WORDS and ((i - 1 in gone) or (j + 1 in gone)) and not SEGUE.search(" ".join(w[0] for w in words[i:j + 1])):
            out.update(range(i, j + 1))
        i = j + 1
    return out


def cleaned(words: list, restart_at: list = ()) -> list:
    """[(kept word positions of one stretch, [source-second ranges])] in order. A stretch ends at a pause over PAUSE_SPLIT or where words were dropped.
    No range is shorter than MIN_PIECE_S; a stretch that short joins the one before it when only a pause lies between them."""
    drop = repeated_phrase_drops(words)
    drop |= repeated_sentence_drops(words, drop)
    drop |= stammer_drops(words, drop)
    parts, cur = [], []
    for i, w in enumerate(words):
        if i in drop:
            if cur:
                parts.append(cur)
                cur = []
            continue
        if cur and w[1] - words[cur[-1]][2] > clipmap.PAUSE_SPLIT:
            parts.append(cur)
            cur = []
        cur.append(i)
    if cur:
        parts.append(cur)
    joined = []
    for idx in parts:
        short = words[idx[-1]][2] - words[idx[0]][1] < MIN_PIECE_S
        if short and joined and not any(k in drop for k in range(joined[-1][-1] + 1, idx[0])):
            joined[-1] = joined[-1] + idx
        else:
            joined.append(idx)
    kept = []
    for idx in joined:                                          # a fragment under MIN_PIECE_S between stumbles would be a cut on screen for a moment: it goes (a segue stays)
        if words[idx[-1]][2] - words[idx[0]][1] < MIN_PIECE_S and not SEGUE.search(" ".join(words[i][0] for i in idx)):
            continue
        kept.append(idx)
    out = []
    for idx in kept:
        for piece in split_long(words, idx):
            out.append((piece, beatmap.keep_from_idx(words, piece, dead=MAX_PAUSE_S)))
    return out


def split_long(words: list, idx: list) -> list:
    """A stretch longer than CHUNK_MAX s is cut at its longest pause between CHUNK_MIN and CHUNK_MAX s from its start, again as needed:
    the pieces follow each other in the recording, so the picture does not jump but the cut has a place to change the shot."""
    out = []
    while words[idx[-1]][2] - words[idx[0]][1] > CHUNK_MAX:
        t0 = words[idx[0]][1]
        window = [k for k in range(1, len(idx)) if CHUNK_MIN <= words[idx[k]][1] - t0 <= CHUNK_MAX
                  and words[idx[-1]][2] - words[idx[k]][1] >= MIN_PIECE_S]
        if not window:
            break
        k = max(window, key=lambda k: words[idx[k]][1] - words[idx[k - 1]][2])
        out.append(idx[:k])
        idx = idx[k:]
    out.append(idx)
    return out


# ----------------------------------------------------------------------------- the plan
def spoken_lines(work: str, name: str) -> list:
    return outline.speech_lines(outline.load(work, name))


def plan(work: str, name: str) -> dict:
    cfg = footage_cfg.with_titles(clipmap.read_json(WORK / work / f"{name}.footage.json", {}) or {}, work, name)
    analysis = cfg.get("analysis") or {}
    if not analysis:
        raise ValueError("no recordings are read yet")
    lines = spoken_lines(work, name)
    talk = [r for r, an in analysis.items() if not footage_cfg.is_ignored(cfg, r) and is_talking(an)]
    like = Likeness([ln["said"] for ln in lines] + [" ".join(w[0] for w in analysis[r].get("list", [])) for r in talk])
    where = {r: position_of(r, analysis[r], lines, like) for r in talk}
    use, left = choose_recordings(analysis, cfg, {r: v[0] for r, v in where.items()}, len(lines))
    recs = []
    for rel in use:
        an = analysis[rel]
        pos, ln = where[rel]
        parts = cleaned(an["list"], an.get("restart_at") or [])
        kept_s = sum(b - a for _, keep in parts for a, b in keep)
        recs.append({"rel": rel, "series": series_of(rel)[0], "take": series_of(rel)[1], "position": pos, "heading": (ln or {}).get("heading") or "",
                     "parts": parts, "kept_s": round(kept_s, 1), "dur": an.get("dur")})
    recs.sort(key=lambda r: (r["position"], r["rel"]))
    return {"recordings": recs, "left_out": left}


# ----------------------------------------------------------------------------- the beat map
def _chunks(parts: list) -> list:
    """Neighbouring kept takes joined into groups of about CHUNK_MIN..CHUNK_MAX seconds: [[(idx, keep), ...], ...]."""
    out, cur, dur = [], [], 0.0
    for idx, keep in parts:
        d = sum(b - a for a, b in keep)
        if cur and (dur >= CHUNK_MIN or dur + d > CHUNK_MAX):
            out.append(cur)
            cur, dur = [], 0.0
        cur.append((idx, keep))
        dur += d
    if cur:
        out.append(cur)
    if len(out) > 1 and sum(sum(b - a for a, b in k) for _, k in out[-1]) < MIN_PIECE_S:       # a last beat of a few seconds belongs to the one before
        out[-2] += out.pop()
    return out


def build_beats(work: str, name: str) -> dict:
    pl = plan(work, name)
    cfg = clipmap.read_json(WORK / work / f"{name}.footage.json", {}) or {}
    analysis = cfg.get("analysis") or {}
    beats = []
    sp = silence.path(work, name)
    cache = clipmap.read_json(sp, None) or {}
    for rec in pl["recordings"]:
        words = analysis[rec["rel"]]["list"]
        quiet = silence.of_recording(work, name, cfg.get("folder", ""), rec["rel"], cache)
        for chunk in _chunks(rec["parts"]):
            idx = sorted({i for ix, _ in chunk for i in ix})
            keep = []
            for _, kr in chunk:
                keep += [list(r) for r in kr]
            tight = silence.cut_silences(keep, quiet, MAX_PAUSE_S, SILENCE_PAD_S, SILENCE_LEAD_S, words)       # the sound says how long a pause is; the word times do not
            if tight and sum(b - a for a, b in tight) >= 0.5 * sum(b - a for a, b in keep):
                keep = tight
            first, last = words[idx[0]], words[idx[-1]]
            sid = clipmap.span_id(rec["rel"], first[1])
            ar = {"rel": rec["rel"], "in": keep[0][0], "out": keep[-1][1], "dur": round(sum(b - a for a, b in keep), 2), "span": sid,
                  "span_in": keep[0][0], "span_out": keep[-1][1], "keep": keep, "trim_by": "auto",
                  "words": [w for w in words if w[2] >= keep[0][0] - 2 and w[1] <= keep[-1][1] + 2]}
            said = beatmap.kept_text(words, keep)
            beats.append(beatmap.blank_beat(f"B{len(beats) + 1:02d}", rec["heading"], [], said, ar, ar["dur"], False, []))
    clipmap.write_json(sp, cache)
    beatmap.retime(beats)
    p = beatmap.path_of(work, name)
    old = clipmap.read_json(p, None)
    if old:
        clipmap.write_json(p.with_name(p.name + ".bak"), old)
    data = {"version": 1, "generated": time.strftime("%Y-%m-%dT%H:%M:%S"), "mode": "recordings", "beats": beats, "orphans": [],
            "changes": [{"t": time.strftime("%Y-%m-%dT%H:%M:%S"), "who": "app", "what": "built from whole recordings",
                         "recordings": [r["rel"] for r in pl["recordings"]]}]}
    clipmap.write_json(p, data)
    return {"beats": len(beats), "recordings": [r["rel"] for r in pl["recordings"]], "left_out": pl["left_out"],
            "seconds": round(sum(b["dur"] for b in beats), 1)}


# ----------------------------------------------------------------------------- b-roll over the speech
BROLL_MIN_LIKE = 0.12
BROLL_MIN_BEAT_S = 12.0      # a beat this long or longer gets a cutaway (no change of picture for more than the beat is too long)


def place_broll(work: str, name: str, shots: dict, plan_rows: list) -> int:
    """Each shot idea that has chosen footage goes over the beat where its spoken line is said (the beat whose words are most like the line).
    One cutaway per beat; cutaways placed by hand stay. `shots` = shotmatch.load, `plan_rows` = shotmatch.plan."""
    bp = beatmap.path_of(work, name)
    data = clipmap.read_json(bp, None)
    if not data:
        return 0
    lines = {ln["id"]: ln for ln in spoken_lines(work, name)}
    locked = locks.beat_ids(work, name, data)                                  # beats with a sentence the creator marked good keep their picture
    beats = [b for b in data["beats"] if b.get("aroll") and not b.get("skip") and not b.get("vo") and b["id"] not in locked]
    like = Likeness([b["said"] for b in beats] + [ln["said"] for ln in lines.values()])
    bv = {b["id"]: like.vec(b["said"]) for b in beats}
    for b in beats:
        broll = b.setdefault("on_screen", {}).setdefault("broll", [])
        if not any(not x.get("auto") for x in broll):
            broll[:] = []
    claimed: dict = {}
    jp = brolllib.paths(work, name)[1]
    known = shotmatch.programs(json.loads(jp.read_text(encoding="utf-8")).get("clips", {})) if jp.exists() else set()
    progs = beat_programs([b for b in beats if not str(b.get("id", "")).startswith("H")], known)
    for s in plan_rows:
        e = shots.get(s["key"])
        ln = lines.get(s["speech"])
        if not e or not e.get("chosen") or not ln:
            continue
        hit = e["chosen"]
        lv = like.vec(ln["said"])
        ranked = sorted(((like.cos(lv, bv[b["id"]]), b) for b in beats if b["id"] not in claimed), key=lambda t: -t[0])
        for sc, b in ranked:
            if sc < BROLL_MIN_LIKE:
                break
            if any(not x.get("auto") for x in b["on_screen"]["broll"]):
                continue
            named = {progs[b["id"]]} if progs.get(b["id"]) else set()
            if named and "tierlist" not in shotmatch._norm(hit["rel"]) and not shotmatch.of_program(hit["rel"], named, hit["what"] if hit.get("tagged") else ""):            # the beat is about Shapr3D: not a Fusion clip
                continue
            room = max(1.0, float(hit.get("dur") or BROLL_MAX) - float(hit["t"]))
            dur = round(min(BROLL_MAX, b["dur"], room), 2)
            if dur < MIN_PIECE_S:
                continue
            b["on_screen"]["broll"].append({"file": hit["rel"], "in": float(hit["t"]), "dur": dur, "at": 0.0, "why": hit["what"][:120], "auto": True})
            claimed[b["id"]] = True
            break
    clipmap.write_json(bp, data)
    return len(claimed)


# ----------------------------------------------------------------------------- b-roll from the program's own screen recordings
COVER_AFTER_S = 3.0          # the speaker is seen first; the cutaway starts this far into a beat


def beat_programs(beats: list, known: set) -> dict:
    """{beat id: the program it is about} ("" when no one program). A recording starts on the program it is filed under (Fusion_2.mkv -> fusion) and stays on
    it until a beat introduces another ('Next up on the list is Shaper 3D', or a program named in two sentences and no other): a passage about Shapr3D said
    inside TinkerCAD.mkv is Shapr3D until the next one is introduced. The intro and outro recordings are about no program."""
    out, state, last_rel = {}, "", None
    for b in beats:
        rel = b["aroll"]["rel"]
        if rel != last_rel:
            stem = shotmatch._norm(rel)
            state = next((k for k in sorted(known, key=len, reverse=True) if k in stem), "")
            last_rel = rel
        said = b.get("said", "")
        named = shotmatch.named_programs(said, known)
        spoken = re.split(r"(?<=[.?!])\s+", said)
        introduced = [shotmatch.named_programs(x, known) for x in spoken if SEGUE.search(x)]
        introduced = [next(iter(x)) for x in introduced if len(x) == 1]          # "Next up on the list is Shaper 3D": the sentence names the one it introduces
        if introduced:
            state = introduced[-1]
        elif len(named) == 1:
            n = next(iter(named))
            if n != state and ((not state and not any(k in shotmatch._norm(rel) for k in INTRO_OUTRO)) or sum(shotmatch.named_programs(x, known) == {n} for x in spoken) >= 2):
                state = n
        out[b["id"]] = state
    return out


DULL = re.compile(r"repositor|github|readme|source code|code editor|text editor|file list|login", re.I)
ABOUT_DULL = re.compile(r"repo|github|readme|source|code|file", re.I)


def is_dull(shot: dict, beat: dict) -> bool:
    """A page of text or code scrolling by (a repository, a README) is not a picture of what is said: the host 2026-10-29, 'scrolling through a github repo just isn't interesting'.
    It stays only where the sentence is about it."""
    return bool(DULL.search(f"{shot.get('file', '')} {shot.get('why', '')}")) and not ABOUT_DULL.search(beat.get("said", ""))


def audit_cutaways(work: str, name: str) -> list:
    """Takes out every automatic cutaway of one program lying over a beat about another (a TinkerCad clip over a Shapr3D passage). Returns what it took out."""
    bp = beatmap.path_of(work, name)
    data = clipmap.read_json(bp, None)
    jp = brolllib.paths(work, name)[1]
    if not data or not jp.exists():
        return []
    known = shotmatch.programs(json.loads(jp.read_text(encoding="utf-8")).get("clips", {}))
    locked = locks.beat_ids(work, name, data)
    beats = [b for b in data["beats"] if b.get("aroll") and not b.get("skip") and not b.get("vo") and not str(b.get("id", "")).startswith("H") and b["id"] not in locked]
    prog = beat_programs(beats, known)
    mine = tags.load(work, name)
    out = []
    for b in beats:
        was = (b.get("on_screen") or {}).get("broll", [])
        keep = []
        for x in was:
            p = prog.get(b["id"], "")
            if x.get("auto") and p and shotmatch.programs([x["file"]]) and not shotmatch.of_program(x["file"], {p}, shotmatch.label_at(mine, x["file"], x.get("in", 0))) and "tierlist" not in shotmatch._norm(x["file"]):
                out.append({"beat": b["id"], "file": x["file"], "program": p})
            elif x.get("auto") and is_dull(x, b):
                out.append({"beat": b["id"], "file": x["file"], "program": "dull"})
            else:
                keep.append(x)
        if len(keep) != len(was):
            b["on_screen"]["broll"] = keep
    if out:
        clipmap.write_json(bp, data)
    return out


def program_footage(clips: dict, program: str) -> list:
    """[(rel, t, dur_of_file)] sharp screen-recording moments of a program's own folder, in recording order."""
    out = []
    for rel in sorted(clips):
        if not shotmatch._norm(rel.replace("\\", "/").split("/")[0]) == program or "/" not in rel.replace("\\", "/"):
            continue
        for s in clips[rel].get("samples", []):
            if s.get("kind") == "screen recording" and s.get("sharp", True):
                out.append((rel, float(s["t"]), float(clips[rel].get("dur") or 0)))
    return out


def cover_with_footage(work: str, name: str) -> int:
    """Every talking beat of BROLL_MIN_BEAT_S or more that has no cutaway gets one from its program's own screen recordings, so the picture
    changes at least once in every beat (15 to 30 s). Within a program the footage is used in order, one moment each, so the cutaways follow
    the work as it was done. Hand-placed cutaways stay. Returns how many it added."""
    bp = beatmap.path_of(work, name)
    data = clipmap.read_json(bp, None)
    jp = brolllib.paths(work, name)[1]
    if not data or not jp.exists():
        return 0
    clips = json.loads(jp.read_text(encoding="utf-8")).get("clips", {})
    known = shotmatch.programs(clips)
    locked = locks.beat_ids(work, name, data)
    beats = [b for b in data["beats"] if b.get("aroll") and not b.get("skip") and not b.get("vo") and not str(b.get("id", "")).startswith("H") and b["id"] not in locked]
    progs = beat_programs(beats, known)
    todo: dict = {}
    for b in beats:
        broll = b.setdefault("on_screen", {}).setdefault("broll", [])
        if broll or b["dur"] < BROLL_MIN_BEAT_S:
            continue
        prog = progs.get(b["id"], "")
        if prog:
            todo.setdefault(prog, []).append(b)
    added = 0
    for prog, group in todo.items():
        foot = program_footage(clips, prog)
        if not foot:
            continue
        for i, b in enumerate(group):
            rel, t, fdur = foot[min(len(foot) - 1, int((i + 0.5) * len(foot) / len(group)))]
            piece = float(b["dur"])
            at = COVER_AFTER_S if piece >= MIN_PIECE_S + COVER_AFTER_S + 1 else 0.0
            dur = round(min(BROLL_MAX, piece - at, max(0.0, fdur - t)), 2)
            if dur < MIN_PIECE_S:
                continue
            b["on_screen"]["broll"].append({"file": rel, "in": t, "dur": dur, "at": at, "why": f"{prog} screen recording", "auto": True})
            added += 1
    clipmap.write_json(bp, data)
    return added


NAME_MIN_LIKE = 0.12         # likeness between a beat's words and a B-roll clip's NAME (the creator names them for what they show: Console, GCodeViewer, Editing Config)


def clip_name_words(rel: str) -> str:
    """The words of a B-roll clip's file name, camel case split: 'B Roll/GCodeViewer.mkv' -> 'g code viewer'."""
    stem = re.sub(r"([a-z])([A-Z])", r"\1 \2", re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", Path(rel).stem))
    return re.sub(r"[_\-]+", " ", stem).lower()


def cover_by_name(work: str, name: str) -> int:
    """Where nothing else gave a long talking beat a cutaway (no program footage, no shot-list match), a B-roll clip whose NAME says what the beat is about goes over it
    (a beat about the G-code viewer gets GCodeViewer.mkv, one about the console gets Console.mkv). A clip is used again, at a later moment of it, when it is long; the match is
    by the file name only, because a picture matched on its description alone was often the wrong one and the wrong picture is worse than none. Returns how many it added."""
    bp = beatmap.path_of(work, name)
    data = clipmap.read_json(bp, None)
    jp = brolllib.paths(work, name)[1]
    cfg = clipmap.read_json(WORK / work / f"{name}.footage.json", {}) or {}
    if not data or not jp.exists():
        return 0
    clips = json.loads(jp.read_text(encoding="utf-8")).get("clips", {})
    analysis = cfg.get("analysis") or {}
    pool = {rel: c for rel, c in clips.items() if not footage_cfg.is_ignored(cfg, rel) and not is_talking(analysis.get(rel) or {}) and any(s.get("kind") == "screen recording" for s in c.get("samples", []))}
    locked = locks.beat_ids(work, name, data)
    beats = [b for b in data["beats"] if b.get("aroll") and not b.get("skip") and not b.get("vo") and not str(b.get("id", "")).startswith("H") and b["id"] not in locked]
    like = Likeness([b["said"] for b in beats] + [clip_name_words(r) for r in pool])
    used: dict = {}
    added = 0
    for b in beats:
        on = b.setdefault("on_screen", {}).setdefault("broll", [])
        if on or b["dur"] < BROLL_MIN_BEAT_S:
            continue
        bv = like.vec(b["said"])
        scored = sorted(((like.cos(bv, like.vec(clip_name_words(r))), r) for r in pool), reverse=True)
        for sc, rel in scored:
            if sc < NAME_MIN_LIKE:
                break
            samples = [s for s in pool[rel].get("samples", []) if s.get("kind") == "screen recording" and s.get("sharp", True)]
            k = used.get(rel, 0)
            if not samples or k >= max(1, int(float(pool[rel].get("dur") or 0) // BROLL_MAX)):
                continue
            t = float(samples[min(len(samples) - 1, k * max(1, len(samples) // max(1, int(float(pool[rel].get("dur") or 1) // BROLL_MAX))))]["t"])
            at = COVER_AFTER_S if b["dur"] >= MIN_PIECE_S + COVER_AFTER_S + 1 else 0.0
            dur = round(min(BROLL_MAX, b["dur"] - at, max(0.0, float(pool[rel].get("dur") or 0) - t)), 2)
            if dur < MIN_PIECE_S:
                continue
            on.append({"file": rel, "in": t, "dur": dur, "at": at, "why": f"clip named {Path(rel).stem}", "auto": True})
            used[rel] = k + 1
            added += 1
            break
    clipmap.write_json(bp, data)
    return added
