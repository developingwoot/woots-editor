import json

import pytest

import appsetup
import config


@pytest.fixture
def settings(tmp_path, monkeypatch):
    f = tmp_path / "s" / "settings.json"
    monkeypatch.setenv("WOOTS_SETTINGS_FILE", str(f))
    return f


def test_settings_are_saved_per_user_and_merged(settings):
    config.save_user_settings({"data_root": "D:/a"})
    config.save_user_settings({"music_dir": "D:/m"})
    assert json.loads(settings.read_text()) == {"data_root": "D:/a", "music_dir": "D:/m"}
    config.save_user_settings({"music_dir": ""})                       # blank = back to the default
    assert config.user_settings() == {"data_root": "D:/a"}


def test_user_settings_rank_below_env_and_local_file(settings, monkeypatch):
    config.save_user_settings({"sfx_dir": str(settings.parent / "mine")})
    monkeypatch.delenv("WOOTS_SFX_DIR", raising=False)
    assert config._pick("WOOTS_SFX_DIR", "sfx_dir", "x") == config.Path(str(settings.parent / "mine"))
    monkeypatch.setenv("WOOTS_SFX_DIR", str(settings.parent / "env"))
    assert config._pick("WOOTS_SFX_DIR", "sfx_dir", "x").name == "env"


def test_fresh_install_needs_setup_until_a_folder_is_named(settings, monkeypatch):
    monkeypatch.delenv("WOOTS_DATA_ROOT")
    monkeypatch.setattr(config, "_DEFAULT_DATA_ROOT", str(settings.parent / "nowhere"))
    monkeypatch.setattr(config, "_local", lambda: {})
    assert config.needs_setup()
    config.save_user_settings({"data_root": str(settings.parent)})
    assert not config.needs_setup()


def test_a_missing_folder_is_created_and_a_file_is_refused(tmp_path):
    p = appsetup.check_folder(str(tmp_path / "new" / "deep"), make=True)
    assert p.is_dir()
    with pytest.raises(ValueError, match="does not exist"):
        appsetup.check_folder(str(tmp_path / "other"))
    (tmp_path / "f.txt").write_text("x")
    with pytest.raises(ValueError, match="file, not a folder"):
        appsetup.check_folder(str(tmp_path / "f.txt"), make=True)
    with pytest.raises(ValueError):
        appsetup.check_folder("  ")


def test_save_validates_before_writing(settings, tmp_path):
    with pytest.raises(ValueError, match="unknown setting"):
        appsetup.save({"python": "x"})
    assert not settings.exists()
    appsetup.save({"music_dir": str(tmp_path / "Music")})
    assert (tmp_path / "Music").is_dir()
    assert config.user_settings()["music_dir"] == str(tmp_path / "Music")


def test_claude_sign_in_state_is_read_from_auth_status():
    assert appsetup.parse_signed_in('{"loggedIn": true, "email": "a@b.c"}', 0)
    assert not appsetup.parse_signed_in('{"loggedIn": false}', 1)
    assert not appsetup.parse_signed_in("Not logged in", 1)
    assert appsetup.parse_signed_in("Logged in as someone", 0)
    assert "a@b.c" in appsetup.account_line('{"loggedIn": true, "email": "a@b.c"}')


def test_missing_claude_command_gives_install_help(monkeypatch):
    import builder
    def gone():
        raise RuntimeError("the claude command was not found")
    monkeypatch.setattr(builder, "find_claude", gone)
    s = appsetup.claude_status()
    assert not s["installed"] and "claude.com" in s["how"]
