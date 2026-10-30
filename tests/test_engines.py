import pytest

import config
import engines
import hardware

CARD12 = {"gpus": [{"name": "RTX 3060", "vram_gb": 12.0}], "vram_gb": 12.0, "ram_gb": 32, "free_gb": 500, "tools": {}}
CARD4 = {"gpus": [{"name": "GTX 1650", "vram_gb": 4.0}], "vram_gb": 4.0, "ram_gb": 16, "free_gb": 500, "tools": {}}
NOCARD = {"gpus": [], "vram_gb": 0.0, "ram_gb": 16, "free_gb": 500, "tools": {}}


@pytest.fixture(autouse=True)
def own_settings(tmp_path, monkeypatch):
    monkeypatch.setenv("WOOTS_SETTINGS_FILE", str(tmp_path / "s.json"))
    monkeypatch.setattr(engines, "cache_root", lambda: tmp_path / "hub")
    engines._dl.clear()


def test_gpu_output_is_parsed():
    assert hardware.parse_gpus("NVIDIA GeForce RTX 3060, 12288\n") == [{"name": "NVIDIA GeForce RTX 3060", "vram_gb": 12.0}]
    assert hardware.parse_gpus("Tesla T4, 15360\nQuadro, P, 8192\n")[1]["name"] == "Quadro, P"
    assert hardware.parse_gpus("garbage") == []


def test_the_vision_model_follows_the_card():
    assert engines.recommend("vision", CARD12) == "qwen3-vl-8b"
    assert engines.recommend("vision", CARD4) == "qwen3-vl-2b"
    assert engines.recommend("vision", NOCARD) is None
    assert engines.recommend("speech", CARD12) == "parakeet-0.6b"
    assert engines.recommend("speech", NOCARD) == "whisper-small"   # Parakeet needs an Nvidia card: the Whisper family is the way in


def test_why_a_model_does_not_fit_is_said():
    ok, why = engines.fits(engines.by_id("qwen3-vl-8b"), CARD4)
    assert not ok and "10 GB" in why and "4" in why
    assert "Nvidia" in engines.fits(engines.by_id("parakeet-0.6b"), NOCARD)[1]


def test_choice_is_saved_and_unbuilt_models_are_refused(monkeypatch):
    assert engines.chosen("vision")["id"] == "qwen3-vl-8b"           # the default is what the code ran on before
    engines.choose("vision", "qwen3-vl-4b")
    assert engines.chosen("vision")["repo"] == "Qwen/Qwen3-VL-4B-Instruct"
    engines.choose("speech", "whisper-small")
    assert engines.chosen("speech")["runner"] == "whisper"
    monkeypatch.setitem(engines.by_id("whisper-small"), "built", False)
    with pytest.raises(ValueError, match="not available yet"):
        engines.choose("speech", "whisper-small")
    assert engines.chosen("speech")["id"] == "parakeet-0.6b"          # a saved choice that is no longer built is ignored
    with pytest.raises(ValueError, match="not for this job"):
        engines.choose("vision", "parakeet-0.6b")
    config.save_user_settings({"vision_engine": "nonsense"})
    assert engines.chosen("vision")["id"] == "qwen3-vl-8b"


def test_installed_is_read_from_the_cache_size(tmp_path):
    e = engines.by_id("siglip")
    assert engines.status(e)["state"] == "missing"
    root = tmp_path / "hub" / "models--google--siglip-base-patch16-224"
    (root / "blobs").mkdir(parents=True)
    (root / "blobs" / "abc.incomplete").write_bytes(b"x" * int(0.5e9))             # a download in progress
    assert engines.status(e)["state"] == "partial" and 0.2 < engines.status(e)["progress"] < 0.4
    (root / "blobs" / "abc.incomplete").unlink()
    (root / "snapshots" / "rev1").mkdir(parents=True)
    (root / "snapshots" / "rev1" / "model.safetensors").write_bytes(b"x" * int(1.6e9))
    assert engines.status(e)["state"] == "installed"


