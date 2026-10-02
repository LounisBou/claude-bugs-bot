"""The slash commands of the plugin: what they may run."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from conftest import REPO_ROOT

COMMANDS = sorted((REPO_ROOT / "commands").glob("*.md"))
# The one invocation that is not `bugs-bot ...`: the first doctor run, before the launcher exists.
BOOTSTRAP = "python3 ${CLAUDE_PLUGIN_ROOT}/bin/bugs-bot doctor"


def test_the_three_commands_exist():
    assert {p.stem for p in COMMANDS} >= {"init", "remove", "doctor"}


@pytest.mark.parametrize("path", COMMANDS, ids=lambda p: p.stem)
def test_a_command_runs_only_bugs_bot_save_doctors_bootstrap(path: Path):
    text = path.read_text()

    for line in text.splitlines():
        stripped = line.strip().removeprefix("allowed-tools:").strip()
        for match in re.finditer(r"python3 [^\s)`]*", stripped):
            assert path.stem == "doctor" and match.group(0).startswith(BOOTSTRAP.split(" doctor")[0])
    assert "$(" not in text and "&&" not in text
    assert text.startswith("---\ndescription: ")
