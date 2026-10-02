"""Screenshots to reporters: the checks before anything is sent, each channel's wire, the record of what was sent."""

from __future__ import annotations

from pathlib import Path

import pytest

from bugs_bot.errors import BugsError
from bugs_bot.images import MAX_BYTES, MAX_IMAGES, check_images, record_sent

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
