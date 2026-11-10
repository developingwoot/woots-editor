"""Map transcribed clips to the script: takes, topic spans, best take per script line.

Usage:
    python clipmap.py <work> <name> [--roles aroll,unassigned]     # writes <name>.clips.json (old one kept as .bak)

Inputs (all under _editor\\work\\<work>\\):
    <name>.script.md       lines that start with an id: "S01 Hook ...". "# Heading" lines name the section.
    <name>.footage.json    the footage folder + per-clip "analysis" (word list, restarts) from analyze_takes.py
Output <name>.clips.json (the rough cut screen edits it):
    {"script_fp", "folder", "clips": [{"rel", "name", "dur", "role", "spans": [span]}],
     "by_line": {"S01": {"candidates": [span ids, best first], "picked": id|None, "picked_by": "auto"|"user",
                         "score": {id: x}, "reason": "..."}},
     "missing_lines": ["S07"], "corrections": [...]}
    span = {"id", "start", "end", "dur", "topic", "summary", "text", "script_lines", "coverage": {line: 0..1},
            "confidence", "flags": [...], "wpm", "restarts", "skip", "note", "edited"}

How it works (deterministic; Claude then rewrites the summaries with judgment):
  1. split each recording into takes at pauses > 1.2 s and at restarts the transcript tools flagged;
  2. align each take's words against the whole script (difflib on word lists) to find which lines it reads;
  3. split a long take (> 45 s) where the matched script line changes, in chunks of at least 15 s, so one
     recording that covers a big part of the script becomes several topic spans;
  4. rank the spans that cover each line (completeness, on-script, restarts, slow stretches, pace).
Python stdlib only.
"""
import argparse
import difflib
import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path

HERE = Path(os.path.abspath(__file__)).parent
import config
WORK = config.WORK
sys.path.insert(0, str(HERE))
import footage_cfg  # noqa: E402

PAUSE_SPLIT = 1.2        # s: a longer pause ends a take
SLOW_PAUSE = 0.8         # s: a pause this long inside a take counts as a slow stretch
LONG_TAKE = 45.0         # s: split longer takes where the script line changes
MIN_CHUNK = 15.0         # s
MIN_BLOCK = 3            # words that must match in a row to count as reading a script line
LINE_COVER = 0.5         # a line counts as read when this share of its words were matched
SHARE_MIN = 0.2          # ... and those words are at least this share of the take's words
WPM_OK = (100, 200)

ID_RE = re.compile(r"^\W*(S\d{2,3})\b[\s:.\-–—]*(.*)$")
TOK = re.compile(r"[a-z0-9']+")


def tokens_of(s: str) -> list[str]:
    return TOK.findall(s.lower().replace("’", "'"))


def _replace(tmp, p):
    """os.replace that survives a reader holding the destination open (Windows: 'Access is denied' while the board polls)."""
    for i in range(8):
        try:
            os.replace(tmp, p)
            return
        except PermissionError:
            if i == 7:
                raise
            time.sleep(0.05 * (i + 1))


def read_json(p: Path, default=None):
    if not p.exists():
        return default
    return json.loads(p.read_text(encoding="utf-8-sig"))


import projectstore  # noqa: E402  (plan-file writes are recorded: ADR 0005)


def write_json(p: Path, data):
    projectstore.write_json(p, data)


# ----------------------------------------------------------------------------- script
def parse_script(text: str) -> list[dict]:
    """[{id, text, said, heading, tokens}]: `said` = the line without [bracketed notes]. A script with no line ids that is in the host's outline
    format (v2) gives one line per talking point / voice-over, numbered S01, S02... by order (outline.speech_lines)."""
    lines, heading = [], None
    if not any(ID_RE.match(r) for r in text.splitlines()):
        import outline
        model = outline.parse(text)
        if model["format"] == "outline" and model["sections"]:
            return [{"id": ln["id"], "text": ln["text"], "said": ln["said"], "heading": ln["heading"], "tokens": tokens_of(ln["said"])}
                    for ln in outline.speech_lines(model)]
    for raw in text.splitlines():
        s = raw.strip()
        if s.startswith("#"):
            heading = s.lstrip("# ").strip() or heading
            continue
        m = ID_RE.match(raw)
        if not m:
            continue
        body = m.group(2).strip()
        said = re.sub(r"\[[^\]]*\]", " ", body).replace(">", " ").strip()
        lines.append({"id": m.group(1), "text": body, "said": said, "heading": heading, "tokens": tokens_of(said)})
    return lines


