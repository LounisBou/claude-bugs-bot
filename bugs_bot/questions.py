"""One question at a time per person (spec § 3.5): a question to someone who owes an answer on another report waits on their card.

A person may raise several subjects; the agent works on all of them but asks about one at a time, so
nobody faces a volley of questions. ``reply --awaits`` to a person whose answer is awaited on another
report not done posts nothing: the question joins ``questions`` on their card. Once nothing of theirs is
awaited — they answered, or the awaited message was deleted — ``wait`` prints ``ask <report-id>`` for
the oldest one, and the agent asks it from the current state of that subject.
"""

from __future__ import annotations

from datetime import datetime, timezone

from bugs_bot.people import card_key, card_of, load_person, save_person
from bugs_bot.store import Store


def _awaited(reports: list[tuple[str, object, dict]], key: str, exclude: str | None) -> str | None:
    """Return the first report but ``exclude`` on which the answer of the person with card ``key`` is awaited, or ``None``.

    A wait counts whatever the report's status but ``done`` (« vérifier » is asked on a ``fixed`` one).
    """
    for report_id, _, report in reports:
        wait = report.get("awaiting")
        if (
            report_id != exclude
            and wait
            and report["status"] != "done"
            and card_key(report.get("author_id"), report["author"]) == key
        ):
            return report_id
    return None


def awaited_elsewhere(store: Store, report: dict) -> str | None:
    """Return the id of another report on which the answer of ``report``'s author is awaited, or ``None``."""
    return _awaited(store.reports(), card_key(report.get("author_id"), report["author"]), report["id"])


def queue_question(store: Store, report: dict, text: str, now: float) -> None:
    """Append a question about ``report`` to its author's queue, creating their card."""
    card = card_of(store, card_key(report.get("author_id"), report["author"]), report["author"], report.get("author_id"))
    card.setdefault("questions", []).append(
        {"report": report["id"], "text": text, "queued": datetime.fromtimestamp(now, timezone.utc).isoformat()}
    )
    save_person(store, card)


def _remove(store: Store, report: dict, every: bool) -> None:
    card = load_person(store, card_key(report.get("author_id"), report["author"]))
    if not card or not card.get("questions"):
        return
    kept, removed = [], False
    for question in card["questions"]:
        if question["report"] == report["id"] and (every or not removed):
            removed = True
            continue
        kept.append(question)
    if removed:
        card["questions"] = kept
        save_person(store, card)


def asked(store: Store, report: dict) -> None:
    """Take the oldest queued question about ``report`` off its author's queue: it has just been asked."""
    _remove(store, report, every=False)


def drop_closed(store: Store, report: dict) -> None:
    """Drop every queued question about ``report``: it is done, there is nothing left to ask."""
    _remove(store, report, every=True)


def asks(store: Store) -> list[str]:
    """Return the report ids to ask about now: per person whose answer is awaited nowhere, their oldest queued question.

    A question about a report done or gone in the meantime is passed over; one about a ``fixed`` report is kept.
    """
    reports = store.reports()
    askable = {report_id for report_id, _, report in reports if report["status"] != "done"}
    found = []
    for path in sorted(store.people.glob("*.json")):
        card = load_person(store, path.stem) or {}
        pending = [q["report"] for q in card.get("questions", []) if q["report"] in askable]
        if pending and _awaited(reports, card_key(card.get("author_id"), card.get("name") or ""), None) is None:
            found.append(pending[0])
    return found
