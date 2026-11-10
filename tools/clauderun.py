"""The one place that builds the command for a background Claude run (`claude -p`).

Every run: restricted mode (no code-running tools unless named, the file tools confined to the run's own folder, user settings ignored),
no MCP servers from the host's own setup, nothing asked of a person (`dontAsk`), a money limit, and the prompt on standard input (a
command line is limited to about 32,000 characters on Windows and its arguments are visible to other programs).
"""
import subprocess
import threading

import channel


def command(exe: str, tools: str, allow: list[str], budget, flags: list[str]) -> list[str]:
    """The argument list. `flags` is the model and effort (claudemodels.flags(kind), or ["--model", m, "--effort", e]). The prompt is not in it: see start()."""
    return [exe, "-p", *flags, "--restricted", "--strict-mcp-config", "--tools", tools, "--allowedTools", *allow,
            "--permission-mode", "dontAsk", "--permission-prompts", "none", "--max-budget-usd", str(budget), "--output-format", "stream-json", "--verbose"]


def start(cmd: list[str], prompt: str, cwd, env) -> subprocess.Popen:
    """Start the run with the channel's profile put in front of the prompt, which goes in on standard input."""
    p = subprocess.Popen(cmd, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
    text = channel.prompt(prompt)

    def feed():
        try:
            p.stdin.write(text)
            p.stdin.close()
        except OSError:                                          # the run ended before reading it all
            pass
    threading.Thread(target=feed, daemon=True).start()
    return p
