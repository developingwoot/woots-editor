"""'This computer' on first run: each missing piece gets one plain sentence with the fix."""
import appsetup


class R:
    def __init__(self, out):
        self.stdout = out


def run_ok(args, timeout=20):
    return R("v22.4.0" if "node" in args[0] else "2.1.400 (Claude Code)")


GOOD = {"ffmpeg": "f", "ffprobe": "p", "node": "node", "claude": "claude"}


def rows(**kw):
    a = dict(run=run_ok, tools=GOOD, gpus=[], free=100.0, python=(3, 12, 1))
    a.update(kw)
    return {r["id"]: r for r in appsetup.computer_check(**a)}


def test_a_complete_computer_has_every_tick():
    assert all(r["ok"] for r in rows().values())


def test_each_missing_piece_has_its_sentence_and_fix():
    r = rows(tools={"ffmpeg": None, "ffprobe": None, "node": None, "claude": None}, free=5.0, python=(3, 10, 0))
    for k in ("python", "ffmpeg", "node", "claude", "disk"):
        assert not r[k]["ok"] and r[k]["detail"] and r[k]["fix"], k
    assert "winget" in r["ffmpeg"]["fix"] and "not installed" in r["claude"]["detail"]


def test_old_node_and_old_claude_are_named_with_their_versions():
    r = rows(run=lambda a, t=20: R("v18.2.0" if "node" in a[0] else "2.0.5 (Claude Code)"))
    assert "18.2.0" in r["node"]["detail"] and "2.0.5" in r["claude"]["detail"] and not r["node"]["ok"] and not r["claude"]["ok"]


def test_no_graphics_card_is_not_an_error():
    assert rows(gpus=[])["gpu"]["ok"] and "processor" in rows()["gpu"]["detail"]


def test_update_check_compares_versions_and_never_raises():
    import version
    cur = version.__version__
    assert appsetup.check_update(lambda: {"tag_name": "v99.0.0", "html_url": "u"})["newer"] is True
    assert appsetup.check_update(lambda: {"tag_name": "v" + cur, "html_url": "u"})["newer"] is False

    def boom():
        raise OSError("no network")
    r = appsetup.check_update(boom)
    assert "Could not reach" in r["error"] and "latest" not in r
