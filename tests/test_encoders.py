import encoders


def test_nvenc_settings_become_x264_settings():
    nv = ["-c:v", "h264_nvenc", "-preset", "p6", "-rc", "vbr", "-cq", "19", "-b:v", "0"]
    assert encoders.to_x264(nv) == ["-c:v", "libx264", "-preset", "medium", "-crf", "19"]


def test_nvenc_only_options_are_dropped_and_others_kept():
    nv = ["-c:v", "h264_nvenc", "-preset", "p7", "-tune", "hq", "-rc", "vbr", "-cq", "15", "-b:v", "0", "-maxrate", "16M", "-bufsize", "32M",
          "-spatial-aq", "1", "-temporal-aq", "1", "-rc-lookahead", "24", "-profile:v", "high", "-forced-idr", "1", "-bf", "0"]
    assert encoders.to_x264(nv) == ["-c:v", "libx264", "-preset", "slow", "-crf", "15", "-maxrate", "16M", "-bufsize", "32M",
                                    "-rc-lookahead", "24", "-profile:v", "high", "-bf", "0"]


def test_a_real_x264_tune_is_kept():
    assert encoders.to_x264(["-tune", "film"]) == ["-tune", "film"]


def test_adapt_keeps_nvenc_when_it_opens(monkeypatch):
    monkeypatch.setattr(encoders, "_nvenc", True)
    nv = ["-c:v", "h264_nvenc", "-preset", "p3", "-cq", "28"]
    assert encoders.adapt(nv) == nv


def test_adapt_falls_back_when_nvenc_does_not_open(monkeypatch):
    monkeypatch.setattr(encoders, "_nvenc", False)
    assert encoders.adapt(["-c:v", "h264_nvenc", "-preset", "p3", "-cq", "28"]) == ["-c:v", "libx264", "-preset", "veryfast", "-crf", "28"]


def test_the_probe_says_no_when_ffmpeg_fails(monkeypatch):
    class R:
        returncode = 1
    monkeypatch.setattr(encoders, "_nvenc", None)
    monkeypatch.setattr(encoders.subprocess, "run", lambda *a, **k: R())
    assert encoders.nvenc_available() is False
    monkeypatch.setattr(encoders, "_nvenc", None)
    def boom(*a, **k): raise OSError("no ffmpeg")
    monkeypatch.setattr(encoders.subprocess, "run", boom)
    assert encoders.nvenc_available() is False
