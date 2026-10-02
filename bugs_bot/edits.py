"""Edits: a new version of a message already recorded takes its place in the report, the previous text kept.

A tester may correct a message after sending it (operator, 2026-10-02: a report whose real text came in
an edit was lost). Pull routes the new version to the report recording that message — its first message,
a member of its media group, or an answer in its thread — and records the text it replaces in the report's
``edits``. ``wait`` prints ``edited <report-id>`` while an edit is unseen; ``show`` prints the edits and
marks them seen. An edit never creates a report, never sets or clears a wait, never changes a status or a
reaction; an edit of a message no report records is ignored.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from bugs_bot.channel import ChatId, InboundMessage
from bugs_bot.errors import BugsError
from bugs_bot.store import Store, find_by_message, update_report

_log = logging.getLogger(__name__)


def record_edit(store: Store, chat_id: ChatId, msg: InboundMessage) -> str | None:
    """Replace the recorded text of the message ``msg`` is a new version of; return its report's id.

    ``None`` when no report records that message (logged at debug level only), when the report was purged
    meanwhile, or when the text recorded is already this one (an edit delivered again).
    """
    report_id = find_by_message(store, chat_id, msg.message_id)
    if report_id is None:
        _log.debug("edit of message %s in chat %s ignored: no report records it", msg.message_id, chat_id)
        return None

    def replace(report: dict) -> bool:
        # Read again under the lock: the report as it is now, not as it was found.
        holder = report
        if msg.message_id not in report.get("message_ids", []):
            holder = next((a for a in report.get("answers", []) if a.get("message_id") == msg.message_id), None)
            if holder is None:
                return False
        previous = holder.get("text") or ""
        if previous == msg.text:
            return False
        holder["text"] = msg.text
        report.setdefault("edits", []).append(
            {
                "date": datetime.fromtimestamp(msg.date, timezone.utc).isoformat(),
                "message_id": msg.message_id,
                "previous": previous,
                "seen": False,
            }
        )
        return True

    try:
        changed = update_report(store, report_id, replace)
    except BugsError:
        return None  # purged since it was found: nothing left to correct
    return report_id if changed else None


def unseen_edits(store: Store) -> list[str]:
    """Return the ids of the reports holding an edit ``show`` has not printed yet, oldest first."""
    return [rid for rid, _, report in store.reports() if any(not edit.get("seen") for edit in report.get("edits", []))]


def _current(report: dict, message_id: object) -> str:
    """Return the text recorded now for a message of the report: the report's own, or its answer's."""
    if message_id in report.get("message_ids", []):
        return report.get("text") or ""
    return next((a.get("text") or "" for a in report.get("answers", []) if a.get("message_id") == message_id), "")


def show_edits(store: Store, report_id: str, report: dict) -> list[str]:
    """Return the lines ``show`` prints for the report's edits, and mark them seen in ``report.json``.

    Each line goes from one version to the next: the text an edit replaced, then the one that replaced it.
    Only the edits printed are marked: one Pull records meanwhile stays unseen, for ``wait`` to announce.
    """
    found = report.get("edits", [])
    lines = []
    for number, edit in enumerate(found):
        later = next((e["previous"] for e in found[number + 1 :] if e["message_id"] == edit["message_id"]), None)
        after = later if later is not None else _current(report, edit["message_id"])
        lines.append(f"modifié : {edit['previous'] or '(no text)'} → {after or '(no text)'}")
    printed = len(found)
    if any(not edit.get("seen") for edit in found):

        def mark_seen(fresh: dict) -> None:
            for edit in fresh.get("edits", [])[:printed]:  # edits are only appended: the first ones are those shown
                edit["seen"] = True

        update_report(store, report_id, mark_seen)
    return lines
