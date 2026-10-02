"""One update at a time: every change to a report or a card re-reads it under the project's lock, so no writer saves over a change it did not read."""

from __future__ import annotations

import ast
import fcntl
import json
import shutil
import threading
from pathlib import Path

import pytest
from fake_channel import FakeChannel, inbound
from fake_channel import author as fake_author
from fake_channel import batch as fake_batch
from samples import BASE_DATE, GROUP_ID
from test_mention import STAMP, write_report

from bugs_bot import people, pull, replies, reports
from bugs_bot.channel import Attachment, Author
from bugs_bot.errors import BugsError
from bugs_bot.people import record_language, update_card
from bugs_bot.questions import queue_question
from bugs_bot.reports import cmd_done
from bugs_bot.store import EMOJI_SEEN, Machine, Store, locked, update_report

REPORT = f"{STAMP}-5"


def report(home: Path, report_id: str = REPORT) -> dict:
    return json.loads((home / "inbox" / report_id / "report.json").read_text())


class Interleaving(FakeChannel):
    """A channel whose first call of ``method`` runs ``meanwhile`` before answering: another writer, mid-call."""

    def __init__(self, method: str, meanwhile) -> None:
        super().__init__()
        self.method, self.meanwhile = method, meanwhile

    def react(self, chat_id, message_id, emoji):
        super().react(chat_id, message_id, emoji)
        if self.method == "react" and self.meanwhile:
            meanwhile, self.meanwhile = self.meanwhile, None
            meanwhile()


# -- the defect seen on 2026-10-02 -------------------------------------------------------------


def test_pulls_reaction_retry_keeps_the_agents_done_and_reply(bound, bugs_home):
    # Pull retries the 👀 of a report; while the reaction is on the wire, the agent closes it with a reply.
    write_report(bound, 5, author_id=7, status="seen", reaction={"wanted": EMOJI_SEEN, "applied": None, "error": "429"})
    store = Store(bound)
    agent_channel = FakeChannel()
    channel = Interleaving("react", lambda: cmd_done(agent_channel, store, GROUP_ID, REPORT, "C'est voulu, merci !", BASE_DATE))

    pull.cmd_pull(channel, Machine(bugs_home), BASE_DATE + 60)

    after = report(bound)
    assert after["status"] == "done"
    assert [reply["text"] for reply in after["replies"]] == ["C'est voulu, merci !"]
    assert after["reaction"] == {"wanted": EMOJI_SEEN, "applied": EMOJI_SEEN, "error": None}


# -- two writers interleaved -------------------------------------------------------------------

# How long a second writer is given to get through while the first holds the lock: it must not.
BLOCKED = 0.5


class Writer:
    """A second writer started in a thread from inside the first one's change, blocked on the lock until it ends."""

    def __init__(self, write) -> None:
        self.errors: list[BaseException] = []
        self.done = threading.Event()
        self.thread = threading.Thread(target=self._run, args=(write,))

    def _run(self, write) -> None:
        try:
            write()
        except BaseException as exc:  # re-raised in the test's thread by join()
            self.errors.append(exc)
        finally:
            self.done.set()

    def start_and_watch(self) -> bool:
        """Start it, and tell whether it got through while the caller still holds the lock."""
        self.thread.start()
        return self.done.wait(BLOCKED)

    def join(self) -> None:
        self.thread.join()
        if self.errors:
            raise self.errors[0]


def test_two_updates_of_a_report_interleaved_both_land(bound):
    write_report(bound, 5)
    store = Store(bound)
    second = Writer(lambda: update_report(store, REPORT, lambda rep: rep.update(kind="bug")))
    got_through = []

    def first(rep: dict) -> None:
        got_through.append(second.start_and_watch())
        rep["fix_ref"] = "abc1234"

    update_report(store, REPORT, first)
    second.join()

    assert (report(bound).get("fix_ref"), report(bound).get("kind")) == ("abc1234", "bug"), "a change was lost"
    assert got_through == [False], "the second writer did not wait for the lock"


