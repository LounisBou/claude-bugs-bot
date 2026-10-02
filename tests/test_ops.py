"""The operations files: the PM2 process definition and the Bot API root override."""

from __future__ import annotations

from conftest import REPO_ROOT


def _module_exports() -> str:
    """Return the part of ``pm2.config.js`` after ``module.exports`` (comments above it excluded)."""
    return (REPO_ROOT / "pm2.config.js").read_text().split("module.exports", 1)[1]


def test_pm2_config_names_the_process_and_its_entry_point():
    exports = _module_exports()

    assert "name: 'bugs-bot-pull'" in exports
    assert "script: __dirname + '/bin/bugs-bot'" in exports
    assert "args: 'pull --watch'" in exports


def test_pm2_interpreter_comes_from_the_environment_not_a_fixed_path():
    exports = _module_exports()

    assert "interpreter: process.env.BUGS_BOT_PYTHON || 'python3'" in exports
    assert "/Users/" not in exports


def test_pm2_config_keeps_the_restart_policy_and_no_cron():
    exports = _module_exports()

    assert "autorestart: true" in exports
    assert "restart_delay: 60000" in exports
    assert "kill_timeout: 5000" in exports
    assert "cron_restart" not in exports


import pytest

from bugs_bot.errors import BugsError
from bugs_bot.telegram import TelegramChannel, api_root
from samples import FakeTelegram


def test_api_root_defaults_to_telegram():
    assert api_root({}) == "https://api.telegram.org"


@pytest.mark.parametrize(
    "root",
    ["https://bot.example.org", "http://127.0.0.1:9", "http://127.0.0.1", "http://localhost:8081", "http://localhost"],
)
def test_api_root_accepts_https_and_loopback_http(root):
    assert api_root({"BUGS_BOT_API_ROOT": root}) == root


def test_an_empty_api_root_falls_back_to_telegram():
    assert api_root({"BUGS_BOT_API_ROOT": ""}) == "https://api.telegram.org"


@pytest.mark.parametrize(
    "root",
    [
        "http://evil.example",
        "http://127.0.0.1.evil.example",
        "http://localhost.evil.example:80",
        "http://user@127.0.0.1:9",
        "ftp://127.0.0.1",
        "file:///tmp/x",
        "evil.example",
    ],
)
def test_api_root_refuses_any_other_url_and_names_the_variable(root):
    with pytest.raises(BugsError, match="BUGS_BOT_API_ROOT"):
        api_root({"BUGS_BOT_API_ROOT": root})


def test_the_refusal_does_not_hold_a_token():
    with pytest.raises(BugsError) as caught:
        api_root({"BUGS_BOT_API_ROOT": "http://evil.example/bot123456:SECRETSECRETSECRET"})
    assert "SECRETSECRETSECRET" not in str(caught.value)


def test_api_and_file_urls_are_built_from_the_same_root():
    tg = FakeTelegram()
    channel = TelegramChannel("123456789:AAFakeTokenFakeTokenFake", tg, "http://127.0.0.1:9")

    channel.get_updates(None, 0)
    channel.get_file("abc")

    assert [url for url, _ in tg.calls] == [
        "http://127.0.0.1:9/bot123456789:AAFakeTokenFakeTokenFake/getUpdates",
        "http://127.0.0.1:9/bot123456789:AAFakeTokenFakeTokenFake/getFile",
        "http://127.0.0.1:9/file/bot123456789:AAFakeTokenFakeTokenFake/photos/abc.jpg",
    ]
