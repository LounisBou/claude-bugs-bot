"""Inbound messages: Telegram's updates normalised by ``TelegramChannel.poll``, the factory, the cursor."""

from __future__ import annotations

import pytest
from samples import BASE_DATE, GROUP_ID, OTHER_GROUP_ID, TOKEN, FakeTelegram, message

from bugs_bot.channel import Attachment, Author, Batch, InboundMessage, mask
from bugs_bot.channels import channel_for, token_problem
from bugs_bot.errors import BugsError
from bugs_bot.store import Machine
from bugs_bot.telegram import TelegramChannel

OLD_ID = -555
PROMOTED_ID = -1005555555555
IZNO = Author(id=42, username="izno_op", name="izno_op", language=None, is_bot=False)


def poll(*updates: dict, cursor: dict | None = None, timeout: int = 0) -> tuple[Batch, FakeTelegram]:
    tg = FakeTelegram(list(updates))
    return TelegramChannel(TOKEN, tg).poll(cursor, [], timeout), tg


# -- one message each kind ----------------------------------------------------------------------


def test_a_text_message_is_normalised():
    got, _ = poll(message(10, 100, text="ça plante"))

    assert got.messages == [
        InboundMessage(
            chat_id=GROUP_ID,
            message_id=100,
            date=float(BASE_DATE),
            author=IZNO,
            text="ça plante",
            attachments=(),
            group_key=None,
            thread_of=None,
        )
    ]
    assert isinstance(got.messages[0].date, float)


def test_a_photo_gives_its_largest_size_as_a_jpg_and_its_caption_as_text():
    got, _ = poll(message(10, 100, caption="l'écran", photo="p1"))

    [msg] = got.messages
    assert msg.attachments == (Attachment(file_id="p1-l", ext=".jpg"),)
    assert msg.text == "l'écran"


def test_an_image_document_keeps_its_extension_lower_cased():
    doc = {"file_id": "doc-1", "file_name": "Capture.PNG", "mime_type": "image/png"}
    got, _ = poll(message(10, 100, document=doc))

    assert got.messages[0].attachments == (Attachment(file_id="doc-1", ext=".png"),)
    assert got.messages[0].text == ""


def test_a_document_without_a_name_takes_the_extension_of_its_type():
    got, _ = poll(message(10, 100, document={"file_id": "doc-2", "mime_type": "image/png"}))

    assert got.messages[0].attachments == (Attachment(file_id="doc-2", ext=".png"),)


def test_a_document_that_is_not_an_image_is_text_only():
    doc = {"file_id": "pdf-1", "file_name": "log.pdf", "mime_type": "application/pdf"}
    got, _ = poll(message(10, 100, caption="le journal", document=doc))

    assert got.messages[0].attachments == ()
    assert got.messages[0].text == "le journal"


def test_a_media_group_shares_its_key_and_keeps_the_order():
    got, _ = poll(
        message(10, 100, caption="trois", photo="g1", media_group_id="album"),
        message(11, 101, photo="g2", media_group_id="album"),
    )

    assert [(m.message_id, m.group_key) for m in got.messages] == [(100, "album"), (101, "album")]


def test_the_author_without_a_username_is_named_by_first_name_with_language():
    update = message(10, 100, text="x")
    update["message"]["from"] = {"id": 77, "is_bot": False, "first_name": "Zoé", "language_code": "fr"}

    got, _ = poll(update)

    assert got.messages[0].author == Author(id=77, username=None, name="Zoé", language="fr", is_bot=False)


def test_a_message_without_a_sender_has_an_empty_author():
    update = message(10, 100, text="x")
    del update["message"]["from"]

    got, _ = poll(update)

    assert got.messages[0].author == Author(id=None, username=None, name="", language=None, is_bot=False)


# -- what is not content ------------------------------------------------------------------------


def test_a_bot_post_is_not_a_message_but_its_chat_is_seen():
    post = message(10, 100, text="Comment signaler un bug")
    post["message"]["from"] = {"id": 8, "is_bot": True, "first_name": "Clawdbot", "username": "ClawBot"}

    got, _ = poll(post)

    assert got.messages == []
    assert got.chats == {GROUP_ID: {"id": GROUP_ID, "title": "TM Bugs", "type": "supergroup"}}


def test_a_service_message_is_not_a_message():
    service = message(10, 100)
    service["message"]["new_chat_title"] = "Renamed"

    got, _ = poll(service)

    assert got.messages == []


def test_a_private_chat_is_not_among_the_chats():
    got, _ = poll(message(10, 100, chat_id=42, chat_type="private", text="x"))

    assert got.chats == {}
    assert [m.chat_id for m in got.messages] == [42]


def test_a_chat_the_bot_was_added_to_is_seen():
    joined = {"update_id": 10, "my_chat_member": {"chat": {"id": OTHER_GROUP_ID, "title": "Nouveau", "type": "group"}}}

    got, _ = poll(joined)

    assert got.chats == {OTHER_GROUP_ID: {"id": OTHER_GROUP_ID, "title": "Nouveau", "type": "group"}}
    assert got.messages == []


# -- a group promoted to supergroup ---------------------------------------------------------------