def test_a_card_keeps_the_language_pull_records_while_the_agent_queues_a_question(bound, monkeypatch):
    # The agent queues a question on Laura's card; Pull, meanwhile, records her language from a new message.
    write_report(bound, 5, author_id=7)
    store = Store(bound)
    laura = report(bound)
    pull_writes = Writer(lambda: record_language(store, Author(id=7, username=None, name="Laura", language="fr-FR", is_bot=False)))
    got_through = []
    read = people.card_of

    def card_of_then_pull(*args):
        card = read(*args)
        if not pull_writes.thread.is_alive() and not pull_writes.done.is_set():
            got_through.append(pull_writes.start_and_watch())
        return card

    monkeypatch.setattr(people, "card_of", card_of_then_pull)
    queue_question(store, laura, "Tu es sur quel iPhone ?", BASE_DATE)
    pull_writes.join()

    card = json.loads((bound / "people" / "7.json").read_text())
    assert card.get("language") == "fr", "Pull's language was lost"
    assert [question["text"] for question in card["questions"]] == ["Tu es sur quel iPhone ?"]
    assert got_through == [False], "Pull did not wait for the lock"


def test_a_card_changed_inside_a_report_change_does_not_deadlock(bound):
    # Re-entrance: the same thread nests an update of another file under the lock it holds.
    write_report(bound, 5, author_id=7)
    store = Store(bound)

    def close_and_note(rep: dict) -> None:
        rep["status"] = "done"
        update_card(store, "7", lambda card: card["notes"].append({"date": "d", "text": "closed"}), "Laura", 7)

    update_report(store, REPORT, close_and_note)

    assert report(bound)["status"] == "done"
    assert json.loads((bound / "people" / "7.json").read_text())["notes"] == [{"date": "d", "text": "closed"}]


# -- a report purged meanwhile -----------------------------------------------------------------


def test_a_report_purged_meanwhile_is_refused_and_not_written_back(bound, monkeypatch):
    path = write_report(bound, 5)
    store = Store(bound)
    found = store.report_dir

    def found_then_purged(report_id: str) -> Path:
        # Pull's purge runs between the agent's look at the report and its update.
        where = found(report_id)
        shutil.rmtree(where)
        return where

    monkeypatch.setattr(store, "report_dir", found_then_purged)
    changes = []

    with pytest.raises(BugsError, match=f"no report {REPORT}"):
        update_report(store, REPORT, changes.append)

    assert changes == []
    assert not path.exists(), "the update recreated the purged report"


def test_the_purge_waits_for_an_update_in_progress(bound):
    write_report(bound, 5, status="done", date="2026-07-01T08:30:00+00:00")
    store = Store(bound)
    purge = Writer(lambda: pull.purge_old_done(store, BASE_DATE))
    got_through = []

    def triage(rep: dict) -> None:
        got_through.append(purge.start_and_watch())
        rep["kind"] = "bug"

    update_report(store, REPORT, triage)
    purge.join()

    assert not (bound / "inbox" / REPORT).exists(), "the update wrote the purged report back"
    assert got_through == [False], "the purge did not wait for the lock"


# -- the lock itself ---------------------------------------------------------------------------


def lock_is_free(home: Path) -> bool:
    """Tell whether another process could take the project's lock now (a second open file is one to ``flock``)."""
    with open(home / ".lock", "a") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return False
        fcntl.flock(handle, fcntl.LOCK_UN)
        return True


def test_the_lock_is_a_file_lock_beside_the_inbox_held_until_the_last_exit(bound):
    store = Store(bound)
    with locked(store):
        assert not lock_is_free(bound)
        with locked(store):  # re-entered, not deadlocked
            assert not lock_is_free(bound)
        assert not lock_is_free(bound), "the inner exit released the outer hold"
    assert lock_is_free(bound)
    assert (bound / ".lock").is_file()


def test_an_unknown_report_is_refused_without_creating_anything(tmp_path):
    store = Store(tmp_path / "nowhere")

    with pytest.raises(BugsError, match="no such report"):
        update_report(store, "20261002-083000-5", lambda rep: rep)

    assert not (tmp_path / "nowhere").exists()


# -- no channel call under the lock ------------------------------------------------------------


class LockProbe(FakeChannel):
    """A channel that fails any call made while the project's lock is held: the lock never spans the network."""

    def __init__(self, home: Path, *batches) -> None:
        super().__init__(*batches)
        self.home = home
        self.probed: list[str] = []

    def _free(self, method: str) -> None:
        self.probed.append(method)
        assert lock_is_free(self.home), f"{method} called while the lock is held"

    def send(self, *args, **kw):
        self._free("send")
        return super().send(*args, **kw)

    def send_images(self, *args, **kw):
        self._free("send_images")
        return super().send_images(*args, **kw)

    def edit(self, *args, **kw):
        self._free("edit")
        return super().edit(*args, **kw)

    def delete(self, *args, **kw):
        self._free("delete")
        return super().delete(*args, **kw)

    def react(self, *args, **kw):
        self._free("react")
        return super().react(*args, **kw)

    def get_file(self, *args, **kw):
        self._free("get_file")
        return super().get_file(*args, **kw)

    def list_admins(self, *args, **kw):
        self._free("list_admins")
        return super().list_admins(*args, **kw)

    def member_count(self, *args, **kw):
        self._free("member_count")
        return super().member_count(*args, **kw)


