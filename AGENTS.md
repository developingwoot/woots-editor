# Agent instructions

Read [CLAUDE.md](CLAUDE.md): it is the single source for how to work in this repo (code vs data split, how to run and test, rules). It applies to every agent, not just Claude.

Short version:
1. Data paths come from `tools/config.py`; never hardcode a drive or user folder; never write to real video folders while testing.
2. Run `python -m pytest` (the repo's venv) before and after a change.
3. Use proper edit tools, not source-patching scripts.
4. Channel-specific data belongs in the per-user profile, not in code.
