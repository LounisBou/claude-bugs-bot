"""One update at a time: every change to a report or a card re-reads it under the project's lock, so no writer saves over a change it did not read."""

from __future__ import annotations

import json
from pathlib import Path

from fake_channel import FakeChannel
from samples import BASE_DATE, GROUP_ID
from test_mention import STAMP, write_report

from bugs_bot import pull
from bugs_bot.reports import cmd_done
from bugs_bot.store import EMOJI_SEEN, Machine, Store

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
