"""Screenshots to reporters: the checks every image passes before anything is sent, and the copy of what was sent.

The agent posts screenshots its launcher hands it (``reply … --image <path>``, ``post … --image``). Every
image is checked first — all of them, before the first byte goes out — and each one sent is copied
beside the report (``sent/<reply n>-<k>.<ext>``), so ``show`` and the handover note know what the
person saw.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from bugs_bot.errors import BugsError

MAX_IMAGES = 10
MAX_BYTES = 10 * 1024 * 1024
# The formats both platforms show inline, told by their first bytes (a name proves nothing).
_MAGIC = ((b"\x89PNG\r\n\x1a\n", ".png"), (b"\xff\xd8\xff", ".jpg"))
_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".webp": "image/webp"}


def extension_of(head: bytes) -> str | None:
    """Return the extension of an image by its first bytes (``.png``, ``.jpg``, ``.webp``), ``None`` for anything else."""
    for magic, ext in _MAGIC:
        if head.startswith(magic):
            return ext
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return ".webp"
    return None


def wire_file(path: Path, rank: int) -> tuple[str, bytes, str]:
    """Return what a channel uploads for the ``rank``-th image (1-based): ``(name, bytes, content type)``.

    The name is a neutral ``image-<k>.<ext>``: the file's own name may tell a local detail, and the group sees it.
    """
    data = path.read_bytes()
    ext = extension_of(data[:12]) or ".png"
    return f"image-{rank}{ext}", data, _TYPES[ext]


def _problem(path: Path) -> str | None:
    """Return why ``path`` cannot be sent, ``None`` when it can."""
    if not path.is_file():
        return "no such file"
    if path.stat().st_size > MAX_BYTES:
        return f"over {MAX_BYTES // (1024 * 1024)} MB"
    with path.open("rb") as handle:
        if extension_of(handle.read(12)) is None:
            return "not a PNG, JPEG or WebP image"
    return None


def check_images(paths: list[str]) -> list[Path]:
    """Check the images to send: 1 to ``MAX_IMAGES`` files, each PNG, JPEG or WebP, ``MAX_BYTES`` at most.

    Args:
        paths: The paths as given on the command line.

    Returns:
        The absolute paths, in the order given.

    Raises:
        BugsError: Naming every image refused and why. Nothing has been sent.
    """
    if not 1 <= len(paths) <= MAX_IMAGES:
        raise BugsError(f"{len(paths)} images: 1 to at most {MAX_IMAGES} images per message")
    resolved = [Path(path).expanduser().resolve() for path in paths]
    refused = [f"{path}: {why}" for path in resolved if (why := _problem(path))]
    if refused:
        raise BugsError("image refused, nothing sent: " + "; ".join(refused))
    return resolved


def record_sent(report_dir: Path, reply_number: int, paths: list[Path]) -> list[str]:
    """Copy the images sent with reply ``reply_number`` into ``<report_dir>/sent/<n>-<k>.<ext>``.

    Returns:
        Their names relative to the report's directory, in order, as the reply records them.
    """
    (report_dir / "sent").mkdir(exist_ok=True)
    names = []
    for rank, path in enumerate(paths, 1):
        with path.open("rb") as handle:
            ext = extension_of(handle.read(12)) or path.suffix
        name = f"sent/{reply_number}-{rank}{ext}"
        shutil.copyfile(path, report_dir / name)
        names.append(name)
    return names
