"""Tests for gym.gitrepo plumbing against a fixture repo."""

from gym import gitrepo


def test_head_sha(fixture_repo):
    sha = gitrepo.head_sha(fixture_repo)
    assert len(sha) == 40


def test_log_commits_order_and_fields(fixture_repo):
    commits = gitrepo.log_commits(fixture_repo)
    assert len(commits) == 3
    # newest first
    assert commits[0].subject == "chore: add constant"
    assert commits[1].subject == "feat: add clamp helper"
    assert commits[1].body.strip() == "Adds a clamp function."
    assert commits[1].files == ["mod.py"]
    assert commits[2].files == ["LICENSE", "mod.py"]


def test_commit_diff_contains_hunk(fixture_repo):
    commits = gitrepo.log_commits(fixture_repo)
    diff = gitrepo.commit_diff(fixture_repo, commits[1].sha)
    assert "def clamp" in diff
    assert diff.startswith("diff --git")


def test_file_at(fixture_repo):
    commits = gitrepo.log_commits(fixture_repo)
    first = commits[-1].sha
    content = gitrepo.file_at(fixture_repo, first, "mod.py")
    assert "clamp" not in content
    head = gitrepo.file_at(fixture_repo, commits[0].sha, "mod.py")
    assert "clamp" in head


def test_first_commit_date(fixture_repo):
    d = gitrepo.first_commit_date(fixture_repo)
    assert d.year == 2020
