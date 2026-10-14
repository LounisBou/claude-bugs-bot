---
description: Check this machine's bugs-bot setup and install the fixed `bugs-bot` launcher
allowed-tools: Bash(sh ${CLAUDE_PLUGIN_ROOT}/bin/setup doctor:*), Bash(bugs-bot:*)
---

Check the setup and report the verdict.

1. If `bugs-bot` is not yet on the PATH (the first run), or the `python` or
   `interpreter` check fails, run the plugin's setup, which finds a Python 3.10
   or newer, remembers it, then runs doctor through it and installs the launcher:

   ```
   sh ${CLAUDE_PLUGIN_ROOT}/bin/setup doctor --install-launcher
   ```

   It looks for one already on the machine (`python3.14` … `python3.10` and
   `python3` on the PATH, pyenv's versions, Homebrew's prefixes, `uv python
   find`). Only when there is none does it install `uv` into `~/.local/bin` (no
   root, no shell profile edited) and then Python 3.12 with `uv python install`:
   say so when its lines show it did. The system Python is never changed. The
   interpreter is remembered in `~/.bugs-bot/python`; the launcher, PM2's Pull and
   the sessions run it.

   Later runs are `bugs-bot doctor`. An installed launcher whose text differs (an update changed it) is
   replaced by `bugs-bot doctor --install-launcher`, not by a plain `bugs-bot doctor`.
2. Report each line as printed (`ok` or `FAIL`, the check and its detail), then
   what to do about each failure:
   - `python`: Python 3.10 or newer is needed: run the setup line above.
   - `interpreter`: none is remembered, or the remembered one is gone: run the setup line above.
   - `token`: `TELEGRAM_BOT_TOKEN` goes in `~/.bugs-bot/.env`; never print it.
   - `slack token`: `SLACK_BOT_TOKEN` (`xoxb-…`) goes in the same file; never print it.
   - `telegram bot` / `slack bot`: the platform refused the token (Telegram's
     `getMe`, Slack's `auth.test`): the operator puts a valid one in the file.
   - `registry`: the file `~/.bugs-bot/projects.json` is damaged; say so, do not
     edit it.
   - `pull`: exactly one Pull process must run, under PM2; none or two is a fault. When it says PM2
     recorded a versioned path, print its remedy as given: the operator runs `bugs-bot doctor
     --install-launcher`, then `pm2 delete bugs-bot-pull`, then `pm2 start` of the plugin's
     `pm2.config.js`, then `pm2 save`. When it says PM2
     recorded a working directory (not the home directory: the shell that ran `pm2 start` was in a
     directory that may be deleted), print its remedy as given: the operator runs `cd ~`, then
     `pm2 delete bugs-bot-pull`, then the same `pm2 start` and `pm2 save`. When it names both the
     path and the directory, one remedy covers both: `bugs-bot doctor --install-launcher` first, then
     those steps.
   - `orchestrator`: install the orchestrator plugin, 0.49 or later (`/plugin marketplace update lounisbou`, `/plugin update orchestrator@lounisbou`, then restart); `/bugs-bot:start` needs it, and `gate --measure` reads the measure file 0.49 writes.
   - `launcher`: run the first-run line above; a launcher that differs is replaced by
     `bugs-bot doctor --install-launcher`.
   - `allow rule`: the operator adds `Bash(bugs-bot:*)` himself, through
     `/permissions → Allow → Bash(bugs-bot:*)`. A session cannot change its own
     permissions, and doctor never edits a settings file: print the line for him.
3. The exit code is 0 only when every check passes.
