"""Tests for routing: one machine-wide Pull serves several projects, each message to its own inbox."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from conftest import read_offset, register, reports
from samples import BASE_DATE, GROUP_ID, OTHER_GROUP_ID, FakeTelegram, message

from bugs_bot.project import PROJECT_FILE
from bugs_bot.registry import Registry
from bugs_bot.store import Machine

STAMP = "20261002-083000"
FAMILY_ID = -1007777777777


def report_json(path: Path) -> dict:
    """Load a report directory's ``report.json``."""
    return json.loads((path / "report.json").read_text())


@pytest.fixture
def two(tmp_path, bugs_home, home, bound):
    """Register a second project, ``other``, next to ``demo``; return its data directory."""
    register(bugs_home, tmp_path / "repo-other", "other", OTHER_GROUP_ID, "Other Bugs")
    return bugs_home / "other"


# -- the registry decides ---------------------------------------------------------------------


def test_pull_with_no_project_registered_says_so_and_never_calls_the_channel(run, home, capsys):
    tg = FakeTelegram([message(10, 100, text="x")])

    assert run("pull", transport=tg) == 0

    out = capsys.readouterr().out
    assert out.count("\n") == 1 and "no project registered" in out
    assert tg.calls == []
    assert not home.exists()


def test_pull_asks_only_for_messages(run, bound):
    tg = FakeTelegram()

    assert run("pull", transport=tg) == 0

    assert [c["allowed_updates"] for c in tg.updates_calls()] == [["message"]]


# -- Review Focus 1: the offset is machine-wide, the reports are per project -------------------


def test_one_batch_of_two_projects_and_an_unregistered_group_lands_each_where_it_belongs(run, two, bound, capsys):
    tg = FakeTelegram(
        [
            message(10, 100, text="bug de demo"),
            message(11, 200, chat_id=OTHER_GROUP_ID, title="Other Bugs", text="bug de other"),
            message(12, 300, chat_id=FAMILY_ID, title="Famille", text="le repas de dimanche"),
        ]
    )

    assert run("pull", transport=tg) == 0

    [demo] = reports(bound)
    [other] = reports(two)
    assert report_json(demo)["text"] == "bug de demo" and demo.name == f"{STAMP}-100"
    assert report_json(other)["text"] == "bug de other" and other.name == f"{STAMP}-200"
    # the unregistered group is noted by id and title, its text is kept nowhere
    seen = Machine(bound.parent).unregistered()
    assert list(seen) == [FAMILY_ID] and seen[FAMILY_ID]["title"] == "Famille"
    assert not any("dimanche" in p.read_text() for p in bound.parent.rglob("*.json"))
    assert capsys.readouterr().err == f"bugs-bot: unregistered chat {FAMILY_ID} 'Famille' dropped\n"
    # one offset, past every update of the batch, whichever project or none it belonged to
    assert read_offset(bound) == 13
    assert not (bound / "state.json").exists() and not (two / "state.json").exists()


def test_two_messages_of_the_same_unregistered_chat_give_one_line_and_one_entry(run, bound, capsys):
    tg = FakeTelegram(
        [message(10, 100, chat_id=FAMILY_ID, title="Famille", text="a"), message(11, 101, chat_id=FAMILY_ID, title="Famille", text="b")]
    )

    assert run("pull", transport=tg) == 0

    assert capsys.readouterr().err.count("unregistered chat") == 1
    assert list(Machine(bound.parent).unregistered()) == [FAMILY_ID]


def test_a_private_chat_is_neither_routed_nor_noted(run, bound, capsys):
    tg = FakeTelegram([message(10, 100, chat_id=5, chat_type="private", title="Izno", text="salut")])

    assert run("pull", transport=tg) == 0

    assert Machine(bound.parent).unregistered() == {}
    assert "unregistered" not in capsys.readouterr().err
    assert reports(bound) == []
    assert read_offset(bound) == 11


def test_a_message_of_a_registered_chat_is_never_noted_as_unregistered(run, bound):
    assert run("pull", transport=FakeTelegram([message(10, 100, text="x")])) == 0

    assert Machine(bound.parent).unregistered() == {}


# -- Review Focus 2: a failure in one project never blocks or duplicates another ---------------


@pytest.mark.parametrize("failing_first", [True, False])
def test_a_failed_download_in_one_project_keeps_the_offset_and_blocks_no_other_project(run, two, bound, failing_first):
    broken = message(10, 100, chat_id=OTHER_GROUP_ID, title="Other Bugs", caption="une image", photo="p1")
    fine = message(11, 101, text="un texte pour demo")
    tg = FakeTelegram([broken, fine] if failing_first else [fine, broken])
    tg.fail_download = True

    assert run("pull", transport=tg) != 0

    # the healthy project's report is on disk although the batch failed, the broken one left nothing
    assert [report_json(p)["text"] for p in reports(bound)] == ["un texte pour demo"]
    assert reports(two) == []
    assert read_offset(bound) is None


def test_the_redelivered_batch_does_not_duplicate_what_the_other_project_already_has(run, two, bound):
    broken = message(10, 100, chat_id=OTHER_GROUP_ID, title="Other Bugs", caption="une image", photo="p1")
    fine = message(11, 101, text="un texte pour demo")
    tg = FakeTelegram([broken, fine])
    tg.fail_download = True
    assert run("pull", transport=tg) != 0
    [demo_first] = reports(bound)
    # the launcher works on it between the two pulls: a retry must not rewrite it
    handled = report_json(demo_first) | {"status": "taken", "kind": "bug"}
    (demo_first / "report.json").write_text(json.dumps(handled))

    tg.fail_download = False
    assert run("pull", transport=tg) == 0

    [demo] = reports(bound)
    # same report, same handling; only the pending 👀 reaction landed meanwhile
    assert demo.name == demo_first.name
    assert {k: v for k, v in report_json(demo).items() if k != "reaction"} == {k: v for k, v in handled.items() if k != "reaction"}
    [other] = reports(two)
    assert report_json(other)["images"] == ["1.jpg"] and (other / "1.jpg").exists()
    assert read_offset(bound) == 12
    # the whole batch was asked for again: the first pull confirmed nothing
    assert [c.get("offset") for c in tg.updates_calls()] == [None, None]


