"""Footage library: a local, free description of EVERY clip, so Claude (and the app) can look clips up instead of watching them.

A clip with no spoken words can only be found by what it shows, so this runs on all the footage, not only B-roll. Samples one frame every
STEP seconds of each clip (capped per clip; a clip with a lot of speech, a talking head, is sampled much more coarsely), describes each with a
local vision model (Qwen3-VL-8B, 4-bit, about 7 s a frame on the RTX 3060), and stores SigLIP image embeddings so a clip can be found by text.
The prompt's list of things to expect comes from `vision_hints` in <name>.footage.json (a default for the channel otherwise).

Writes only under the work folder:
  <work>/<name>.brolllib.json      {"model", "step", "clips": {rel: {dur, samples: [{t, what, subject, hands, kind, sharp, frame}]}}}
  <work>/<name>.brolllib.npz       SigLIP embeddings (keys = "<rel>|<t>"), float16, L2-normalised
  <work>/brolllib/frames/*.jpg     the sampled frames (768 px wide)
Resumable: clips already in the json are skipped; the json is rewritten after every clip.

  python brolllib.py <work> [--name N] [--limit N]          build / continue (name defaults to work)
  python brolllib.py <work> [--name N] --find "text query"  search by SigLIP, prints the best clips and times
WOOTS_FAKE_VISION=1 (tests): no models; the caption is the file name and the embedding is a hash of the caption's words.
Descriptions are hints (part names can be wrong); confirm the frame actually used by looking at it.
"""
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import sectionrender  # noqa: E402
import footage_cfg  # noqa: E402
import engines  # noqa: E402
import tags  # noqa: E402

FF = sectionrender.FFMPEG
VLM = "Qwen/Qwen3-VL-8B-Instruct"
SIGLIP = "google/siglip-base-patch16-224"
STEP, CAP = 6.0, 120
TALK_STEP, TALK_CAP = 30.0, 24            # a talking head looks the same all the way through: a few frames are enough
TALK_WORDS_PER_S = 0.5                    # more speech than this per second counts as a talking head
FAKE_DIM = 64
import config  # noqa: E402
WORK_ROOT = config.WORK

DEFAULT_HINTS = "tools, materials, hands holding things, a computer screen"          # the profile's `subjects` replaces this


def prompt_for(cfg: dict) -> str:
    import channel
    p = channel.load()
    return (f'This is one frame from footage for {p["topic"]}. '
            f'Things that often appear: {cfg.get("vision_hints") or p["subjects"] or DEFAULT_HINTS}. '
            'Use those names only when you can clearly see that part; otherwise describe it plainly. '
            'Do not mention anything that is not visible. '
            'Reply with JSON only, no other text: {"what": "one plain sentence on what is visible", "subject": "short noun phrase", '
            '"hands": true or false (human hands or fingers visible), "kind": "real footage" | "screen recording", '
            '"sharp": true or false (in focus)}')


def dur_of(path: str) -> float:
    r = subprocess.run([FF, "-hide_banner", "-i", path], capture_output=True, text=True).stderr
    h, m, s = r.split("Duration:")[1].split(",")[0].strip().split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)


def clips_of(cfg: dict, scope: str = "all", skip_ignored: bool = True) -> list[str]:
    """Every recording in the footage folder (scope 'all'), or only the B-roll (scope 'broll')."""
    root = Path(cfg["folder"])
    out = []
    for p in sorted(root.rglob("*")):
        if p.suffix.lower() in footage_cfg.VIDEO_EXT and not p.name.lower().endswith(".proxy.mp4"):
            rel = p.relative_to(root).as_posix()
            if skip_ignored and footage_cfg.is_ignored(cfg, rel):
                continue
            if scope == "all" or footage_cfg.role_of(cfg, rel)[0] == "broll":
                out.append(rel)
    return out


def talking(cfg: dict, rel: str, dur: float) -> bool:
    """True when the clip's transcript has a lot of speech (a talking head)."""
    words = len(((cfg.get("analysis") or {}).get(rel) or {}).get("list") or [])
    return dur > 0 and words / dur > TALK_WORDS_PER_S


def tag_of(rel: str) -> str:
    return hashlib.md5(rel.encode()).hexdigest()[:8] + "_" + "".join(c if c.isalnum() else "_" for c in rel.rsplit(".", 1)[0])[-40:]


