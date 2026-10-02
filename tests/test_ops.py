"""The operations files: the PM2 process definition and the Bot API root override."""

from __future__ import annotations

import os
import subprocess
import sys

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


def _api_root(**env: str) -> str:
    base = {k: v for k, v in os.environ.items() if k != "BUGS_BOT_API_ROOT"}
    out = subprocess.run(
        [sys.executable, "-c", "from bugs_bot import telegram; print(telegram.API_ROOT)"],
        cwd=REPO_ROOT, env=base | env, capture_output=True, text=True, check=True,
    )
    return out.stdout.strip()


def test_api_root_defaults_to_telegram():
    assert _api_root() == "https://api.telegram.org"


def test_api_root_is_overridden_by_the_environment():
    assert _api_root(BUGS_BOT_API_ROOT="http://127.0.0.1:9") == "http://127.0.0.1:9"


def test_an_empty_api_root_falls_back_to_telegram():
    assert _api_root(BUGS_BOT_API_ROOT="") == "https://api.telegram.org"
