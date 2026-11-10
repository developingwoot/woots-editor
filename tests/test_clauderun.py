"""Every background Claude run is built in one place with the same limits."""
import builder
import clauderun


def _st():
    return {"build_model": "m", "build_effort": "low", "build_budget_usd": 2, "critic_model": "m", "critic_effort": "low", "critic_budget_usd": 1}


def _check(cmd):
    assert "--restricted" in cmd and "--strict-mcp-config" in cmd and "dontAsk" in cmd and "--max-budget-usd" in cmd
    allow = cmd[cmd.index("--allowedTools") + 1:cmd.index("--permission-mode")]
    assert "Bash" not in allow and "Bash(*)" not in allow                      # no bare shell
    assert "-p" in cmd and cmd[cmd.index("-p") + 1].startswith("--")          # the prompt is not an argument: it goes in on standard input
    return allow


def test_builder_may_run_only_the_two_hyperframes_commands_and_ffprobe():
    allow = _check(builder.agent_command(_st()))
    bash = [a for a in allow if a.startswith("Bash(")]
    assert any(f"{builder.HF} render *" in a for a in bash) and any(f"{builder.HF} snapshot *" in a for a in bash)
    assert not any(a.endswith(f"{builder.HF} *)") for a in bash) and not any("ffmpeg" in a for a in bash)
    assert "@" in builder.HF and builder.HF.split("@")[-1][0].isdigit()          # a pinned version


def test_critic_cannot_render_or_edit():
    allow = _check(builder.agent_command(_st(), "critic"))
    assert "Edit" not in allow and not any("render" in a for a in allow)


def test_plain_runs_read_and_write_only():
    cmd = clauderun.command("claude", "Read,Write", ["Read", "Write"], "1.0", ["--model", "m", "--effort", "low"])
    assert _check(cmd) == ["Read", "Write"] and cmd[cmd.index("--tools") + 1] == "Read,Write"


def test_the_prompt_reaches_the_run_on_standard_input(tmp_path):
    import sys
    p = clauderun.start([sys.executable, "-c", "import sys; print(len(sys.stdin.read()))"], "x" * 200000, tmp_path, None)
    out, _ = p.communicate(timeout=20)
    assert int(out.strip()) >= 200000