def sample_times(d: float, step: float = STEP, cap: int = CAP) -> list[float]:
    step = step if d / step <= cap else d / cap
    t, out = min(1.0, d / 2), []
    while t < d - 0.3 and len(out) < cap:
        out.append(round(t, 2))
        t += step
    return out or [0.0]


def grab(path: str, t: float, f: Path):
    if not f.exists():
        subprocess.run([FF, "-nostdin", "-v", "error", "-ss", str(t), "-i", path, "-frames:v", "1", "-vf", "scale=768:-2", "-q:v", "3", str(f)], check=True)


def paths(work: str, name: str | None = None):
    name = name or work
    d = WORK_ROOT / work
    return d, d / f"{name}.brolllib.json", d / f"{name}.brolllib.npz", d / "brolllib" / "frames"


def fake() -> bool:
    return bool(os.environ.get("WOOTS_FAKE_VISION"))


def fake_embed(text: str):
    """Tests: a unit vector from the words of `text` (the same words give the same direction)."""
    import numpy as np
    v = np.zeros(FAKE_DIM, dtype="float32")
    for w in "".join(c.lower() if c.isalnum() else " " for c in text).split():
        v[int(hashlib.md5(w.encode()).hexdigest(), 16) % FAKE_DIM] += 1.0
    n = float(np.linalg.norm(v))
    return v / n if n else v


def state(work: str, name: str | None = None) -> dict:
    """How much of the footage has been looked at: {total, described, missing: [rel], ready}. Needs no models."""
    d, jp, ep, _ = paths(work, name)
    cfg = footage_cfg.with_titles(footage_cfg.load(d / f"{name or work}.footage.json"), work, name or work)
    if not cfg.get("folder") or not Path(cfg["folder"]).is_dir():
        return {"total": 0, "described": 0, "missing": [], "ready": False, "no_folder": True}
    try:
        lib = json.loads(jp.read_text(encoding="utf-8")) if jp.exists() else {"clips": {}}
    except ValueError:
        lib = {"clips": {}}
    every = clips_of(cfg)
    missing = [c for c in every if not (lib["clips"].get(c) or {}).get("samples") and not (lib["clips"].get(c) or {}).get("error")]
    return {"total": len(every), "described": len(every) - len(missing), "missing": missing, "ready": bool(every) and not missing, "no_folder": False}


