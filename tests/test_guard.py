"""The plugin is generic: no file of it names a project, outside the design documents and test fixtures."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from conftest import REPO_ROOT

# The names of the first project the plugin served. This file names them to look for them, so it is
# the one test file left out of its own search.
PROJECT_NAMES = re.compile(r"TorrentMate|PersonalScraper|tm-design", re.IGNORECASE)
EXCLUDED_DIRS = ("docs/", "tests/fixtures/")
SELF = "tests/test_guard.py"


def tracked_files() -> list[str]:
    """Return the repository's tracked files, relative to its root."""
    out = subprocess.run(["git", "ls-files"], cwd=REPO_ROOT, capture_output=True, text=True, check=True).stdout
    return out.splitlines()


def project_names_in(root: Path, paths: list[str]) -> list[str]:
    """Return ``path:line: text`` for every line naming a project, in the files that must name none."""
    found = []
    for path in paths:
        if path.startswith(EXCLUDED_DIRS) or path == SELF:
            continue
        text = (root / path).read_text(errors="replace")
        for number, line in enumerate(text.splitlines(), 1):
            if PROJECT_NAMES.search(line):
                found.append(f"{path}:{number}: {line.strip()[:100]}")
    return found


def test_no_file_of_the_plugin_names_a_project():
    assert project_names_in(REPO_ROOT, tracked_files()) == []


def test_the_guard_sees_a_planted_name(tmp_path):
    (tmp_path / "bugs_bot").mkdir()
    (tmp_path / "docs").mkdir()
    (tmp_path / "bugs_bot" / "probe.py").write_text("ok\n# served by torrentMATE\n")
    (tmp_path / "docs" / "spec.md").write_text("TorrentMate\n")
    (tmp_path / "tests").mkdir()
    (tmp_path / SELF).write_text("PersonalScraper\n")

    found = project_names_in(tmp_path, ["bugs_bot/probe.py", "docs/spec.md", SELF])

    assert found == ["bugs_bot/probe.py:2: # served by torrentMATE"]
