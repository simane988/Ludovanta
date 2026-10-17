"""ludovanta.py feedback: the friction log in docs/feedback-log.md."""
import json
import os
import subprocess
import sys
from datetime import date, timedelta

import pytest

from helpers import NO_WINDOW, PLATFORM_DIR, git, read, write

CLI = PLATFORM_DIR / "ludovanta.py"
LOG = "docs/feedback-log.md"


def cli(project, *args):
    """Decodes output as UTF-8 explicitly: entries are usually in the user's language."""
    env = {k: v for k, v in os.environ.items() if k != "PYTHONIOENCODING"}
    p = subprocess.run([sys.executable, "-B", str(CLI), "--project", str(project), "feedback", *args],
                       capture_output=True, encoding="utf-8", errors="strict", env=env,
                       creationflags=NO_WINDOW)
    return p.returncode, p.stdout + p.stderr


@pytest.fixture
def game(make_project):
    return make_project(with_git=False)


def test_add_creates_log(game):
    code, out = cli(game, "add", "Codex трижды переписал тесты | они всё ещё красные", "--doing", "T-012 счётчик",
                    "--severity", "3")
    assert code == 0, out
    assert out.startswith(f"FEEDBACK_ADDED: {LOG}, severity 3")
    text = read(game / LOG)
    assert text.startswith("# Friction log")
    assert text.endswith(f"| {date.today().isoformat()} | 3 | T-012 счётчик | "
                         "Codex трижды переписал тесты \\| они всё ещё красные |\n")


def test_add_keeps_user_text_and_line_endings(game):
    write(game / LOG, "# Мой журнал\r\n\r\n| Date | Severity | Doing | What got in the way |\r\n|---|---|---|---|\r\n"
                      "| 2026-01-02 | 1 | ручная запись | долго ставится |")
    code, out = cli(game, "add", "много\nстрок   текста")
    assert code == 0, out
    text = read(game / LOG)
    assert text.startswith("# Мой журнал\r\n")
    assert text.endswith(f"| 2026-01-02 | 1 | ручная запись | долго ставится |\r\n"
                         f"| {date.today().isoformat()} | 2 | - | много строк текста |\r\n")


def test_show_recent_most_severe_first(game):
    cli(game, "add", "мелочь", "--severity", "1")
    cli(game, "add", "блокер", "--severity", "3", "--doing", "установка")
    old = (date.today() - timedelta(days=30)).isoformat()
    write(game / LOG, read(game / LOG) + f"| {old} | 3 | давно | старая проблема |\n")

    code, out = cli(game, "show")
    assert code == 0, out
    lines = out.splitlines()
    assert lines[0].startswith("FEEDBACK: 2 entries for the last 7 days (severity 1 x 3, 0 x 2, 1 x 1), 3 in total")
    assert lines[1].endswith("3 [установка] блокер") and lines[2].endswith("1 мелочь")
    assert "старая" not in out

    code, out = cli(game, "show", "--days", "0", "--json")
    data = json.loads(out)
    assert [e["problem"] for e in data["entries"]] == ["старая проблема", "блокер", "мелочь"]


def test_show_without_log(game):
    code, out = cli(game, "show")
    assert code == 0, out
    assert out.startswith("NO_FEEDBACK")


def test_parallel_entries_merge_without_conflict(installed_project):
    """Two worktrees append to the log; .gitattributes (merge=union) keeps both rows."""
    p = installed_project
    cli(p, "add", "first entry")
    git(p, "add", "-A")
    git(p, "commit", "--quiet", "-m", "log")
    git(p, "checkout", "--quiet", "-b", "other")
    cli(p, "add", "from the other branch")
    git(p, "commit", "--quiet", "-am", "other")
    git(p, "checkout", "--quiet", "main")
    cli(p, "add", "from main")
    git(p, "commit", "--quiet", "-am", "main")
    git(p, "merge", "--quiet", "--no-edit", "other")
    text = read(p / LOG)
    assert "from main" in text and "from the other branch" in text and "<<<<<<<" not in text