class Script:
    def __init__(self, lines: list[dict]):
        self.lines = lines
        self.flat, self.line_of = [], []
        for i, ln in enumerate(lines):
            self.flat += ln["tokens"]
            self.line_of += [i] * len(ln["tokens"])
        self.index = {ln["id"]: i for i, ln in enumerate(lines)}

    def match(self, toks: list[str]) -> list[int]:
        """For each take token: the index of the script token it was matched to, or -1."""
        asg = [-1] * len(toks)
        if not toks or not self.flat:
            return asg
        sm = difflib.SequenceMatcher(None, toks, self.flat, autojunk=False)
        for a, b, n in sm.get_matching_blocks():
            whole_line = False
            if n < MIN_BLOCK:                       # a short script line read word for word still counts
                li = self.line_of[b] if b < len(self.line_of) else -1
                whole_line = li >= 0 and len(self.lines[li]["tokens"]) == n and n >= 2 and self.line_of[b + n - 1] == li
            if n >= MIN_BLOCK or whole_line:
                for k in range(n):
                    asg[a + k] = b + k
        return asg

    def coverage(self, asg: list[int], lo: int, hi: int) -> tuple[dict, dict]:
        """(share of each line's words matched, number of matched words) by take tokens lo..hi-1."""
        got: dict[int, int] = {}
        for j in range(lo, hi):
            if asg[j] >= 0:
                li = self.line_of[asg[j]]
                got[li] = got.get(li, 0) + 1
        ratio = {self.lines[li]["id"]: round(c / max(1, len(self.lines[li]["tokens"])), 2) for li, c in got.items()}
        return ratio, {self.lines[li]["id"]: c for li, c in got.items()}


# ----------------------------------------------------------------------------- takes and spans
def split_takes(words: list, restart_at: list) -> list[list]:
    """words = [[word, start, end], ...] -> groups split at long pauses and at flagged restarts."""
    if not words:
        return []
    cuts = set()
    for i in range(1, len(words)):
        if words[i][1] - words[i - 1][2] > PAUSE_SPLIT:
            cuts.add(i)
    for r in restart_at or []:
        i = next((k for k, w in enumerate(words) if w[1] >= r - 0.05), None)
        if i:
            cuts.add(i)
    out, cur = [], []
    for i, w in enumerate(words):
        if i in cuts and cur:
            out.append(cur)
            cur = []
        cur.append(w)
    out.append(cur)
    return out


def chunk_long(words: list, asg_words: list[int], script: Script) -> list[tuple[int, int]]:
    """Index ranges [lo, hi) of `words`. A take over LONG_TAKE s is cut where the matched line changes,
    at the biggest gap near the change, keeping every chunk at least MIN_CHUNK s."""
    n = len(words)
    if n < 2 or words[-1][2] - words[0][1] <= LONG_TAKE:
        return [(0, n)]
    line = []                                   # script line index per word, forward-filled
    cur = -1
    for a in asg_words:
        if a >= 0:
            cur = script.line_of[a]
        line.append(cur)
    cuts = []
    for i in range(1, n):
        if line[i] != line[i - 1] and line[i] >= 0 and line[i - 1] >= 0:
            best, gap = i, -1.0                 # biggest pause within +-4 words of the change
            for k in range(max(1, i - 4), min(n, i + 5)):
                g = words[k][1] - words[k - 1][2]
                if g > gap:
                    best, gap = k, g
            cuts.append(best)
    ranges, lo = [], 0
    for c in sorted(set(cuts)):
        if c > lo and words[c][1] - words[lo][1] >= MIN_CHUNK and words[-1][2] - words[c][1] >= MIN_CHUNK:
            ranges.append((lo, c))
            lo = c
    ranges.append((lo, n))
    return ranges


