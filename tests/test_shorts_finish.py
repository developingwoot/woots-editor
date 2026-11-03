import json

import pytest

import config
import shortsapp
import shortsview
import shorts as sh


@pytest.fixture
def proj(tmp_path, monkeypatch):
    work = tmp_path / "work"
    (work / "v1").mkdir(parents=True)
    monkeypatch.setattr(shortsapp, "WORK", work)
    monkeypatch.setattr(config, "WORK", work)
    vid = tmp_path / "videos" / "big.mp4"
    vid.parent.mkdir()
    vid.write_bytes(b"x")
    shorts = [{"id": "s1", "title": "First", "hook": "A|B", "ranges": [[0, 5]], "status": "kept"},
              {"id": "s2", "title": "Second", "hook": "C", "ranges": [[5, 9]], "status": "dropped"}]
    (work / "v1" / "big.shorts.json").write_text(json.dumps({"source": str(vid), "transcript": "t.json", "shorts": shorts}), encoding="utf-8")
    return work, vid


def make_final(work, short):
    d = work / "v1" / "shorts"
    d.mkdir(exist_ok=True)
    (d / f"{short['id']}.final.mp4").write_bytes(b"final-" + short["id"].encode())
    (d / f"{short['id']}.final.render.json").write_text(json.dumps({"sig": sh.short_sig(short, sh.SIG_ALL)}), encoding="utf-8")


def test_the_youtube_details_are_edited_by_hand_and_the_link_is_kept(proj):
    shortsapp.apply_op("v1", "big", "publish", {"id": "s1", "title": " Never use a cold iron ", "tags": "Soldering, Tips ,", "filename": "Never Use A Cold Iron!"})
    shortsapp.apply_op("v1", "big", "project", {"full_video_url": " https://youtu.be/x "})
    raw = shortsapp.read_raw("v1", "big")
    pub = raw["shorts"][0]["publish"]
    assert pub["title"] == "Never use a cold iron" and pub["tags"] == ["Soldering", "Tips"] and pub["filename"] == "never-use-a-cold-iron" and raw["full_video_url"] == "https://youtu.be/x"
    assert shortsview.publish_of(raw["shorts"][0])["tags"] == "Soldering, Tips" and shortsview.publish_of(raw["shorts"][1])["written"] is False
    with pytest.raises(ValueError):
        shortsapp.apply_op("v1", "big", "publish", {"id": "s1", "title": "x" * 101})


def test_the_finished_shorts_are_saved_beside_the_video_with_their_details_and_never_overwritten(proj):
    work, vid = proj
    raw = shortsapp.read_raw("v1", "big")
    make_final(work, raw["shorts"][0])
    shortsapp.apply_op("v1", "big", "publish", {"id": "s1", "title": "Never use a cold iron", "description": "Because.", "filename": "cold-iron"})
    raw = shortsapp.read_raw("v1", "big")
    make_final(work, raw["shorts"][0])
    lines = []
    out = shortsapp.deliver("v1", "big", log=lines.append)
    dst = vid.parent / "Shorts" / "cold-iron.mp4"
    assert out == [str(dst)] and dst.read_bytes() == b"final-s1" and "Never use a cold iron" in dst.with_suffix(".txt").read_text(encoding="utf-8")
    again = shortsapp.deliver("v1", "big")
    assert again == [str(dst)] and sorted(p.name for p in dst.parent.iterdir()) == ["cold-iron.mp4", "cold-iron.txt"]   # the same file is not saved twice
    dst.write_bytes(b"something else")
    assert shortsapp.deliver("v1", "big") == [str(dst.parent / "cold-iron (2).mp4")] and dst.read_bytes() == b"something else"


def test_a_missing_or_old_final_stops_the_delivery_and_the_card_says_where_it_went(proj):
    work, vid = proj
    with pytest.raises(ValueError, match="S1"):
        shortsapp.deliver("v1", "big")
    raw = shortsapp.read_raw("v1", "big")
    make_final(work, raw["shorts"][0])
    shortsapp.deliver("v1", "big")
    card = shortsview.card("v1", "big", work / "v1", shortsapp.read_raw("v1", "big")["shorts"][0])
    assert card["delivered"]["name"] == "first.mp4" and card["delivered"]["current"] and card["delivered"]["exists"]
    shortsapp.apply_op("v1", "big", "edit", {"id": "s1", "hook": "NEW"})
    card = shortsview.card("v1", "big", work / "v1", shortsapp.read_raw("v1", "big")["shorts"][0])
    assert card["delivered"]["current"] is False and card["final"]["made"] is False
    assert shortsview.delivered_of({}) == {}


def test_the_publishing_prompt_names_no_channel_or_subject_of_its_own():
    for word in ("3D", "Klipper", "Ender", "printing"):
        assert word not in shortsapp.PUBLISH_RULES