def test_no_channel_call_is_made_while_the_lock_is_held(bound, bugs_home):
    write_report(bound, 5, author_id=7, status="seen", reaction={"wanted": EMOJI_SEEN, "applied": None, "error": None})
    write_report(bound, 6, author="Mathis", text="écran noir")
    store = Store(bound)
    other = f"{STAMP}-6"
    answer = inbound(GROUP_ID, 300, "iPhone SE", date=BASE_DATE + 30, author=fake_author(7, None, "Laura"),
                     thread_of=5, attachments=[Attachment(file_id="a1", ext=".jpg")])
    fresh = inbound(GROUP_ID, 301, "nouveau", date=BASE_DATE + 31, attachments=[Attachment(file_id="n1", ext=".jpg")])
    channel = LockProbe(bound, fake_batch(answer, fresh))
    channel.admins, channel.members = [fake_author(8, "mathis", "Mathis")], 1

    pull.cmd_pull(channel, Machine(bugs_home), BASE_DATE + 60)
    reports.cmd_reply(channel, store, GROUP_ID, REPORT, "Tu es sur quel iPhone ?", BASE_DATE + 70, awaits=True)
    replies.cmd_edit(channel, store, GROUP_ID, REPORT, "Tu as quel iPhone ?", BASE_DATE + 80, awaits=True)
    replies.cmd_delete(channel, store, GROUP_ID, REPORT, BASE_DATE + 90)
    reports.cmd_taken(channel, store, GROUP_ID, REPORT)
    reports.cmd_fixed(channel, store, GROUP_ID, REPORT, "abc1234", BASE_DATE + 100)
    reports.cmd_done(channel, store, GROUP_ID, other, "C'est voulu", BASE_DATE + 110)
    people.cmd_backfill_authors(channel, store, GROUP_ID)

    assert set(channel.probed) == {"send", "edit", "delete", "react", "get_file", "list_admins", "member_count"}
    assert report(bound, other)["author_id"] == 8
    assert report(bound)["answers"][0]["images"] == ["1.jpg"]


# -- the guard: no report or card written but through update_report / update_card ------------

# Every function of the package that may call write_json, and what it writes. A report.json or a card
# is written by update_report / update_card only; Pull builds a new report in a hidden temp directory.
WRITERS = {
    ("store.py", "update_report"): "a report, under the lock",
    ("people.py", "update_card"): "a card, under the lock",
    ("pull.py", "build_report"): "a new report, in its temp directory before the rename",
    ("store.py", "Machine._save_machine_key"): "the machine's state.json",
    ("store.py", "Machine.note_unregistered"): "unregistered.json",
    ("store.py", "Store.save_state"): "the project's state.json",
    ("registry.py", "Registry._write"): "projects.json",
    ("init.py", "cmd_init"): "a project file",
    ("gate.py", "cmd_gate"): "a project file",
    ("project.py", "rebind_chat"): "a project file",
}


def write_json_callers(source: str) -> set[str]:
    """Return the qualified names of the functions of ``source`` that call ``write_json``."""
    found: set[str] = set()

    def visit(node: ast.AST, scope: list[str]) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                visit(child, [*scope, child.name])
                continue
            if isinstance(child, ast.Call) and getattr(child.func, "id", getattr(child.func, "attr", None)) == "write_json":
                found.add(".".join(scope[:2]) or "<module>")
            visit(child, scope)

    visit(ast.parse(source), [])
    return found


def package_writers() -> set[tuple[str, str]]:
    package = Path(pull.__file__).parent
    return {
        (path.name, caller)
        for path in sorted(package.glob("*.py"))
        if path.name != "jsonio.py"
        for caller in write_json_callers(path.read_text())
    }


def test_no_report_or_card_is_written_but_through_update_report_or_update_card():
    assert package_writers() == set(WRITERS)


def test_the_guard_sees_a_report_saved_by_hand():
    source = '''
def cmd_triage(store, report_id, kind):
    path, report = load_report(store, report_id)
    report["kind"] = kind
    write_json(path / "report.json", report)
'''
    assert write_json_callers(source) == {"cmd_triage"}