def describe(words: list, script: Script, restart_at: list | None = None) -> dict:
    """Everything the UI shows about a stretch of words: text, lines read, confidence, flags."""
    toks, widx = [], []
    for i, w in enumerate(words):
        for t in tokens_of(w[0]):
            toks.append(t)
            widx.append(i)
    asg = script.match(toks)
    cov, cnt = script.coverage(asg, 0, len(toks))
    # A take only "reads" a line if that line is a real part of it. A short phrase that recurs inside a long
    # ramble ("was it worth it") must not make the ramble a candidate take for the line.
    for lid in [k for k in cov if cnt[k] < SHARE_MIN * len(toks)]:
        if cnt[lid] < 3 or cov[lid] >= LINE_COVER:
            del cov[lid]
    lines = [lid for lid, c in sorted(cov.items(), key=lambda kv: script.index[kv[0]]) if c >= LINE_COVER]
    on = sum(1 for a in asg if a >= 0)
    conf = round(on / len(toks), 2) if toks else 0.0
    start, end = (words[0][1], words[-1][2]) if words else (0.0, 0.0)
    dur = max(0.01, end - start)
    wpm = round(len(words) / (dur / 60)) if len(words) > 3 else 0
    slow = sum(1 for a, b in zip(words, words[1:]) if SLOW_PAUSE < b[1] - a[2] <= PAUSE_SPLIT)
    # A restart is held against the take that was ABANDONED: one that ends just before the retake begins
    # (r = where the retake starts) or has the restart inside it. The clean retake itself is not penalised.
    restarts = sum(1 for r in (restart_at or []) if start + 0.05 < r <= end + 3.0)
    flags = []
    if not lines:
        flags.append("not in the script")
    elif conf < 0.6:
        flags.append(f"only {int(conf * 100)}% of the words match the script")
    part = [lid for lid, c in cov.items() if 0.2 <= c < LINE_COVER]
    if part and lines:
        flags.append("partly reads " + ", ".join(sorted(part, key=lambda x: script.index[x])))
    if restarts:
        flags.append(f"{restarts} restart{'s' if restarts != 1 else ''}")
    if slow >= 2:
        flags.append(f"{slow} slow pauses")
    if dur < 2:
        flags.append("very short")
    if wpm and not WPM_OK[0] <= wpm <= WPM_OK[1]:
        flags.append(f"{wpm} wpm")
    text = " ".join(w[0] for w in words)
    return {"start": round(start, 3), "end": round(end, 3), "dur": round(dur, 2), "text": text, "script_lines": lines,
            "coverage": cov, "confidence": conf, "flags": flags, "wpm": wpm, "restarts": restarts, "slow": slow}


def topic_of(script: Script, lines: list[str], text: str) -> str:
    if lines:
        ln = script.lines[script.index[lines[0]]]
        return ln["heading"] or " ".join(ln["said"].split()[:8])
    return "Not in the script: " + " ".join(text.split()[:6])


def summary_of(script: Script, lines: list[str], text: str) -> str:
    head = " ".join(text.split()[:14]) + ("…" if len(text.split()) > 14 else "")
    if not lines:
        return f"Off-script. Starts: “{head}”"
    rng = lines[0] if len(lines) == 1 else f"{lines[0]}–{lines[-1]}"
    return f"Reads {rng}. Starts: “{head}”"


def span_id(rel: str, start: float) -> str:
    return hashlib.sha1(rel.encode()).hexdigest()[:6] + f"-{int(round(start * 1000)):07d}"