def test_a_migration_maps_the_old_id_to_the_new_and_the_old_chat_is_dead():
    before = message(10, 1, chat_id=OLD_ID, chat_type="group", text="avant")
    promoted = message(11, 2, chat_id=OLD_ID, chat_type="group")
    promoted["message"]["migrate_to_chat_id"] = PROMOTED_ID
    arrived = message(12, 1, chat_id=PROMOTED_ID)
    arrived["message"]["migrate_from_chat_id"] = OLD_ID

    got, _ = poll(before, promoted, arrived)

    assert got.migrations == {OLD_ID: PROMOTED_ID}
    assert list(got.chats) == [PROMOTED_ID]
    # the message sent before the promotion keeps the id it was sent in
    assert [(m.chat_id, m.text) for m in got.messages] == [(OLD_ID, "avant")]


# -- the cursor ---------------------------------------------------------------------------------


def test_the_cursor_moves_past_every_update_and_is_only_returned():
    joined = {"update_id": 30, "my_chat_member": {"chat": {"id": OTHER_GROUP_ID, "title": "N", "type": "group"}}}

    got, tg = poll(message(10, 100, text="x"), joined)

    assert got.cursor == {"offset": 31}
    assert "offset" not in tg.updates_calls()[0]


def test_a_given_cursor_is_sent_as_the_offset():
    got, tg = poll(message(10, 100, text="x"), message(11, 101, text="y"), cursor={"offset": 11})

    assert [m.message_id for m in got.messages] == [101]
    assert tg.updates_calls() == [{"timeout": 0, "allowed_updates": ["message"], "offset": 11}]


def test_an_empty_batch_returns_the_cursor_it_was_given():
    assert poll(cursor={"offset": 11})[0].cursor == {"offset": 11}
    assert poll()[0].cursor == {}


def test_a_held_poll_is_read_longer_than_telegram_holds_it():
    _, tg = poll(timeout=50)

    assert tg.updates_calls() == [{"timeout": 50, "allowed_updates": ["message"]}]
    assert tg.timeouts == [60]


def test_the_machine_keeps_the_telegram_cursor_as_the_offset_key(bugs_home):
    machine = Machine(bugs_home)
    assert machine.load_cursor("telegram") is None

    machine.save_cursor("telegram", {"offset": 25})

    assert (bugs_home / "state.json").read_text() == '{\n  "offset": 25\n}\n'
    assert machine.load_cursor("telegram") == {"offset": 25}
    assert machine.load_offset() == 25


def test_the_machine_refuses_a_cursor_of_an_unknown_kind(bugs_home):
    with pytest.raises(BugsError, match="slack"):
        Machine(bugs_home).load_cursor("slack")
    with pytest.raises(BugsError, match="slack"):
        Machine(bugs_home).save_cursor("slack", {})


# -- administrators -----------------------------------------------------------------------------


def test_administrators_are_authors():
    tg = FakeTelegram()
    tg.admins = [
        {"status": "creator", "user": {"id": 42, "is_bot": False, "first_name": "Izno", "username": "izno_op"}},
        {"status": "administrator", "user": {"id": 8, "is_bot": True, "first_name": "Clawdbot", "username": "ClawBot"}},
        {"status": "administrator", "user": {"id": 77, "is_bot": False, "first_name": "Zoé", "language_code": "fr"}},
    ]

    got = TelegramChannel(TOKEN, tg).list_admins(GROUP_ID)

    assert got == [
        IZNO,
        Author(id=8, username="ClawBot", name="ClawBot", language=None, is_bot=True),
        Author(id=77, username=None, name="Zoé", language="fr", is_bot=False),
    ]


# -- the factory and the mask -------------------------------------------------------------------


def test_the_factory_builds_telegram_with_its_token_and_api_root(env):
    tg = FakeTelegram([message(10, 100, text="x")])

    channel = channel_for("telegram", {**env, "BUGS_BOT_API_ROOT": "http://127.0.0.1:9"}, tg)

    assert channel.kind == "telegram"
    assert channel.secret == TOKEN
    channel.poll(None, [], 0)
    assert tg.calls[0][0] == f"http://127.0.0.1:9/bot{TOKEN}/getUpdates"


def test_the_factory_refuses_an_unknown_kind(env):
    with pytest.raises(BugsError, match="unknown channel: irc"):
        channel_for("irc", env, FakeTelegram())


def test_the_factory_refuses_a_missing_token_without_printing_one(tmp_path, bugs_home):
    env = {"BUGS_BOT_ENV_FILE": str(tmp_path / "missing.env"), "BUGS_BOT_HOME": str(bugs_home)}

    with pytest.raises(BugsError, match="cannot read the env file"):
        channel_for("telegram", env, FakeTelegram())


def test_token_problem_says_why_and_never_the_token(env, tmp_path):
    other = tmp_path / "other.env"
    other.write_text(f"SOMETHING={TOKEN}\n")

    assert token_problem("telegram", env) is None
    assert "cannot read the env file" in token_problem("telegram", {"BUGS_BOT_ENV_FILE": str(tmp_path / "none")})
    assert token_problem("telegram", {"BUGS_BOT_ENV_FILE": str(other)}) == f"TELEGRAM_BOT_TOKEN not found in {other}"
    assert token_problem("irc", env) == "unknown channel: irc"


def test_mask_hides_the_secret_and_any_bot_token_shape():
    assert mask(f"GET /bot{TOKEN}/getMe", TOKEN) == "GET /bot<token>/getMe"
    assert mask("secret part AAFakeTokenFakeTokenFakeTokenFake123", TOKEN) == "secret part <token>"
    assert mask("GET /bot999:ABCdef_ghi-123/getMe", None) == "GET /bot<token>/getMe"
    assert mask("nothing here", None) == "nothing here"
