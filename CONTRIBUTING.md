# Contributing

Read [CLAUDE.md](CLAUDE.md): it holds the rules for changing the code (code and data are kept apart, plan files are written through `projectstore`, there are no approval gates,
every change comes with a test) and the map of the code is in [docs/how-it-works.md](docs/how-it-works.md).

Run the tests before you send a change:

```bash
python -m pytest            # about a minute, touches no real data
python -m pytest -m ui      # the browser tests (needs: playwright install chromium)
```

Never test on your real video folders: start a second server on another port with `WOOTS_DATA_ROOT` pointed at a temporary folder (see CLAUDE.md).
