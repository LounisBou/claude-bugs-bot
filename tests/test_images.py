"""Screenshots to reporters: the checks before anything is sent, each channel's wire, the record of what was sent."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from samples import GROUP_ID, TOKEN, FakeTelegram, parse_multipart

from bugs_bot.channel import ImagesNotSent, multipart
from bugs_bot.errors import BugsError
from bugs_bot.images import MAX_BYTES, MAX_IMAGES, check_images, record_sent
from bugs_bot.telegram import TelegramChannel

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 16
WEBP = b"RIFF\x10\x00\x00\x00WEBPVP8 " + b"\x00" * 8


def image(where: Path, name: str, data: bytes = PNG) -> str:
    """Write an image file named ``name`` under ``where``; return its path as the CLI receives it."""
    path = where / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return str(path)


# -- check_images: everything checked before anything is sent ---------------------------------


def test_png_jpeg_and_webp_pass_by_their_magic_bytes_whatever_their_name(tmp_path):
    paths = [image(tmp_path, "a.png"), image(tmp_path, "photo sans extension", JPEG), image(tmp_path, "c.bin", WEBP)]

    assert check_images(paths) == [Path(p).resolve() for p in paths]


@pytest.mark.parametrize(
    "make, said",
    [
        (lambda d: str(d / "absent.png"), "no such file"),
        (lambda d: image(d, "notes.png", b"just some text, not an image"), "not a PNG, JPEG or WebP image"),
        (lambda d: image(d, "big.png", PNG + b"\x00" * MAX_BYTES), "over 10 MB"),
        (lambda d: str(d), "no such file"),
    ],
    ids=["missing", "not-an-image", "too-big", "a-directory"],
)
def test_a_bad_image_is_refused_and_named(tmp_path, make, said):
    good, bad = image(tmp_path, "ok.png"), make(tmp_path)

    with pytest.raises(BugsError, match=said) as refused:
        check_images([good, bad])

    assert Path(bad).name in str(refused.value)


def test_more_than_ten_images_are_refused(tmp_path):
    paths = [image(tmp_path, f"{k}.png") for k in range(MAX_IMAGES + 1)]

    with pytest.raises(BugsError, match="at most 10 images"):
        check_images(paths)


def test_ten_images_pass(tmp_path):
    assert len(check_images([image(tmp_path, f"{k}.png") for k in range(MAX_IMAGES)])) == MAX_IMAGES


# -- record_sent: what the person saw, kept beside the report ----------------------------------


def test_the_images_sent_are_copied_into_sent_named_by_reply_and_rank(tmp_path):
    report_dir = tmp_path / "inbox" / "r1"
    report_dir.mkdir(parents=True)
    paths = check_images([image(tmp_path, "my shots/écran 1.png"), image(tmp_path, "my shots/b", JPEG)])

    names = record_sent(report_dir, 3, paths)

    assert names == ["sent/3-1.png", "sent/3-2.jpg"]
    assert (report_dir / "sent" / "3-1.png").read_bytes() == PNG
    assert (report_dir / "sent" / "3-2.jpg").read_bytes() == JPEG


# -- Telegram: sendPhoto for one, sendMediaGroup for several, multipart read back --------------

LAURA = {"user_id": 7, "username": "laura_t", "name": "Laura"}


def telegram() -> tuple[TelegramChannel, FakeTelegram]:
    tg = FakeTelegram()
    return TelegramChannel(TOKEN, tg), tg


def test_telegram_one_image_is_a_photo_captioned_with_the_text(tmp_path):
    channel, tg = telegram()
    paths = check_images([image(tmp_path, "my shot.png")])

    sent = channel.send_images(GROUP_ID, "Voilà l'écran", paths)

    assert [url.rsplit("/", 1)[-1] for url, _ in tg.calls] == ["sendPhoto"]
    form = tg.photos[0]
    assert form["fields"] == {"chat_id": str(GROUP_ID), "caption": "Voilà l'écran"}
    assert form["files"] == {"photo": ("image-1.png", PNG, "image/png")}
    assert sent == [{"message_id": 601, "text": "Voilà l'écran"}]


def test_telegram_several_images_are_one_media_group_captioned_on_the_first(tmp_path):
    channel, tg = telegram()
    paths = check_images([image(tmp_path, "a.png"), image(tmp_path, "b", JPEG), image(tmp_path, "c", WEBP)])

    sent = channel.send_images(GROUP_ID, "Les trois étapes", paths, reply_to=55)

    form = tg.photos[0]
    assert form["method"] == "sendMediaGroup"
    assert json.loads(form["fields"]["media"]) == [
        {"type": "photo", "media": "attach://image1", "caption": "Les trois étapes"},
        {"type": "photo", "media": "attach://image2"},
        {"type": "photo", "media": "attach://image3"},
    ]
    assert json.loads(form["fields"]["reply_parameters"]) == {"message_id": 55}
    assert form["files"] == {
        "image1": ("image-1.png", PNG, "image/png"),
        "image2": ("image-2.jpg", JPEG, "image/jpeg"),
        "image3": ("image-3.webp", WEBP, "image/webp"),
    }
    assert sent == [{"message_id": 610, "text": "Les trois étapes"}, {"message_id": 611, "text": ""}, {"message_id": 612, "text": ""}]


def test_telegram_threads_and_mentions_through_the_caption(tmp_path):
    channel, tg = telegram()

    sent = channel.send_images(GROUP_ID, "regarde", check_images([image(tmp_path, "a.png")]), reply_to=55, mention=LAURA)

    fields = tg.photos[0]["fields"]
    assert fields["caption"] == "@laura_t regarde"
    assert json.loads(fields["caption_entities"]) == [{"type": "mention", "offset": 0, "length": 8}]
    assert json.loads(fields["reply_parameters"]) == {"message_id": 55}
    assert sent[0]["text"] == "@laura_t regarde"


def test_telegram_a_text_too_long_for_a_caption_goes_first_then_the_images_on_the_same_thread(tmp_path):
    channel, tg = telegram()
    text = "é" * 1020  # 1020 alone fits; with the mention it does not

    sent = channel.send_images(GROUP_ID, text, check_images([image(tmp_path, "a.png")]), reply_to=55, mention=LAURA)

    assert [url.rsplit("/", 1)[-1] for url, _ in tg.calls] == ["sendMessage", "sendPhoto"]
    assert tg.sent[0]["text"] == f"@laura_t {text}" and tg.sent[0]["reply_parameters"] == {"message_id": 55}
    fields = tg.photos[0]["fields"]
    assert "caption" not in fields and json.loads(fields["reply_parameters"]) == {"message_id": 55}
    assert sent == [{"message_id": 777, "text": f"@laura_t {text}"}, {"message_id": 601, "text": ""}]


def test_telegram_images_failing_after_the_text_say_the_text_alone_went_out(tmp_path):
    channel, tg = telegram()
    tg.photo_error = "Bad Request: IMAGE_PROCESS_FAILED"

    with pytest.raises(ImagesNotSent, match="IMAGE_PROCESS_FAILED") as failed:
        channel.send_images(GROUP_ID, "x" * 1100, check_images([image(tmp_path, "a.png")]))

    assert failed.value.sent == {"message_id": 777, "text": "x" * 1100}


def test_telegram_a_refused_photo_with_its_caption_posts_nothing_and_is_a_plain_error(tmp_path):
    channel, tg = telegram()
    tg.photo_error = "Bad Request: chat not found"

    with pytest.raises(BugsError, match="sendPhoto: Bad Request: chat not found") as failed:
        channel.send_images(GROUP_ID, "court", check_images([image(tmp_path, "a.png")]))

    assert not isinstance(failed.value, ImagesNotSent)
    assert TOKEN not in str(failed.value)


# -- the multipart body ------------------------------------------------------------------------


def test_a_multipart_body_reads_back_whole_with_a_filename_holding_spaces_and_quotes():
    body = multipart({"chat_id": "-100", "caption": "deux\r\nlignes « é »"}, [("photo", 'mon "écran" 1.png', PNG, "image/png")])

    form = parse_multipart(body)
    assert body.content_type.startswith("multipart/form-data; boundary=")
    assert form["fields"] == {"chat_id": "-100", "caption": "deux\r\nlignes « é »"}
    assert form["files"] == {"photo": ('mon "écran" 1.png', PNG, "image/png")}


def test_the_boundary_never_appears_inside_the_content(monkeypatch):
    import uuid

    from bugs_bot import channel as channel_module

    drawn = iter([uuid.UUID(int=1), uuid.UUID(int=2)])
    monkeypatch.setattr(channel_module.uuid, "uuid4", lambda: next(drawn))
    clash = uuid.UUID(int=1).hex.encode()

    body = multipart({}, [("photo", "a.png", b"before " + clash + b" after", "image/png")])

    assert uuid.UUID(int=2).hex in body.content_type


def test_the_http_transport_sends_an_upload_as_its_bytes_and_content_type(monkeypatch):
    from bugs_bot import channels

    seen = {}

    class Answer:
        status = 200
        headers = {}

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            return b'{"ok": true}'

    def urlopen(request, timeout):
        seen.update(data=request.data, type=request.get_header("Content-type"), auth=request.get_header("Authorization"))
        return Answer()

    monkeypatch.setattr(channels.urllib.request, "urlopen", urlopen)
    body = multipart({"chat_id": "1"}, [("photo", "image-1.png", PNG, "image/png")])

    status, _ = channels.http_transport("https://example.invalid/up", body, None, {"Authorization": "Bearer x"})

    assert status == 200
    assert (seen["data"], seen["type"], seen["auth"]) == (body.data, body.content_type, "Bearer x")
