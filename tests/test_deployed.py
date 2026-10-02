"""``deployed <commit>``: the project's deploy check says whether a fix is served before it is announced."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

COMMIT = "0123abc4567def"


def set_check(command: str | None) -> None:
    """Write ``deploy_check`` into the project file of the current directory (``None`` removes it)."""
    path = Path.cwd() / ".bugs-bot.json"
    data = json.loads(path.read_text())
    data.pop("deploy_check", None)
    if command is not None:
        data["deploy_check"] = command
    path.write_text(json.dumps(data))


def test_a_check_that_passes_says_deployed_yes(run, bound, capsys):
    set_check(f'test "$BUGS_BOT_COMMIT" = {COMMIT}')

    assert run("deployed", COMMIT) == 0

    assert capsys.readouterr().out.strip() == "deployed=yes"


def test_a_check_that_fails_says_deployed_no(run, bound, capsys):
    set_check(f'test "$BUGS_BOT_COMMIT" = {COMMIT}')

    assert run("deployed", "fedcba9876") == 1

    assert capsys.readouterr().out.strip() == "deployed=no"


def test_without_a_check_the_launchers_word_decides(run, bound, capsys):
    set_check(None)

    assert run("deployed", COMMIT) == 2

    assert capsys.readouterr().out.strip() == "deployed=unknown: the launcher's word decides"


def test_the_check_runs_in_the_repository_whatever_the_current_directory(run, bound, tmp_path, monkeypatch, capsys):
    out = tmp_path / "where"
    set_check(f'pwd -P > "{out}"')
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)

    assert run("deployed", COMMIT, "--project", "demo") == 0

    assert out.read_text().strip() == str((tmp_path / "repo-demo").resolve())


@pytest.mark.parametrize(
    "bad",
    ["abc; touch pwned", "$(touch pwned)", "abc", "x" * 41, "", "abcdef1;touch pwned", "abcdef1\n", "abcdef1 ", "abcdef"],
)
def test_a_commit_that_is_not_a_hash_is_refused_before_anything_runs(run, bound, bad, capsys):
    set_check("touch ran")

    assert run("deployed", bad) == 1

    assert not (Path.cwd() / "ran").exists() and not (Path.cwd() / "pwned").exists()
    assert "deployed=" not in capsys.readouterr().out


@pytest.mark.parametrize("good", ["abcdef1", "a" * 40, "ABCDEF1"])
def test_seven_to_forty_hex_digits_are_accepted(run, bound, good, capsys):
    set_check("true")

    assert run("deployed", good) == 0

    assert capsys.readouterr().out.strip() == "deployed=yes"