def make_span(rel: str, words: list, script: Script, restart_at: list) -> dict:
    d = describe(words, script, restart_at)
    sp = {"id": span_id(rel, d["start"]), **d}
    sp["topic"] = topic_of(script, d["script_lines"], d["text"])
    sp["summary"] = summary_of(script, d["script_lines"], d["text"])
    sp.update(skip=False, note="", edited=False)
    return sp


# ----------------------------------------------------------------------------- ranking
def score(sp: dict, line: str) -> float:
    s = 0.55 * sp["coverage"].get(line, 0) + 0.25 * sp["confidence"]
    s -= 0.20 * min(sp["restarts"], 2) + 0.05 * min(sp.get("slow", 0), 4)
    if sp["wpm"] and not WPM_OK[0] <= sp["wpm"] <= WPM_OK[1]:
        s -= 0.05
    return round(s, 3)


def why_picked(sp: dict, line: str, n: int) -> str:
    bits = [f"covers {int(sp['coverage'].get(line, 0) * 100)}% of the line"]
    bits.append("no restarts" if not sp["restarts"] else f"{sp['restarts']} restart(s)")
    if sp["wpm"]:
        bits.append(f"{sp['wpm']} wpm")
    return (f"best of {n} take{'s' if n != 1 else ''}: " if n > 1 else "only take: ") + ", ".join(bits)


STOP = set("""a an and are as at be been but by can do does for from had has have he her his i if in into is it its just me my of on or our
so than that the their them then there these they this to up us was we were what when which who will with you your not no yes
like really very about all some more most one two get got going gonna im ive thats youre dont didnt""".split())
LOOSE_MIN = 0.2          # topic likeness (0..1) a take needs to stand in for a line it does not read word for word
LOOSE_MIN_DUR = 3.0      # s


def _content(s: str) -> list[str]:
    return [t.replace("'", "") for t in tokens_of(s) if t.replace("'", "") not in STOP and len(t) > 1]


def loose_matches(script: Script, spans: list[dict], skip_lines: set) -> dict:
    """{line id: [(likeness, span)] best first} for lines no take reads word for word: the take that talks about the same things
    (idf-weighted shared words, so program names count most). A take reading another line is not used, and each take stands in for one line."""
    docs = {ln["id"]: _content(ln["said"]) for ln in script.lines}
    sdocs = {sp["id"]: _content(sp["text"]) for sp in spans}
    df: dict[str, int] = {}
    for d in list(docs.values()) + list(sdocs.values()):
        for t in set(d):
            df[t] = df.get(t, 0) + 1
    n = len(docs) + len(sdocs)

    def vec(d):
        v: dict[str, float] = {}
        for t in d:
            v[t] = v.get(t, 0) + 1
        v = {t: c * (1 + (n / df[t]) ** 0.5) for t, c in v.items()}
        norm = sum(x * x for x in v.values()) ** 0.5
        return {t: x / norm for t, x in v.items()} if norm else {}

    lv = {lid: vec(d) for lid, d in docs.items() if lid in skip_lines}
    sv = {sid: vec(d) for sid, d in sdocs.items()}
    free = [sp for sp in spans if sp["dur"] >= LOOSE_MIN_DUR and not any(c >= LINE_COVER for c in sp["coverage"].values())]
    pairs = []
    for lid, a in lv.items():
        for sp in free:
            b = sv[sp["id"]]
            s = sum(x * b.get(t, 0) for t, x in a.items())
            if s >= LOOSE_MIN:
                pairs.append((s, lid, sp))
    pairs.sort(key=lambda p: -p[0])
    out: dict[str, list] = {}
    used: set = set()
    for s, lid, sp in pairs:                      # the best pair first, so a take goes to the line it is most like
        if sp["id"] in used:
            continue
        used.add(sp["id"])
        out.setdefault(lid, []).append((round(s, 3), sp))
    return out


