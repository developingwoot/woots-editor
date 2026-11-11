"""Show the source: a claim the fact check found right is shown on screen as its source page, scrolled to the evidence words, over the clip where it is said."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools" / "review_app"))
import make_project  # noqa: E402
import accuracy  # noqa: E402

needs_ffmpeg = pytest.mark.skipif(not make_project.have_ffmpeg(), reason="ffmpeg missing")


def test_the_source_with_evidence_words_is_chosen_and_unsafe_links_are_not():
    c = {"sources": [{"title": "bad", "url": "javascript:alert(1)", "evidence": "x"}, {"title": "A", "url": "https://a.example/"},
                     {"title": "B", "url": "https://b.example/", "evidence": "founded in 2019"}]}
    assert accuracy.best_source(c)["title"] == "B"
    assert accuracy.best_source({"sources": [{"url": "https://a.example/"}]})["url"] == "https://a.example/"
    assert accuracy.best_source({"sources": [{"url": "file:///c:/x"}]}) is None and accuracy.best_source({}) is None


def test_the_quote_is_found_in_the_kept_words_of_the_take():
    words = [["Um", 10.0, 10.3], ["so", 10.4, 10.6], ["the", 12.0, 12.2], ["Company", 12.3, 12.7], ["was", 12.8, 13.0], ["founded", 13.1, 13.5]]
    b = {"dur": 3.0, "aroll": {"in": 10.0, "out": 14.0, "keep": [[10.0, 10.7], [12.0, 14.0]], "words": words}}
    assert accuracy.quote_at(b, "the company was founded in 2019") == 0.7          # the cut gap (10.7-12.0) does not count
    b["aroll"]["keep"] = None
    assert accuracy.quote_at(b, "company, was founded") == 2.3


def test_a_voice_over_and_a_beat_without_timed_words_still_get_a_time():
    vo = {"dur": 4.0, "vo": {"start": 5.0, "end": 9.0, "words": [["Pressure", 5.5, 5.9], ["advance", 6.0, 6.4]]}}
    assert accuracy.quote_at(vo, "pressure advance") == 0.5
    plain = {"dur": 4.0, "said": "one two three four five six seven eight", "aroll": {"words": []}}
    assert accuracy.quote_at(plain, "five six") == 2.0
    assert accuracy.quote_at(plain, "not said at all") == 0.0


def claims(r, *items):
    (r["dir"] / f"{r['name']}.accuracy.json").write_text(json.dumps({"status": "done", "claims": list(items)}), encoding="utf-8")


def test_the_plan_puts_the_page_over_the_clip_where_the_claim_is_said():
    r = make_project.build(cut=True, title="fact source plan")
    claims(r, {"id": "C01", "beat": "B02", "quote": "shirt again", "verdict": "correct",
               "sources": [{"title": "T", "url": "https://example.com/tape", "evidence": "  tape  shirts   hold  "}]},
           {"id": "C02", "beat": "B02", "quote": "x", "verdict": "correct", "sources": []},
           {"id": "C03", "beat": "B99", "quote": "x", "verdict": "correct", "sources": [{"url": "https://example.com/"}]})
    p = accuracy.source_plan(r["work"], r["name"], "C01")
    assert p == {"clip": "B02", "url": "https://example.com/tape", "find": "tape shirts hold", "at": 1.0, "seconds": accuracy.SOURCE_SECONDS}   # "shirt" is at 1.5 s; kept 2 s before the clip ends
    for cid, msg in (("C02", "no web page"), ("C03", "not in the cut"), ("C99", "no longer")):
        with pytest.raises(ValueError, match=msg):
            accuracy.source_plan(r["work"], r["name"], cid)


@needs_ffmpeg
def test_a_source_on_this_computer_is_refused_before_any_job_starts():
    import server
    r = make_project.build(cut=True, title="fact source refused")
    claims(r, {"id": "C01", "beat": "B02", "quote": "tape", "verdict": "correct", "sources": [{"url": "http://127.0.0.1:8765/", "evidence": "x"}]})
    s = accuracy.source_plan(r["work"], r["name"], "C01")
    with pytest.raises(ValueError, match="private network"):
        server.start_web_broll(r["work"], r["name"], s["clip"], s["url"], "scroll", s["find"], s["seconds"], s["at"])
    assert not [j for j in server._jobs.values() if j.get("pipeline") == "webcapture" and j.get("name") == r["name"]]


def test_the_prompt_asks_for_the_exact_evidence_words():
    assert '"evidence"' in accuracy.PROMPT and "EXACTLY" in accuracy.PROMPT