def test_download_runs_in_the_background_and_reports_errors(monkeypatch):
    import threading
    gate = threading.Event()
    monkeypatch.setattr(engines.hardware, "free_gb", lambda p: 500.0)
    monkeypatch.setattr(engines, "_fetch", lambda repo: gate.wait(5))
    e = engines.by_id("siglip")
    assert engines.download("siglip")["state"] == "running"
    assert engines.download("siglip")["state"] == "running"          # a second press starts nothing new
    gate.set()
    engines._dl_thread_join = [t.join(5) for t in threading.enumerate() if t.name == "download-siglip"]
    assert engines._dl[e["repo"]]["state"] == "done"
    monkeypatch.setattr(engines, "_fetch", lambda repo: (_ for _ in ()).throw(OSError("no network")))
    engines._dl.clear()
    engines.download("siglip")
    [t.join(5) for t in threading.enumerate() if t.name == "download-siglip"]
    s = engines.status(e)
    assert s["state"] == "error" and "no network" in s["error"]


def test_a_download_that_cannot_fit_is_refused(monkeypatch):
    monkeypatch.setattr(engines.hardware, "free_gb", lambda p: 3.0)
    with pytest.raises(ValueError, match="not enough free space"):
        engines.download("qwen3-vl-8b")


def test_view_lists_every_job():
    v = engines.view(CARD12)
    assert set(v["jobs"]) == {"speech", "vision", "embed"}
    assert [r["id"] for r in v["jobs"]["vision"] if r["recommended"]] == ["qwen3-vl-8b"]
    assert any(r["chosen"] for r in v["jobs"]["speech"])


class Word:
    def __init__(self, w, a, z):
        self.word, self.start, self.end = w, a, z


class Seg:
    def __init__(self, text, a, z, words):
        self.text, self.start, self.end, self.words = text, a, z, words


def test_whisper_segments_become_the_transcript_format():
    import transcribe
    segs = [Seg(" It matters a lot. ", 0.0, 1.5, [Word(" It", 0.0, 0.2), Word(" matters", 0.2, 0.6), Word(" a", 0.6, 0.7), Word(" lot.", 0.7, 1.4)]),
            Seg("Next.", 1.6, 2.0, [Word("Next.", 1.6, 2.0), Word(" ", 2.0, 2.0)])]
    words, segments, text = transcribe.words_from(segs)
    assert [w["word"] for w in words] == ["It", "matters", "a", "lot.", "Next."]
    assert words[3] == {"word": "lot.", "start": 0.7, "end": 1.4} and text == "It matters a lot. Next."
    assert segments[0] == {"text": "It matters a lot.", "start": 0.0, "end": 1.5}


def test_without_parakeet_the_reader_falls_back_to_whisper(monkeypatch, capsys):
    import transcribe
    made = []
    monkeypatch.setattr(transcribe, "Whisper", lambda repo: made.append(repo) or "whisper")
    monkeypatch.setattr(transcribe, "_parakeet_unavailable", lambda: "there is no Nvidia graphics card")
    monkeypatch.setattr(transcribe.hardware if hasattr(transcribe, "hardware") else hardware, "gpus", lambda: [])
    assert transcribe.load_model() == "whisper" and made == ["Systran/faster-whisper-small"]
    assert "not available" in capsys.readouterr().out


def test_a_hyphen_or_apostrophe_joins_the_word_before_it():
    import transcribe
    segs = [Seg(" The G-code, it's here", 0.0, 2.0, [Word(" The", 0.0, 0.2), Word(" G", 0.2, 0.4), Word("-code,", 0.4, 0.8), Word(" it", 1.0, 1.1), Word("'s", 1.1, 1.3), Word(" here", 1.4, 1.8)])]
    words, _, _ = transcribe.words_from(segs)
    assert [w["word"] for w in words] == ["The", "G-code,", "it's", "here"]
    assert words[1]["start"] == 0.2 and words[1]["end"] == 0.8