def rank_lines(data: dict, script: Script):
    """Recompute candidates / scores for every script line; keep the host's picks, auto-pick the rest. A line no take reads word for word
    gets the take that talks about the same things (`loose`), for the host to confirm."""
    old = data.get("by_line", {})
    spans = [sp for c in data["clips"] for sp in c["spans"] if not sp.get("skip")]
    by_line, missing = {}, []
    bare = {ln["id"] for ln in script.lines if not any(sp["coverage"].get(ln["id"], 0) >= LINE_COVER for sp in spans)}
    loose = loose_matches(script, spans, bare)
    for ln in script.lines:
        lid = ln["id"]
        cands = [sp for sp in spans if sp["coverage"].get(lid, 0) >= LINE_COVER]
        scored = sorted(((score(sp, lid), sp) for sp in cands), key=lambda t: -t[0])
        if not cands and loose.get(lid):
            scored = [(s, sp) for s, sp in loose[lid]]
            cands = [sp for _, sp in scored]
        ids = [sp["id"] for _, sp in scored]
        prev = old.get(lid, {})
        picked, by = None, "auto"
        if prev.get("picked_by") == "user" and (prev.get("picked") in ids or prev.get("picked") is None):
            picked, by = prev.get("picked"), "user"
        elif ids:
            picked = ids[0]
        entry = {"candidates": ids, "picked": picked, "picked_by": by, "score": {sp["id"]: s for s, sp in scored}}
        is_loose = bool(cands) and not any(sp["coverage"].get(lid, 0) >= LINE_COVER for sp in cands)
        if is_loose:
            entry["loose"] = True
        if picked and is_loose:
            entry["reason"] = (f"you chose this take" if by == "user" else
                               f"closest take by topic, not word for word ({int(entry['score'][picked] * 100)}% alike): check it")
        elif picked:
            sp = next(x for x in cands if x["id"] == picked)
            entry["reason"] = (f"your choice from {len(ids)}: " + why_picked(sp, lid, 0).split(': ', 1)[-1]
                               if by == "user" else why_picked(sp, lid, len(ids)))
        else:
            entry["reason"] = "no usable take" if by == "auto" else "you chose no take"
            if by == "auto":
                missing.append(lid)
        by_line[lid] = entry
    data["by_line"], data["missing_lines"] = by_line, missing


# ----------------------------------------------------------------------------- build
def script_path(work: str, name: str) -> Path:
    return WORK / work / f"{name}.script.md"


def load_script(work: str, name: str) -> Script:
    p = script_path(work, name)
    if not p.exists():
        raise ValueError(f"no script yet: {p.name}")
    lines = parse_script(p.read_text(encoding="utf-8-sig"))
    if not lines:
        raise ValueError("the script has no line ids (S01, S02, ...)")
    return Script(lines)


def script_fp(work: str, name: str) -> str:
    return hashlib.sha256(script_path(work, name).read_bytes()).hexdigest()[:16]


def iou(a0, a1, b0, b1) -> float:
    i = max(0.0, min(a1, b1) - max(a0, b0))
    u = (a1 - a0) + (b1 - b0) - i
    return i / u if u > 0 else 0.0


