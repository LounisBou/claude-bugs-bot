#!/usr/bin/env python3
"""Move the data of the previous single-project inbox into a bugs home, once.

The legacy layout is ``<legacy-home>/{inbox/, people/, state.json}`` with ``state.json`` holding
``chat_id``, ``offset`` and ``posts``, and the bot token in an ``.env`` file of its own. The target
is ``<bugs-home>/<project>/{inbox/, people/, state.json}`` plus the machine-wide
``<bugs-home>/state.json`` (the update offset) and ``<bugs-home>/.env`` (the token).

Every precondition is checked before the first write, so a refused run changes nothing. The token
value is never printed, and ``.env`` is created with mode 0600 from the start.

Standard library only; it does not import the plugin, so it runs from any checkout.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
from pathlib import Path

PROJECT_ID = re.compile(r"[a-z0-9-]+")
PROJECT_FILE = ".bugs-bot.json"
TOKEN_KEY = "TELEGRAM_BOT_TOKEN"
MOVED_DIRS = ("inbox", "people")


class Refused(Exception):
    """A precondition failed: nothing has been written."""


def read_json_object(path: Path, what: str) -> dict:
    """Return the JSON object in ``path``.

    Raises:
        Refused: If the file is missing, unreadable or not a JSON object.
    """
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        raise Refused(f"cannot read {what} {path}: {exc}") from None
    if not isinstance(data, dict):
        raise Refused(f"{what} {path} is not a JSON object")
    return data


def check_offset(state: dict) -> int | None:
    """Return the legacy offset as it is: an integer >= 0, or ``None`` when absent or null.

    The value is copied, never adjusted: Telegram's offset is already « the next update », so
    ``+ 1`` would lose a message and ``0`` would replay the history.

    Raises:
        Refused: If it is anything else (a ``bool`` is not an offset).
    """
    offset = state.get("offset")
    if offset is None:
        return None
    if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
        raise Refused(f"the legacy offset is not a natural number: {offset!r}")
    return offset


def read_token_line(env_file: Path) -> str:
    """Return the ``TELEGRAM_BOT_TOKEN=...`` line of ``env_file``, verbatim.

    Raises:
        Refused: If the file or the variable is missing. The message never holds the value.
    """
    try:
        lines = env_file.read_text().splitlines()
    except OSError as exc:
        raise Refused(f"cannot read the env file {env_file}: {exc.strerror}") from None
    for line in lines:
        key, sep, value = line.partition("=")
        if sep and key.strip() == TOKEN_KEY and value.strip().strip("'\""):
            return line
    raise Refused(f"{TOKEN_KEY} not found in {env_file}")


def check_repo(repo: Path, project: str, chat_id: object) -> None:
    """Check that ``init`` already bound ``repo`` to this project and to the legacy group.

    Raises:
        Refused: If the project file is missing, names another project or another group.
    """
    data = read_json_object(repo / PROJECT_FILE, "project file")
    if data.get("project") != project:
        raise Refused(f"{repo / PROJECT_FILE} is for project {data.get('project')!r}, not {project!r}")
    bound = (data.get("group") or {}).get("chat_id")
    if chat_id is not None and bound != chat_id:
        raise Refused(f"{repo / PROJECT_FILE} is bound to group {bound!r}, the legacy state to {chat_id!r}")


def write_text_private(path: Path, text: str) -> None:
    """Create ``path`` with mode 0600 from the first byte (no window at the umask's mode)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as handle:
        handle.write(text)
    os.chmod(path, 0o600)  # the umask can only narrow the mode at creation, never set it to anything else; this pins it


def write_json(path: Path, data: dict) -> None:
    """Write JSON atomically: a temp file next to ``path``, then rename."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    os.replace(tmp, path)


def migrate(legacy: Path, bugs_home: Path, project: str, repo: Path, env_file: Path, copy: bool) -> list[str]:
    """Migrate the legacy tree; return one line per thing done.

    Raises:
        Refused: On any failed precondition, before anything is written.
    """
    if not PROJECT_ID.fullmatch(project):
        raise Refused(f"project must match [a-z0-9-]+, got {project!r}")
    state = read_json_object(legacy / "state.json", "legacy state")
    offset = check_offset(state)
    token_line = read_token_line(env_file)
    check_repo(repo, project, state.get("chat_id"))

    target = bugs_home / project
    if target.exists() and any(target.iterdir()):
        raise Refused(f"{target} is not empty: refusing to merge into it")
    for name in ("state.json", ".env"):
        if (bugs_home / name).exists():
            raise Refused(f"{bugs_home / name} already exists: refusing to overwrite it")

    done = []
    write_text_private(bugs_home / ".env", token_line + "\n")
    done.append(f"token line -> {bugs_home / '.env'} (mode 0600)")
    write_json(bugs_home / "state.json", {"offset": offset})
    done.append(f"offset {offset} -> {bugs_home / 'state.json'}")
    posts = state.get("posts")
    if posts:
        write_json(target / "state.json", {"posts": posts})
        done.append(f"{len(posts)} post(s) -> {target / 'state.json'}")
    for name in MOVED_DIRS:
        source = legacy / name
        if not source.is_dir():
            continue
        count = sum(1 for _ in source.iterdir())
        target.mkdir(parents=True, exist_ok=True)
        if copy:
            shutil.copytree(source, target / name)
        else:
            shutil.move(str(source), str(target / name))
        done.append(f"{name}/ ({count} entries) {'copied' if copy else 'moved'} -> {target / name}")
    return done


def main(argv: list[str] | None = None) -> int:
    """Run the migration; return the exit code (0 done, 1 refused)."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--legacy-home", type=Path, required=True, help="the legacy data directory")
    parser.add_argument("--bugs-home", type=Path, required=True, help="the bugs home to fill")
    parser.add_argument("--project", required=True, help="the project id, [a-z0-9-]+")
    parser.add_argument("--repo", type=Path, required=True, help="the repository holding the project file")
    parser.add_argument("--env-file", type=Path, required=True, help="the legacy .env holding the token")
    parser.add_argument("--copy", action="store_true", help="copy inbox/ and people/ instead of moving them")
    args = parser.parse_args(argv)
    try:
        done = migrate(args.legacy_home, args.bugs_home, args.project, args.repo, args.env_file, args.copy)
    except Refused as exc:
        print(f"migration refused: {exc}", file=sys.stderr)
        return 1
    print("\n".join(done))
    return 0


if __name__ == "__main__":
    sys.exit(main())
