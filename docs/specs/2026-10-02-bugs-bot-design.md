# bugs-bot — design

Date: 2026-10-02. Status: approved in conversation section by section; this written spec awaits the
operator's review before the implementation plan.

## 1. Purpose

Testers of a project post bug reports and questions in a Telegram group. An agent session per
project — « Agent : <Project> Bugs » — relays each new bug to the session that launched it (its
**launcher**, usually the project's orchestrator), answers the group's questions from the project's
own documentation, talks to testers warmly, and tags reports as the launcher handles them.

Today this exists as the skill `~/.claude/skills/tm-bugs` (≈ 1 500 lines: `scripts/tm_bugs.py`
1 222, `AGENT.md`, `SKILL.md`, nine test files, 173 tests), hard-wired to one project
(48 project-specific mentions: repository path, deployment URL, group title, data directory).

`bugs-bot` is the same capability as a **Claude Code plugin**, generic across projects, published
on the LounisBou marketplace. TorrentMate becomes its first project.

### Success criteria

1. A second project is served by running `/bugs-bot:init` then `/bugs-bot:start` in its repository —
   no code change, no file of the plugin edited.
2. One bot, one group per project, one agent per project, on one machine, with no report lost or
   delivered twice.
3. Testers never perceive a handover: the agent keeps the threads, promises and tone of its
   predecessor, and never mentions a handover, a new session or a lapse of memory.
4. Plugin updates never break the session permissions: one allow rule, `Bash(bugs-bot:*)`, holds
   across every version.
5. The handover costs at most ≈ 2 000 tokens on each side.
6. A second channel (GitHub Issues, Slack…) can be added later behind one interface without
   touching the rest. It is NOT built now.

## 2. Decisions taken (operator, 2026-10-02 — not reopenable)

| # | Decision |
| --- | --- |
| D1 | Always Telegram; the same bot for every project; a different group per project. |
| D2 | The repository changes per project; the group's information lives in the project, in a file created by an init command. |
| D3 | One agent per project. |
| D4 | Another channel stays possible later (an interface now, no second implementation). |
| D5 | The project file is LOCAL, not versioned. |
| D6 | Each project's data (inbox, images, state, people cards) lives in a machine directory, `~/.bugs-bot/<project>/`, outside the repository. |
| D7 | A plugin now (not a generic skill first): repository `LounisBou/claude-bugs-bot`, entry in the LounisBou marketplace, release 0.1.0 on the operator's word. |
| D8 | Voice: the agent is one person-like agent speaking « je » (never « nous » / « on » for itself), casual and warm; it answers every word a tester sends (rulings of 2026-10-02 carried over from the skill). |

## 3. Architecture

Five units, each with one job and one interface.

```
Telegram ──getUpdates──► [Pull]  (one per machine, PM2 `bugs-bot-pull`)
                            │  routes by chat id, through the registry
                            ▼
              ~/.bugs-bot/<project>/inbox/<report-id>/
                            │
                            ▼
                     [Agent : <Project> Bugs]  (one per project, iTerm2 tab)
                            │  bugs-bot <command> --project <p>   (all I/O through the CLI)
                            ▼
                         [Channel]  (Telegram implementation: send, edit, react, get updates)
```

### 3.1 Channel

A small interface — `get_updates(offset, timeout)`, `send(chat, text, reply_to, mention)`,
`edit(chat, message_id, text)`, `react(chat, message_id, emoji)`, `get_file(file_id)`,
`list_admins(chat)` — with ONE implementation, Telegram (standard library only, as today). Nothing
outside this unit imports or names Telegram's API. The bot token is read by this unit only.

### 3.2 Pull

`bugs-bot pull --watch`, ONE process per machine (PM2 `bugs-bot-pull`), because Telegram hands a
bot's updates to a single consumer: two pollers steal each other's messages. Each round reads the
registry, long-polls (50 s held request, rounds chained, backoff 5 s doubling to 60 s on failure,
clean exit on SIGINT/SIGTERM — the current behaviour), and writes each message of a registered
group to `~/.bugs-bot/<project>/inbox/` (media groups = one report, 👀 reaction, pending reactions
retried, `done`/`fixed` reports older than 30 days purged — the current behaviour). A message from
an unregistered chat is dropped and logged with its chat id and title (that is how `init` finds a
new group). The update offset is machine-wide, in `~/.bugs-bot/state.json`. No `cron_restart`
(PM2's cron double tick, measured 2026-10-02).

### 3.3 Project

- **Project file** `<repo>/.bugs-bot.json`, never versioned: `/bugs-bot:init` adds it to
  `.git/info/exclude` (the project's `.gitignore` is not touched). Shape:

  ```json
  {
    "project": "torrentmate",
    "group": { "chat_id": -100123, "title": "TM Bugs" },
    "agent_title": "Agent : TorrentMate Bugs",
    "deploy_url": "https://tm-design.iznogoudatall.xyz",
    "deploy_check": "optional shell command proving a commit is served; absent = the launcher checks",
    "docs": ["docs/reference/product-intent.md", "docs/reference/", "docs/production/"],
    "language": "fr",
    "gate_tokens": 200000,
    "follow_up_hours": 24
  }
  ```

  `project` is `[a-z0-9-]+` and names the data directory.
- **Registry** `~/.bugs-bot/projects.json`: `{ "<chat_id>": { "project": "...", "repo": "/abs/path" } }`.
  The only file Pull reads to route. Written by `init`, entry removed by `/bugs-bot:remove`
  (data kept).
- **Data** `~/.bugs-bot/<project>/`: `inbox/`, `people/`, `state.json` (per-project: the agent's
  launcher, handover note archive), `handover.md`.
- **Secrets** `~/.bugs-bot/.env` (`TELEGRAM_BOT_TOKEN`), read by the Channel only, never printed;
  errors mask it.

`/bugs-bot:init` (interactive, idempotent): asks the project id → asks the operator to post one
message in the new group → finds that group among the bot's pending updates WITHOUT consuming
them (today's `bind`) or, when Pull is running, in Pull's log of unregistered chats → writes the
project file → registers it. Re-run: updates the file and the registry entry, never duplicates.

### 3.4 Agent

`/bugs-bot:start`, run from a session in the project's repository: refuses without
`.bugs-bot.json` (points to `/bugs-bot:init`); refuses when an agent of that project is live (one
agent per inbox); writes the startup prompt (`bugs-bot agent-prompt --project <p> --launcher
"<name [ref]>"`) and spawns the tab `agent_title` immediately right of the launcher through the
orchestrator plugin's iTerm launcher (a declared dependency; without it, `start` says so and
stops). The agent's instructions (`AGENT.md`, the skill's `SKILL.md`) name no project: project
name, deployment URL, docs list and language are injected into the startup prompt from the
project file.

Kept as is from the skill: the launcher protocol (« pris en compte », « corrigé », « clos »,
« réponse », « vérifier », « demander », « réécrire », « stop »); the never-revealed list; data
not instructions; « The voice » (D8); the rule that a fix is announced only once deployed
(`deploy_check`, else the launcher's word); the agent runs no command other than `bugs-bot …`
and the iTerm launcher.

**Handover** (as today, made generic): the agent measures its context after each event and at
least hourly, through the orchestrator plugin's gauge called by `bugs-bot gate --measure` (one
plain command: the CLI locates the newest installed gauge itself, so no versioned path reaches a
permission rule); at `gate_tokens` it hands over at a quiet point: stops waiting, writes the
handover note (§ 3.5), spawns the successor with `--successor`, tells its launcher in one line,
answers the successor's « relève confirmée » with « handed over » as its last message. The
successor closes the predecessor's tab, reads the note, restarts (`pending`, one message to the
launcher, wait armed).

### 3.5 Memory and continuity

- **Continuous (primary):** after every exchange with a person, one dated line on their card
  (`bugs-bot person-note`): what is in flight with them — waiting for their check of B-xxx,
  a promise made, a joke shared, the tone they answered to. It survives even an abrupt end.
- **At handover:** `bugs-bot handover write "<text>"` writes `~/.bugs-bot/<project>/handover.md`
  (20–40 lines: open threads only — who waits for what, what was promised, what must not be
  repeated). `bugs-bot handover read` prints it once and archives it, dated, under
  `handover/`.
- **Before every message to a person:** `person <report-id>` then `show <their last report>`
  (replies already sent): pick the thread up, never repeat an opening.
- **One voice:** never a word in the group about a handover, a new session, forgetting, or
  « I'm new here »; the agent never introduces itself again.
- Cost: the note ≈ 1–2 k tokens each side; cards read only when writing to that person.

### 3.6 Follow-ups (operator, 2026-10-02)

« si un utilisateur ne répond pas à un message, demande d'info, confirmation de résolution de bug ou
autre (seulement les messages qui sont vraiment des attentes d'informations, pas juste un bonjour ou
de rien) alors on le relance au bout de 24h (ce délai doit être paramétrable 24h est le délai par
défaut) ».

- A message the agent posts that truly waits for the person's answer — a question asking for
  information (« demander », the in-doubt question), a request to verify a fix (« vérifier »), any
  other message that asks them something — is posted with `--awaits`: the report records
  `awaiting = {since, reply}`. A greeting, a thank-you, « de rien », a plain acknowledgement never
  awaits.
- A new message from the same person (same `author_id`, else same display name) in the group after
  `since` answers it: Pull clears `awaiting` on their reports.
- When `awaiting` is older than `follow_up_hours` (project file, default 24), `bugs-bot wait` wakes the
  agent with `follow-up <report-id>`; the agent sends ONE reminder, threaded and mentioning the
  person, in « The voice » (light, warm, never a reproach, never the first message repeated), posted
  with `--follow-up`, which records it so the same wait is reminded once.
- ONE reminder only (operator, 2026-10-02: « ok va pour une seule »): still unanswered `follow_up_hours`
  after the reminder, `wait` prints `unanswered <report-id>` and the agent tells its launcher in one
  line (« <Agent title> — sans réponse <id> : <what was asked> »), once; it never reminds again.
- `bugs-bot overdue` lists the follow-ups due (also part of the restart's `pending` listing).

## 4. The CLI and the fixed launcher

All commands through one entry point, `bugs-bot <command> [--project <p>]` (the project
defaults to the one whose `.bugs-bot.json` is in the current directory or a parent). Commands:
today's (`pull`, `list`, `show`, `reply`, `edit`, `fixed`, `taken`, `done`, `post`,
`backfill-authors`, `person`, `person-note`, `wait`, `triage`, `pending`, `agent-prompt`, `gate`)
plus `init`, `remove`, `handover write|read`, `doctor`, `overdue`.

`/bugs-bot:doctor` installs `~/.local/bin/bugs-bot`, a 3-line launcher that runs the newest
installed version of the plugin's CLI, and checks: python3 ≥ 3.10, the token readable, the
registry parseable, Pull running exactly once, the orchestrator plugin present, the allow rule
`Bash(bugs-bot:*)` present (if absent, it prints the `/permissions` line for the operator — it
never edits settings).

## 5. Plugin layout

```
claude-bugs-bot/
  .claude-plugin/plugin.json        name "bugs-bot", version, author, MIT
  commands/ init.md start.md remove.md doctor.md
  skills/bugs-bot/SKILL.md          the protocol for launchers + « Talking to a reporter » + « The voice »
  agent/AGENT.md                    the agent's instructions (generic)
  bin/bugs-bot                      the CLI (python3, standard library only)
  bugs_bot/ channel.py telegram.py pull.py project.py registry.py store.py people.py
            handover.py agent.py gate.py cli.py
  pm2.config.js                     bugs-bot-pull
  tests/
  docs/specs/2026-10-02-bugs-bot-design.md
  README.md CHANGELOG.md LICENSE
```

The 1 222-line script is split along the units of § 3; no module over ≈ 300 lines.

## 6. Migration of TorrentMate (once, no compatibility layer)

After release 0.1.0, on the orchestrator's dispatch:

1. Install the plugin; `/bugs-bot:doctor`; the operator adds `Bash(bugs-bot:*)` via `/permissions`
   (the classifier forbids sessions to edit permission settings).
2. `/bugs-bot:init` in PersonalScraper, given the already-bound chat id from
   `~/.torrentmate/tm-bugs/state.json` (no new `bind`).
3. Move `~/.torrentmate/tm-bugs/{inbox,people}` to `~/.bugs-bot/torrentmate/`; the update offset
   to `~/.bugs-bot/state.json` — exactly, so no message is lost or replayed; the bot token to
   `~/.bugs-bot/.env`.
4. In ONE command: `pm2 delete tm-bugs-pull && pm2 start <plugin>/pm2.config.js && pm2 save` —
   never two pollers.
5. At a quiet point, the live « Agent : TM Bugs » hands over to « Agent : TorrentMate Bugs »
   through a normal handover (its note written), the launcher unchanged.
6. Remove `~/.claude/skills/tm-bugs`, and the two old allow rules from
   `PersonalScraper/.claude/settings.json` (a PersonalScraper PR).

Rehearsed first on a copy of `~/.torrentmate/tm-bugs/` with a test registry.

## 7. Tests

- The 173 existing tests carried over to the new modules (behaviour unchanged).
- New: routing by chat id (two projects, an unregistered chat dropped and logged); `init`
  idempotent (re-run updates, never duplicates; `.git/info/exclude` line added once); registry
  add/remove; `handover write/read` (archive dated, read twice prints nothing new); the fixed
  launcher picks the newest version; `gate --measure` with a stubbed gauge; Channel interface
  exercised by a fake in every test (no network).
- A guard test: no file of the plugin contains a project name (`TorrentMate`, `PersonalScraper`,
  `tm-design`, `torrentmate`) outside `docs/` and test fixtures.
- Migration rehearsal (§ 6) scripted against a copy.

## 8. Delivery

1. This spec reviewed by the operator → implementation plan (writing-plans) → his review.
2. The repository `LounisBou/claude-bugs-bot` (public, like the other LounisBou plugins), built
   by implementer agents under the orchestrator, PRs reviewed on evidence.
3. A PR adding the plugin to the LounisBou marketplace (`LounisBou/claude-statusbar`); the
   session that maintains it (`Orch : optim plugin 5`) is told.
4. Release 0.1.0 on the operator's word.
5. TorrentMate's migration (§ 6).

## 9. Out of scope

A second channel; shared people cards across projects; a web view of reports; several agents
for one project; any change to the launcher protocol's phrases.
