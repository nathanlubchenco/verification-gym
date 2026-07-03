"""Defect injection into carrier commits: presented diff + ground-truth locations."""

import pytest

from gym import gitrepo
from gym.inject import Edit, InjectionError, build_injected_change


def test_inject_produces_git_format_diff_and_gt(fixture_repo):
    commits = gitrepo.log_commits(fixture_repo)
    carrier = commits[1]  # "feat: add clamp helper", touches mod.py
    edit = Edit(path="mod.py", old="    if x < lo:", new="    if x <= lo:")
    change = build_injected_change(fixture_repo, carrier.sha, [edit])

    # presented diff: parent -> (carrier + defect), genuine git format
    assert change.presented_diff.startswith("diff --git")
    assert "clamp" in change.presented_diff          # carrier's real change
    assert "x <= lo" in change.presented_diff        # the injected defect
    # post-change file content includes the defect
    assert "if x <= lo:" in change.post_files["mod.py"]
    # ground truth points at the defect line only, in post-change coordinates
    assert list(change.gt_locations) == ["mod.py"]
    (start, end), = change.gt_locations["mod.py"]
    lines = change.post_files["mod.py"].splitlines()
    assert any("x <= lo" in lines[i - 1] for i in range(start, end + 1))


def test_inject_requires_exactly_one_match(fixture_repo):
    commits = gitrepo.log_commits(fixture_repo)
    carrier = commits[1]
    with pytest.raises(InjectionError):
        build_injected_change(fixture_repo, carrier.sha,
                              [Edit(path="mod.py", old="nonexistent", new="x")])
    with pytest.raises(InjectionError):  # "return" appears multiple times
        build_injected_change(fixture_repo, carrier.sha,
                              [Edit(path="mod.py", old="return", new="ret")])


def test_worktree_cleaned_up(fixture_repo):
    commits = gitrepo.log_commits(fixture_repo)
    carrier = commits[1]
    build_injected_change(fixture_repo, carrier.sha,
                          [Edit(path="mod.py", old="x < lo", new="x <= lo")])
    out = gitrepo.run_git(fixture_repo, "worktree", "list")
    assert len(out.strip().splitlines()) == 1  # only the main worktree remains