def test_each_report_is_reacted_to_in_its_own_chat(run, two, bound):
    tg = FakeTelegram([message(10, 100, text="a"), message(11, 200, chat_id=OTHER_GROUP_ID, title="Other Bugs", text="b")])

    assert run("pull", transport=tg) == 0

    assert sorted((r["chat_id"], r["message_id"]) for r in tg.reactions) == sorted(
        [(GROUP_ID, 100), (OTHER_GROUP_ID, 200)]
    )


# -- retention is per project ------------------------------------------------------------------


def test_the_30_day_purge_visits_every_registered_project(run, two, bound):
    old = {"status": "done", "date": "2026-08-01T00:00:00+00:00"}
    for data in (bound, two):
        path = data / "inbox" / "20260801-000000-1"
        path.mkdir(parents=True)
        (path / "report.json").write_text(json.dumps(old))

    assert run("pull", now=BASE_DATE) == 0

    assert reports(bound) == [] and reports(two) == []


# -- --project, and the project of the current directory ---------------------------------------


def write_report(data: Path, report_id: str, text: str, chat_id: int) -> None:
    """Drop a minimal report in a project's inbox."""
    path = data / "inbox" / report_id
    path.mkdir(parents=True)
    (path / "report.json").write_text(
        json.dumps(
            {"id": report_id, "chat_id": chat_id, "message_ids": [5], "date": "2026-10-02T08:30:00+00:00", "author": "a",
             "author_id": 1, "author_username": "a", "text": text, "images": [], "status": "seen", "replies": []}
        )
    )


def test_the_project_of_the_current_directory_is_the_default(run, two, bound, capsys):
    write_report(bound, "20261002-083000-1", "du côté demo", GROUP_ID)
    write_report(two, "20261002-083000-2", "du côté other", OTHER_GROUP_ID)

    assert run("list") == 0

    out = capsys.readouterr().out
    assert "du côté demo" in out and "du côté other" not in out


def test_project_overrides_the_current_directory(run, two, bound, capsys):
    write_report(bound, "20261002-083000-1", "du côté demo", GROUP_ID)
    write_report(two, "20261002-083000-2", "du côté other", OTHER_GROUP_ID)

    assert run("list", "--project", "other") == 0

    out = capsys.readouterr().out
    assert "du côté other" in out and "du côté demo" not in out


def test_a_command_never_reaches_another_projects_report(run, two, bound, capsys):
    write_report(bound, "20261002-083000-1", "du côté demo", GROUP_ID)

    assert run("show", "20261002-083000-1", "--project", "other") != 0

    assert "no such report" in capsys.readouterr().err


def test_a_reply_goes_to_the_chat_of_the_project_it_is_for(run, two, bound):
    write_report(two, "20261002-083000-2", "du côté other", OTHER_GROUP_ID)
    tg = FakeTelegram()

    assert run("reply", "20261002-083000-2", "bien reçu", "--project", "other", transport=tg) == 0

    [sent] = tg.sent
    assert sent["chat_id"] == OTHER_GROUP_ID


def test_project_names_a_registered_project_only(run, bound, capsys):
    assert run("list", "--project", "ghost") != 0

    assert "ghost" in capsys.readouterr().err


@pytest.mark.parametrize("bad", ["../demo", "Demo", "a/b"])
def test_project_cannot_name_a_path(run, bound, bad, capsys):
    assert run("list", "--project", bad) != 0

    assert capsys.readouterr().err.startswith("bugs-bot: ")


def test_without_a_project_file_here_or_above_the_command_points_to_init(run, home, tmp_path, monkeypatch, capsys):
    bare = tmp_path / "bare"
    bare.mkdir()
    monkeypatch.chdir(bare)

    assert run("list") == 1

    assert capsys.readouterr().err == "bugs-bot: no .bugs-bot.json here or above: run /bugs-bot:init\n"


def test_pull_needs_no_project_of_the_current_directory(run, bound, tmp_path, monkeypatch):
    bare = tmp_path / "bare"
    bare.mkdir()
    monkeypatch.chdir(bare)

    assert run("pull", transport=FakeTelegram([message(10, 100, text="x")])) == 0

    assert len(reports(bound)) == 1


# -- a group promoted to supergroup gets a new chat id ----------------------------------------


def test_the_registry_and_the_project_file_follow_a_migrated_chat(run, bound, tmp_path, capsys):
    old = message(10, 1, chat_type="group")
    old["message"]["migrate_to_chat_id"] = FAMILY_ID
    tg = FakeTelegram([old, message(11, 2, chat_id=FAMILY_ID, text="après la migration")])

    assert run("pull", transport=tg) == 0

    registry = Registry(bound.parent / "projects.json")
    assert set(registry.entries()) == {FAMILY_ID}
    assert json.loads((tmp_path / "repo-demo" / PROJECT_FILE).read_text())["group"]["chat_id"] == FAMILY_ID
    [rep] = reports(bound)
    assert report_json(rep)["text"] == "après la migration"
    assert "rebound" in capsys.readouterr().out
    # the old id is dead: it is not offered as a new group either
    assert Machine(bound.parent).unregistered() == {}