def build(work: str, limit: int | None, name: str | None = None):
    import numpy as np
    d, jp, ep, fdir = paths(work, name)
    fdir.mkdir(parents=True, exist_ok=True)
    cfg = footage_cfg.with_titles(footage_cfg.load(d / f"{name or work}.footage.json"), work, name or work)
    lib = json.loads(jp.read_text(encoding="utf-8")) if jp.exists() else {"model": VLM, "step": STEP, "clips": {}}
    todo = [c for c in clips_of(cfg) if c not in lib["clips"]]
    if limit:
        todo = todo[:limit]
    print(len(todo), "clips to describe", flush=True)
    caption = None
    if todo and not fake():
        import torch
        from transformers import AutoModelForImageTextToText, AutoProcessor, BitsAndBytesConfig
        vlm = engines.local_path(engines.chosen("vision"))          # the model the user picked in Settings (Qwen3-VL 8B unless changed), the pinned revision, from disk
        proc = AutoProcessor.from_pretrained(vlm)
        model = AutoModelForImageTextToText.from_pretrained(vlm, quantization_config=BitsAndBytesConfig(
            load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_compute_dtype=torch.bfloat16), device_map="cuda")
        prompt = prompt_for(cfg)

        def caption(f: Path) -> dict:
            msgs = [{"role": "user", "content": [{"type": "image", "image": str(f)}, {"type": "text", "text": prompt}]}]
            inp = proc.apply_chat_template(msgs, tokenize=True, add_generation_prompt=True, return_dict=True, return_tensors="pt").to("cuda")
            with torch.no_grad():
                o = model.generate(**inp, max_new_tokens=140, do_sample=False)
            s = proc.batch_decode(o[:, inp["input_ids"].shape[1]:], skip_special_tokens=True)[0].strip()
            s = s.strip("`").removeprefix("json").strip()
            try:
                return json.loads(s)
            except Exception:
                return {"raw": s}

    t0 = time.time()
    for n, rel in enumerate(todo, 1):
        src = str(Path(cfg["folder"]) / rel)
        try:
            dd = dur_of(src)
            step, cap = (TALK_STEP, TALK_CAP) if talking(cfg, rel, dd) else (STEP, CAP)
            rows = []
            for t in sample_times(dd, step, cap):
                f = fdir / f"{tag_of(rel)}_{t:08.2f}.jpg"
                grab(src, t, f)
                c = caption(f) if caption else {"what": Path(rel).stem, "subject": Path(rel).stem, "hands": False, "kind": "real footage", "sharp": True}
                c.update(t=t, frame=f.name)
                rows.append(c)
            lib["clips"][rel] = {"dur": round(dd, 1), "samples": rows}
        except Exception as e:  # keep going; note the failure
            lib["clips"][rel] = {"error": str(e)[:200], "samples": []}
        tmp = jp.with_suffix(".tmp")
        tmp.write_text(json.dumps(lib, indent=1, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, jp)
        print(f"[{n}/{len(todo)}] {rel} {len(lib['clips'][rel]['samples'])} frames, {round((time.time() - t0) / 60, 1)} min", flush=True)
    if caption:
        import torch
        del model
        torch.cuda.empty_cache()

    # SigLIP embeddings for every sampled frame
    emb = dict(np.load(ep)) if ep.exists() else {}
    items = [(f"{rel}|{s['t']}", fdir / s["frame"], s) for rel, c in lib["clips"].items() for s in c["samples"] if f"{rel}|{s['t']}" not in emb]
    if items and fake():
        for k, _, s in items:
            emb[k] = fake_embed(f"{k.split('|')[0]} {s.get('what', '')}").astype("float16")
        np.savez(ep, **emb)
    elif items:
        import torch
        from PIL import Image
        from transformers import AutoModel, AutoProcessor
        sm = AutoModel.from_pretrained(engines.local_path(engines.by_id("siglip"))).to("cuda").eval()
        sp = AutoProcessor.from_pretrained(engines.local_path(engines.by_id("siglip")))
        for i in range(0, len(items), 16):
            batch = items[i:i + 16]
            x = sp(images=[Image.open(f).convert("RGB") for _, f, _ in batch], return_tensors="pt").to("cuda")
            with torch.no_grad():
                e = sm.get_image_features(**x)
                e = e.pooler_output if hasattr(e, "pooler_output") else e
            e = torch.nn.functional.normalize(e, dim=-1).cpu().numpy().astype("float16")
            for (k, _, _), v in zip(batch, e):
                emb[k] = v
        np.savez(ep, **emb)
    print("done:", len(lib["clips"]), "clips,", len(emb), "frames embedded", flush=True)


def search(work: str, query: str, top: int = 8, name: str | None = None, exclude: tuple = ()) -> list[dict]:
    """The best matching moments for a text query, one per clip, best first: [{rel, t, score, what, subject, frame}]. Empty when nothing was looked at."""
    import numpy as np
    d, jp, ep, _ = paths(work, name)
    if not query.strip():
        return []
    if not jp.exists() or not ep.exists():
        return tag_only(work, name, query, top, exclude)
    lib = json.loads(jp.read_text(encoding="utf-8"))
    emb = np.load(ep)
    keys = [k for k in emb.files if k.rsplit("|", 1)[0] not in exclude]
    if not keys:
        return tag_only(work, name, query, top, exclude)
    E = np.stack([emb[k] for k in keys]).astype("float32")
    if fake():
        q = fake_embed(query)
    else:
        import torch
        from transformers import AutoModel, AutoProcessor
        sm = AutoModel.from_pretrained(engines.local_path(engines.by_id("siglip"))).eval()                                   # the text side is small: the CPU is fine
        sp = AutoProcessor.from_pretrained(engines.local_path(engines.by_id("siglip")))
        x = sp(text=[query], padding="max_length", return_tensors="pt")
        with torch.no_grad():
            q = sm.get_text_features(**x)
            q = q.pooler_output if hasattr(q, "pooler_output") else q
        q = torch.nn.functional.normalize(q, dim=-1).numpy()[0]
    sims = E @ q
    z = (sims - sims.mean()) / (sims.std() or 1.0)                  # how far above the other moments this one is, not the raw cosine
    samples = {}
    for i, k in enumerate(keys):
        rel, t = k.rsplit("|", 1)
        samples[i] = next((x for x in (lib["clips"].get(rel) or {}).get("samples", []) if str(x["t"]) == t), {})
    want = words_of(query)
    mine = tags.load(work, name or work)                                           # what the user said is on screen beats the model's description
    bonus = {}
    for i, k in enumerate(keys):
        rel, t = k.rsplit("|", 1)
        tg = tags.at(mine, rel, float(t))
        if tg:
            samples[i] = {**samples[i], "what": tg["label"], "subject": tg["label"], "tagged": True}
            bonus[i] = TAG_WEIGHT * tag_share(want, tg["label"])
    score = np.array([z[i] + LEX_WEIGHT * lexical(want, keys[i].rsplit("|", 1)[0], samples[i]) + bonus.get(i, 0.0) for i in range(len(keys))])
    ranked = [(float(score[i]), keys[i].rsplit("|", 1)[0], float(keys[i].rsplit("|", 1)[1]), float(sims[i]), samples[i]) for i in np.argsort(-score)]
    have = {r[1] for r in ranked}
    for tg in mine:                                                                  # a tagged clip the library has nothing on: the tag alone makes it findable
        share = tag_share(want, tg["label"])
        if tg["rel"] not in have and share > 0:
            ranked.append((TAG_WEIGHT * share, tg["rel"], tg["start"], 0.0, {"what": tg["label"], "subject": tg["label"], "tagged": True}))
    out, seen = [], set()
    for sc, rel, t, vis, s in sorted(ranked, key=lambda r: -r[0]):
        if rel in seen:
            continue
        seen.add(rel)
        out.append({"rel": rel, "t": t, "score": round(sc, 2), "visual": round(vis, 3), "what": s.get("what", ""), "tagged": bool(s.get("tagged")),
                    "subject": s.get("subject", ""), "frame": s.get("frame", ""), "dur": (lib["clips"].get(rel) or {}).get("dur")})
        if len(out) >= top:
            break
    return out


def tag_only(work: str, name: str | None, query: str, top: int, exclude: tuple = ()) -> list[dict]:
    """Nothing in the library yet: the user's tags alone answer the search."""
    want = words_of(query)
    out, seen = [], set()
    for tg in sorted(tags.load(work, name or work), key=lambda x: -tag_share(want, x["label"])):
        share = tag_share(want, tg["label"])
        if share <= 0 or tg["rel"] in seen or tg["rel"] in exclude:
            continue
        seen.add(tg["rel"])
        out.append({"rel": tg["rel"], "t": tg["start"], "score": round(TAG_WEIGHT * share, 2), "visual": 0.0, "what": tg["label"], "tagged": True,
                    "subject": tg["label"], "frame": "", "dur": None})
    return out[:top]


TAG_WEIGHT = 3.0            # a tag whose words are all in the query is worth this many standard deviations: tags win over descriptions


def tag_share(want: list[str], label: str) -> float:
    """0..1: the share of the query's words that the user's tag names."""
    if not want:
        return 0.0
    have = set(words_of(label))
    return sum(w in have for w in want) / len(want)


STOP = {"a", "an", "the", "of", "and", "or", "on", "in", "at", "to", "with", "for", "is", "are", "some", "shot", "clip", "video", "footage", "closeup", "close", "up"}
LEX_WEIGHT = 2.0            # a query word found in the clip's name or description is worth this many standard deviations of image similarity


def words_of(text: str) -> list[str]:
    """The meaningful words of a query or caption, lower case, plurals folded (hands -> hand)."""
    ws = "".join(c.lower() if c.isalnum() else " " for c in text).split()
    return [w[:-1] if len(w) > 3 and w.endswith("s") and not w.endswith("ss") else w for w in ws if w not in STOP]


def lexical(want: list[str], rel: str, sample: dict) -> float:
    """0..1: the share of the query's words that appear in the clip's file name (counts double: the host names his clips) or in the description."""
    if not want:
        return 0.0
    stem = Path(rel).stem
    name = set(words_of(stem)) | set(words_of(re.sub(r"(?<=[a-z])(?=[A-Z])", " ", stem)))          # 'TierList_1' also names 'tier' and 'list'
    desc = set(words_of(f"{sample.get('what', '')} {sample.get('subject', '')}"))
    return sum(1.0 if w in name else 0.5 if w in desc else 0.0 for w in want) / len(want)


def find(work: str, query: str, top: int = 8, name: str | None = None):
    for r in search(work, query, top, name):
        print(f"{r['score']:.2f}  {r['rel']} @ {r['t']}s  {r['what']}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("work")
    ap.add_argument("--name")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--find")
    a = ap.parse_args()
    find(a.work, a.find, name=a.name) if a.find else build(a.work, a.limit, a.name)
