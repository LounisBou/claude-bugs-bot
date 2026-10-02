"""The handover note: written once by the agent at the gate, read once by its successor."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from samples import BASE_DATE

from bugs_bot.handover import read_note, write_note
from bugs_bot.store import Store

NOTE = "Laura attend sa vérification de B-12.\nPromis à Mathis : une réponse demain."


def test_write_then_read_prints_the_note_once(run, bound, capsys):
    assert run("handover", "write", NOTE, now=BASE_DATE) == 0
    assert capsys.readouterr().out.strip() == str(bound / "handover.md")

    assert run("handover", "read", now=BASE_DATE + 60) == 0

    assert capsys.readouterr().out.rstrip("\n") == NOTE


def test_read_archives_the_note_dated_and_records_it_in_the_state(run, bound):
    run("handover", "write", NOTE, now=BASE_DATE)

    run("handover", "read", now=BASE_DATE + 60)

    archive = bound / "handover" / "20261002-083100.md"
    assert archive.read_text() == NOTE + "\n"
    assert not (bound / "handover.md").exists()
    state = json.loads((bound / "state.json").read_text())
    assert state["handovers"] == [{"read": "2026-10-02T08:31:00+00:00", "archive": str(archive)}]


def test_read_twice_prints_nothing_new_and_keeps_the_note(run, bound, capsys):
    # Review Focus 5: a successor that crashed half-way reads again.
    run("handover", "write", NOTE, now=BASE_DATE)
    run("handover", "read", now=BASE_DATE + 60)
    capsys.readouterr()

    assert run("handover", "read", now=BASE_DATE + 120) == 0

    out = capsys.readouterr().out
    assert NOTE not in out and out.strip() == "no handover note"
    assert (bound / "handover" / "20261002-083100.md").read_text() == NOTE + "\n"
    assert len(json.loads((bound / "state.json").read_text())["handovers"]) == 1


def test_write_refuses_while_an_unread_note_exists(run, bound, capsys):
    # Review Focus 5: never overwrite a note nobody has read.
    run("handover", "write", NOTE, now=BASE_DATE)

    assert run("handover", "write", "autre chose", now=BASE_DATE + 60) == 1

    assert "unread" in capsys.readouterr().err
    assert (bound / "handover.md").read_text() == NOTE + "\n"


def test_write_after_a_read_is_accepted(run, bound):
    run("handover", "write", NOTE, now=BASE_DATE)
    run("handover", "read", now=BASE_DATE + 60)

    assert run("handover", "write", "la suite", now=BASE_DATE + 120) == 0

    assert (bound / "handover.md").read_text() == "la suite\n"


def test_write_refuses_an_empty_note(run, bound):
    assert run("handover", "write", "  \n ") == 1

    assert not (bound / "handover.md").exists()


def test_two_reads_in_the_same_second_keep_both_archives(bound):
    store = Store(bound)
    write_note(store, "un", BASE_DATE)
    read_note(store, BASE_DATE)
    write_note(store, "deux", BASE_DATE)

    assert read_note(store, BASE_DATE) == "deux\n"

    assert sorted(p.read_text() for p in (bound / "handover").iterdir()) == ["deux\n", "un\n"]


def test_read_without_a_note_returns_none_and_writes_nothing(bound):
    assert read_note(Store(bound), BASE_DATE) is None

    assert not (bound / "state.json").exists()


AGENT_MD = Path(__file__).resolve().parent.parent / "agent" / "AGENT.md"


@pytest.mark.parametrize("phrase", [
    "handover write", "handover read", "## Memory and continuity", "after every exchange", "I'm new here",
    "never introduce yourself again", "20–40 lines",
])
def test_the_agent_knows_its_memory_and_its_note(phrase):
    assert phrase in AGENT_MD.read_text()
