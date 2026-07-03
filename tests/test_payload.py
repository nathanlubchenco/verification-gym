"""Review payload construction + Appendix A prompt rendering."""

from gym import gitrepo, payload


def test_payload_from_commit(fixture_repo):
    commits = gitrepo.log_commits(fixture_repo)
    clamp_commit = commits[1]  # "feat: add clamp helper"
    p = payload.payload_from_commit(fixture_repo, clamp_commit.sha,
                                    clamp_commit.message)
    assert "clamp" in p.diff
    assert p.description.startswith("feat: add clamp helper")
    assert list(p.files) == ["mod.py"]
    assert "def clamp" in p.files["mod.py"]         # post-change content
    assert "def add" in p.files["mod.py"]


def test_render_prompt_is_appendix_a(fixture_repo):
    commits = gitrepo.log_commits(fixture_repo)
    p = payload.payload_from_commit(fixture_repo, commits[1].sha, commits[1].message)
    prompt = payload.render_prompt(p)
    assert prompt.startswith("You are reviewing a proposed code change before merge.")
    assert "<pr_description>" in prompt and "</pr_description>" in prompt
    assert "<diff>" in prompt and "</diff>" in prompt
    assert "<files>" in prompt and "</files>" in prompt
    assert '"defect_found": bool' in prompt
    assert "If the change is acceptable, defect_found is false" in prompt
    assert p.diff in prompt


def test_save_and_load_roundtrip(fixture_repo, tmp_path):
    commits = gitrepo.log_commits(fixture_repo)
    p = payload.payload_from_commit(fixture_repo, commits[1].sha, commits[1].message)
    path = payload.save_payload(tmp_path, "it-0a1b2c3d4e", p)
    q = payload.load_payload(path)
    assert q == p


def test_payload_chars(fixture_repo):
    commits = gitrepo.log_commits(fixture_repo)
    p = payload.payload_from_commit(fixture_repo, commits[1].sha, commits[1].message)
    assert payload.payload_chars(p) == len(payload.render_prompt(p))