def build(work: str, name: str, roles=("aroll", "unassigned")) -> dict:
    wd = WORK / work
    script = load_script(work, name)
    cfg = footage_cfg.with_titles(read_json(wd / f"{name}.footage.json", {}) or {}, work, name)
    analysis = cfg.get("analysis") or {}
    if not analysis:
        raise ValueError("no clips are transcribed yet: use 'Transcribe clips' first")
    out_path = wd / f"{name}.clips.json"
    old = read_json(out_path, None)
    clips = []
    for rel, an in sorted(analysis.items()):
        role, _ = footage_cfg.role_of(cfg, rel)
        words = an.get("list") or []
        if role not in roles or not words or footage_cfg.is_ignored(cfg, rel):
            continue
        spans = []
        restart_at = an.get("restart_at") or []
        for grp in split_takes(words, restart_at):
            toks, widx = [], []
            for i, w in enumerate(grp):
                for t in tokens_of(w[0]):
                    toks.append(t)
                    widx.append(i)
            asg_tok = script.match(toks)
            asg_word = [-1] * len(grp)
            for t, a in zip(widx, asg_tok):
                if a >= 0 and asg_word[t] < 0:
                    asg_word[t] = a
            for lo, hi in chunk_long(grp, asg_word, script):
                spans.append(make_span(rel, grp[lo:hi], script, restart_at))
        for a, nxt in zip(spans, spans[1:]):          # one script line cut in two by a long pause mid-sentence
            for lid, c in a["coverage"].items():
                if 0.2 <= c < LINE_COVER and nxt["coverage"].get(lid, 0) >= 0.2 and lid not in a["script_lines"]:
                    a["flags"] = [f for f in a["flags"] if not f.startswith("partly reads " + lid)]
                    a["flags"].append(f"{lid} continues in the next span: join them?")
        clips.append({"rel": rel, "name": Path(rel).name, "dur": an.get("dur"), "role": role, "spans": spans})
    data = {"generated": time.strftime("%Y-%m-%dT%H:%M:%S"), "script_fp": script_fp(work, name),
            "folder": cfg.get("folder"), "clips": clips, "by_line": {}, "missing_lines": [], "corrections": []}
    if old:                                          # carry over the creator's work
        data["corrections"] = old.get("corrections", [])
        data["by_line"] = old.get("by_line", {})
        carried = 0
        for c in clips:
            oc = next((x for x in old.get("clips", []) if x["rel"] == c["rel"]), None)
            if not oc:
                continue
            for sp in c["spans"]:
                best = max(oc["spans"], key=lambda o: iou(sp["start"], sp["end"], o["start"], o["end"]), default=None)
                if best and best.get("edited") and iou(sp["start"], sp["end"], best["start"], best["end"]) >= 0.7:
                    for k in ("topic", "summary", "script_lines", "skip", "note", "edited"):
                        sp[k] = best[k]
                    for lid in sp["script_lines"]:               # a line the creator assigned counts as fully covered (as in the edit op), or it would vanish at the next match
                        sp["coverage"][lid] = max(sp["coverage"].get(lid, 0), 1.0)
                    for lid in [k for k in sp["coverage"] if k not in sp["script_lines"] and sp["coverage"][k] >= LINE_COVER]:
                        sp["coverage"][lid] = 0.0
                    if sp["script_lines"]:
                        sp["flags"] = [f for f in sp["flags"] if f != "not in the script"]
                    carried += 1
        data["carried_edits"] = carried
        write_json(out_path.with_name(out_path.name + ".bak"), old)
    rank_lines(data, script)
    write_json(out_path, data)
    return data


# ----------------------------------------------------------------------------- the creator's corrections
def find_span(data: dict, sid: str):
    for c in data["clips"]:
        for i, sp in enumerate(c["spans"]):
            if sp["id"] == sid:
                return c, i, sp
    raise ValueError(f"unknown span {sid!r}")


def words_between(cfg: dict, rel: str, a: float, b: float) -> list:
    words = ((cfg.get("analysis") or {}).get(rel) or {}).get("list") or []
    return [w for w in words if w[1] >= a - 0.001 and w[2] <= b + 0.001]


