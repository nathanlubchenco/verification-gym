"""CLEAN-pool mining filters (HANDOFF §5 Arm 0, DECISIONS D5/D13)."""

import random
import subprocess
from datetime import datetime, timezone

import pytest

from gym import mine


def git(repo, *args, env_date=None):
    import os
    env = dict(os.environ)
    if env_date:
        env["GIT_AUTHOR_DATE"] = env_date
        env["GIT_COMMITTER_DATE"] = env_date
    return subprocess.run(["git", "-C", str(repo), *args], check=True,
                          capture_output=True, text=True, env=env).stdout


@pytest.fixture()
def mining_repo(tmp_path):
    repo = tmp_path / "mrepo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.email", "t@example.com")
    git(repo, "config", "user.name", "T")

    def commit(msg, date, **files):
        for name, content in files.items():
            (repo / name).write_text(content)
        git(repo, "add", "-A")
        git(repo, "commit", "-q", "-m", msg, env_date=date)

    commit("initial", "2019-01-01T00:00:00",
           **{"util.py": "def f():\n    return 1\n",
              "helper.py": "def h():\n    return 2\n",
              "docs.md": "# docs\n"})
    # candidate A: later overlapping fix within 6 months -> must be rejected
    commit("feat: extend f", "2020-01-01T00:00:00",
           **{"util.py": "def f():\n    return 1\n\ndef g():\n    return 3\n"})
    commit("fix: bug in g crashed", "2020-03-01T00:00:00",
           **{"util.py": "def f():\n    return 1\n\ndef g():\n    return 4\n"})
    # candidate B: clean (later fix exists but >6 months after)
    commit("feat: extend h", "2020-04-01T00:00:00",
           **{"helper.py": "def h():\n    return 2\n\ndef i():\n    return 5\n"})
    commit("fix: i regression", "2021-06-01T00:00:00",
           **{"helper.py": "def h():\n    return 2\n\ndef i():\n    return 6\n"})
    # docs-only commit: excluded
    commit("docs: update", "2020-05-01T00:00:00", **{"docs.md": "# docs v2\n"})
    # too recent: window not observable
    commit("feat: recent change", "2026-06-01T00:00:00",
           **{"helper.py": "def h():\n    return 2\n\ndef i():\n    return 6\n# recent\n"})
    return repo


NOW = datetime(2026, 7, 2, tzinfo=timezone.utc)


def test_mine_rejects_later_fixed_and_docs_and_recent(mining_repo):
    pool = mine.mine_clean_pool(mining_repo, quota=10, rng=random.Random(1), now=NOW)
    subjects = {c.subject for c in pool}
    assert "feat: extend h" in subjects          # candidate B survives
    assert "feat: extend f" not in subjects      # rejected: overlapping fix in window
    assert "docs: update" not in subjects        # no .py files
    assert "feat: recent change" not in subjects  # too recent
    # fix commits themselves are eligible carriers/clean unless later-fixed; the
    # 2020-03 fix has no later fix touching util.py within 6 months
    assert "fix: bug in g crashed" in subjects


def test_quota_respected(mining_repo):
    pool = mine.mine_clean_pool(mining_repo, quota=1, rng=random.Random(1), now=NOW)
    assert len(pool) == 1


def test_deterministic_given_seed(mining_repo):
    a = mine.mine_clean_pool(mining_repo, quota=10, rng=random.Random(9), now=NOW)
    b = mine.mine_clean_pool(mining_repo, quota=10, rng=random.Random(9), now=NOW)
    assert [c.sha for c in a] == [c.sha for c in b]
