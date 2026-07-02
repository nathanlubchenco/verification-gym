"""Shared fixtures: a small git repo built on the fly for plumbing tests."""

import subprocess

import pytest


def git(repo, *args):
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True, capture_output=True, text=True,
    ).stdout


@pytest.fixture()
def fixture_repo(tmp_path):
    """Git repo with three commits touching a small python module."""
    repo = tmp_path / "fixture-repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.email", "t@example.com")
    git(repo, "config", "user.name", "T")

    (repo / "mod.py").write_text(
        "def add(a, b):\n    return a + b\n"
    )
    (repo / "LICENSE").write_text("MIT License\n\nPermission is hereby granted...")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "initial: add module", "--date", "2020-01-01T00:00:00")

    (repo / "mod.py").write_text(
        "def add(a, b):\n    return a + b\n\n"
        "def clamp(x, lo, hi):\n"
        "    if x < lo:\n        return lo\n"
        "    if x > hi:\n        return hi\n"
        "    return x\n"
    )
    git(repo, "add", "-A")
    git(
        repo, "commit", "-q", "-m", "feat: add clamp helper\n\nAdds a clamp function.",
        "--date", "2021-06-01T00:00:00",
    )

    (repo / "other.py").write_text("VALUE = 42\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "chore: add constant", "--date", "2021-07-01T00:00:00")

    return repo
