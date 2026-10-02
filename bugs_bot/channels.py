"""The channel factory: the one module naming the implementations, and the default HTTP transport they share."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Mapping

from bugs_bot import slack, telegram
from bugs_bot.channel import Body, Channel, Transport, Upload
from bugs_bot.errors import BugsError

HTTP_TIMEOUT = 30
# The kinds whose platform holds a read until a message arrives and hands the bot's messages to one reader:
# Pull long-polls them and logs the chats it drops, for ``init``. Any other kind is read again each round.
LONG_POLL_KINDS = {"telegram"}
# Each kind: how its token is read, and its channel built from the token, the transport and the env.
_KINDS = {
    "telegram": (telegram.read_token, lambda token, transport, env: telegram.TelegramChannel(token, transport, telegram.api_root(env))),
    "slack": (slack.read_token, lambda token, transport, env: slack.SlackChannel(token, transport, slack.api_root(env))),
}
KINDS = tuple(_KINDS)


def http_transport(
    url: str, payload: dict | Upload | None = None, timeout: float | None = None, headers: Mapping[str, str] | None = None
) -> tuple[int, bytes]:
    """Send one request with ``urllib``; HTTP errors are returned, not raised.

    Args:
        url: Full URL.
        payload: JSON body (POST), an ``Upload`` sent as its bytes (POST), or ``None`` (GET).
        timeout: Read timeout in seconds (default ``HTTP_TIMEOUT``).
        headers: Extra request headers (a platform's ``Authorization``).

    Returns:
        ``(status, body)``; the body carries the response headers (``Body.headers``).
    """
    if isinstance(payload, Upload):
        data, sent = payload.data, {"Content-Type": payload.content_type}
    else:
        data = None if payload is None else json.dumps(payload).encode()
        sent = {} if payload is None else {"Content-Type": "application/json"}
    request = urllib.request.Request(url, data=data, headers={**sent, **(headers or {})})
    try:
        with urllib.request.urlopen(request, timeout=timeout or HTTP_TIMEOUT) as resp:  # noqa: S310 - https or loopback, see each channel's API root
            return resp.status, Body(resp.read(), dict(resp.headers.items()))
    except urllib.error.HTTPError as exc:
        # A platform explains its refusals in the body, and how long to wait in the headers: keep both.
        return exc.code, Body(exc.read(), dict(exc.headers.items()) if exc.headers else {})


def channel_for(kind: str, env: Mapping[str, str], transport: Transport) -> Channel:
    """Return the channel of ``kind``, reading its token and API root itself.

    Args:
        kind: The channel kind, one of ``KINDS``.
        env: Process environment (where the token file and the API root are found).
        transport: What carries the requests; tests inject a fake.

    Returns:
        The channel.

    Raises:
        BugsError: On an unknown kind, a missing token, or an API root refused.
    """
    if kind not in _KINDS:
        raise BugsError(f"unknown channel: {kind}")
    read_token, build = _KINDS[kind]
    return build(read_token(env), transport, env)


def token_problem(kind: str, env: Mapping[str, str]) -> str | None:
    """Return why ``kind``'s token cannot be read, ``None`` when it can; the token itself is never returned.

    Args:
        kind: The channel kind.
        env: Process environment.

    Returns:
        The reason (the env file unreadable, the variable missing, the kind unknown), or ``None``.
    """
    if kind not in _KINDS:
        return f"unknown channel: {kind}"
    try:
        _KINDS[kind][0](env)
    except BugsError as exc:
        return str(exc)
    return None