def apply_op(work: str, name: str, op: str, b: dict) -> dict:
    """One correction from the Clips tab. Returns the updated clips.json (also written)."""
    wd = WORK / work
    path = wd / f"{name}.clips.json"
    data = read_json(path, None)
    if not data:
        raise ValueError("no clips.json yet: map the clips to the script first")
    script = load_script(work, name)
    cfg = read_json(wd / f"{name}.footage.json", {}) or {}
    log = {"t": time.strftime("%Y-%m-%dT%H:%M:%S"), "op": op}
    if op == "edit":
        _, _, sp = find_span(data, b["id"])
        changed = {}
        for k in ("topic", "summary", "note"):
            if k in b and b[k] != sp.get(k):
                changed[k] = [sp.get(k), b[k]]
                sp[k] = b[k]
        if "skip" in b and bool(b["skip"]) != sp.get("skip"):
            changed["skip"] = [sp.get("skip"), bool(b["skip"])]
            sp["skip"] = bool(b["skip"])
        if "script_lines" in b:
            new = [x for x in b["script_lines"] if x in script.index]
            new.sort(key=lambda x: script.index[x])
            if new != sp["script_lines"]:
                changed["script_lines"] = [sp["script_lines"], new]
                sp["script_lines"] = new
                for lid in new:                      # a line the creator assigns counts as fully covered
                    sp["coverage"][lid] = max(sp["coverage"].get(lid, 0), 1.0)
                for lid in [k for k in sp["coverage"] if k not in new and sp["coverage"][k] >= LINE_COVER]:
                    sp["coverage"][lid] = 0.0
                sp["flags"] = [f for f in sp["flags"] if f != "not in the script"]
        if not changed:
            return data
        sp["edited"] = True
        log.update(span=b["id"], changed=changed)
    elif op == "split":
        c, i, sp = find_span(data, b["id"])
        at = float(b["at"])
        a_w = words_between(cfg, c["rel"], sp["start"], at)
        z_w = [w for w in words_between(cfg, c["rel"], sp["start"], sp["end"]) if w[1] >= at - 0.001]
        a_w = [w for w in a_w if w[2] <= at + 0.001]
        if len(a_w) < 1 or len(z_w) < 1:
            raise ValueError("split inside the span, between two words")
        restart_at = ((cfg.get("analysis") or {}).get(c["rel"]) or {}).get("restart_at") or []
        new = []
        for grp in (a_w, z_w):
            s2 = make_span(c["rel"], grp, script, restart_at)
            s2.update(edited=True, note=sp.get("note", ""))
            new.append(s2)
        c["spans"][i:i + 1] = new
        log.update(span=b["id"], at=round(at, 3), into=[x["id"] for x in new])
    elif op == "merge":
        c, i, sp = find_span(data, b["id"])
        if i + 1 >= len(c["spans"]):
            raise ValueError("no span after this one in the same clip")
        nxt = c["spans"][i + 1]
        words = words_between(cfg, c["rel"], sp["start"], nxt["end"])
        restart_at = ((cfg.get("analysis") or {}).get(c["rel"]) or {}).get("restart_at") or []
        m = make_span(c["rel"], words, script, restart_at)
        m.update(edited=True, note=(sp.get("note") or nxt.get("note") or ""))
        c["spans"][i:i + 2] = [m]
        log.update(spans=[sp["id"], nxt["id"]], into=m["id"])
    elif op == "pick":
        lid, sid = b["line"], b.get("span")
        if lid not in script.index:
            raise ValueError(f"unknown line {lid!r}")
        ent = data["by_line"].get(lid)
        if ent is None or (sid and sid not in ent["candidates"]):
            raise ValueError("that span does not cover this line")
        ent["picked"], ent["picked_by"] = sid, "user"
        log.update(line=lid, span=sid)
    else:
        raise ValueError(f"unknown op {op!r}")
    if b.get("why"):
        log["why"] = b["why"]
    data["corrections"].append(log)
    rank_lines(data, script)
    write_json(path, data)
    return data


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("work")
    ap.add_argument("name")
    ap.add_argument("--roles", default="aroll,unassigned")
    a = ap.parse_args()
    try:
        d = build(a.work, a.name, tuple(a.roles.split(",")))
    except ValueError as e:
        sys.exit(f"clipmap: {e}")
    spans = sum(len(c["spans"]) for c in d["clips"])
    picked = sum(1 for e in d["by_line"].values() if e["picked"])
    print(f"{len(d['clips'])} clips, {spans} spans; {picked}/{len(d['by_line'])} script lines have a take; "
          f"missing: {', '.join(d['missing_lines']) or 'none'}" + (f"; kept {d['carried_edits']} of your edits" if d.get("carried_edits") else ""))


if __name__ == "__main__":
    main()
