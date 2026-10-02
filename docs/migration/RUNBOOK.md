# Migrating the single-project skill `tm-bugs` to the plugin

Spec § 6, as commands. Run **once**, after release 0.1.0, at a quiet point and with the agreement of
the project's orchestrator. The rehearsal comes first and touches nothing real.

`PLUGIN` below is the installed plugin directory (`~/.claude/plugins/cache/lounisbou/bugs-bot/<version>`).
`LEGACY` is `~/.torrentmate/tm-bugs` and `LEGACY_ENV` the `.env` holding the bot token
(`/Users/izno/dev/PersonalScraper/.env`). The token is never printed by any command here; do not
`cat` either `.env`.

## 0. Rehearsal, on a copy

Nothing under the real `~/.bugs-bot`, nothing stopped, nothing started.

```bash
R=$(mktemp -d)
cp -R ~/.torrentmate/tm-bugs "$R/legacy"
git init -q "$R/repo"
CHAT=$(python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['chat_id'])" "$R/legacy/state.json")

# the test registry: the project registered in a scratch home, from a scratch repository
BUGS_BOT_HOME="$R/home" bugs-bot init --project torrentmate --agent-title "Agent : TorrentMate Bugs" \
  --chat-id "$CHAT" --title "TM Bugs" --repo "$R/repo"

python3 "$PLUGIN/docs/migration/tm_bugs_to_bugs_bot.py" --copy \
  --legacy-home "$R/legacy" --bugs-home "$R/home" --project torrentmate \
  --repo "$R/repo" --env-file "$LEGACY_ENV"
```

Compare, each pair must be equal:

```bash
python3 - "$R" <<'PY'
import json, sys
r = sys.argv[1]
print("offset ", json.load(open(f"{r}/legacy/state.json")).get("offset"), json.load(open(f"{r}/home/state.json"))["offset"])
PY
ls "$R/legacy/inbox" | wc -l; ls "$R/home/torrentmate/inbox" | wc -l       # reports
ls "$R/legacy/people" | wc -l; ls "$R/home/torrentmate/people" | wc -l     # people cards
stat -f '%Lp' "$R/home/.env"                                                # 600
BUGS_BOT_HOME="$R/home" bugs-bot list --project torrentmate                # the open reports
```

Then delete the copy, which holds the token: `rm -rf "$R"` and `ls -d "$R"` must fail.

A refusal (`migration refused: …`) changes nothing: read its line, fix, run again. The script refuses a
non-empty project directory, an existing `<bugs-home>/state.json` or `.env`, a project file naming
another project or group, and an offset that is not a natural number.

## 1. Install and check

```
/plugin install bugs-bot@lounisbou
/bugs-bot:doctor
```

The operator adds the allow rule with `/permissions → Allow → Bash(bugs-bot:*)` (a session may not
edit its own permissions). `/bugs-bot:doctor` must pass except « Pull running exactly once ».

## 2. Bind the repository, without a new `bind`

In the project's repository (PersonalScraper), with the chat id already bound by the old skill:

```bash
CHAT=$(python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['chat_id'])" ~/.torrentmate/tm-bugs/state.json)
bugs-bot init --project torrentmate --agent-title "Agent : TorrentMate Bugs" \
  --chat-id "$CHAT" --title "TM Bugs" [--deploy-url …] [--docs …] [--language fr]
```

If the old gate setting was changed, carry it with `--gate-tokens`.

## 3. Move the data

Stop the old Pull first, so that its offset is final and it writes nothing more: a Pull that runs
during the move would confirm updates the new one never sees. It is a stop, not a replacement: there
is still one poller at most.

```bash
pm2 stop tm-bugs-pull
python3 "$PLUGIN/docs/migration/tm_bugs_to_bugs_bot.py" --copy \
  --legacy-home ~/.torrentmate/tm-bugs --bugs-home ~/.bugs-bot --project torrentmate \
  --repo <the PersonalScraper checkout> --env-file "$LEGACY_ENV"
```

`--copy` keeps `~/.torrentmate/tm-bugs` whole until step 6, so that going back is `pm2 delete
bugs-bot-pull && pm2 start tm-bugs-pull`. Drop it for a plain move. Compare the counts as in the
rehearsal, against the real directories.

## 4. One command, never two pollers

```bash
pm2 delete tm-bugs-pull && pm2 start "$PLUGIN/pm2.config.js" && pm2 save
```

Check: `pm2 list` shows `bugs-bot-pull` online and no `tm-bugs-pull`; `bugs-bot doctor` is green;
a message posted in the group becomes a report (`bugs-bot list`) within seconds.

## 5. Hand the agent over

At a quiet point, the launcher tells the live « Agent : TM Bugs » to hand over. Its note is saved
for its successor with `bugs-bot handover write "<the note>"`, then `/bugs-bot:start` launches
« Agent : TorrentMate Bugs » through the normal handover, the launcher unchanged. The old agent's tab
is closed by its successor.

## 6. Clean up

- `rm -rf ~/.claude/skills/tm-bugs` and, once the new setup has run a day, `rm -rf ~/.torrentmate/tm-bugs`.
- A PersonalScraper pull request (from a worktree) removing the two old allow rules from
  `.claude/settings.json`.
