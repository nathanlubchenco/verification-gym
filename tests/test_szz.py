"""SZZ arm: fix detection, blame-to-introducer, GT mapping, end-to-end on a
fixture history with a known defect-introducing commit (no API: scripted labeler)."""

import json
import subprocess

import pytest

from gym.arms import szz


def git(repo, *args, env_date=None):
    import os
    env = dict(os.environ)
    if env_date:
        env["GIT_AUTHOR_DATE"] = env_date
        env["GIT_COMMITTER_DATE"] = env_date
    return subprocess.run(["git", "-C", str(repo), *args], check=True,
                          capture_output=True, text=True, env=env).stdout


@pytest.fixture()
def szz_repo(tmp_path):
    repo = tmp_path / "szzrepo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.email", "t@example.com")
    git(repo, "config", "user.name", "T")

    def commit(msg, date, **files):
        for name, content in files.items():
            (repo / name).write_text(content)
        git(repo, "add", "-A")
        git(repo, "commit", "-q", "-m", msg, env_date=date)

    commit("initial", "2020-01-01T00:00:00",
           **{"calc.py": "def half(x):\n    return x / 2\n"})
    # the defect-introducing commit: integer division regression
    commit("perf: use integer ops", "2020-02-01T00:00:00",
           **{"calc.py": "def half(x):\n    return x // 2\n"})
    commit("unrelated", "2020-03-01T00:00:00", **{"other.py": "A = 1\n"})
    # the fix commit referencing a bug
    commit("fix: half() truncated floats, closes #12 (bug)", "2020-06-01T00:00:00",
           **{"calc.py": "def half(x):\n    return x / 2\n"})
    return repo


def test_find_fix_commits(szz_repo):
    fixes = szz.find_fix_commits(szz_repo)
    assert len(fixes) == 1
    assert fixes[0].subject.startswith("fix: half()")


def test_blame_maps_to_introducer(szz_repo):
    from gym import gitrepo

    fix = szz.find_fix_commits(szz_repo)[0]
    intro_map = szz.blame_introducers(szz_repo, fix)
    commits = {c.subject: c.sha for c in gitrepo.log_commits(szz_repo)}
    intro_sha = commits["perf: use integer ops"]
    assert intro_sha in intro_map
    assert "calc.py" in intro_map[intro_sha]
    gt = szz._gt_from_blamed_lines(szz_repo, intro_sha, intro_map[intro_sha])
    # blamed content "return x // 2" is line 2 of calc.py at the introducer
    assert gt == {"calc.py": [(2, 2)]}


def test_generate_szz_end_to_end(szz_repo, tmp_path, monkeypatch):
    from gym import db as dbmod
    from gym.config import Config, ModelPrice, Targets
    import gym.arms.szz as szzmod

    cfg = Config(
        seed=7, generator_model="m", verifier_model="m", spend_cap_usd=5.0,
        data_dir="data", events_dir="events", reports_dir="reports",
        payload_budget_chars=100000, targets=Targets(1, 1, 0.4),
        pricing={"m": ModelPrice(5.0, 25.0)}, repos=[], root=tmp_path,
    )
    dest = tmp_path / "data" / "repos" / "fx"
    dest.parent.mkdir(parents=True)
    subprocess.run(["git", "clone", "-q", str(szz_repo), str(dest)], check=True)
    conn = dbmod.connect(cfg.db_path)
    conn.execute("INSERT INTO repos (name, url, validated) VALUES ('fx','local',1)")
    conn.commit()

    monkeypatch.setattr(szzmod, "label_defect",
                        lambda *a, **k: ("MUT-01", "scripted rationale"))
    made = szzmod.generate_szz(cfg, conn, target=5, progress=lambda *a: None)
    assert made == 1
    rec = conn.execute("SELECT * FROM defect_records WHERE arm='SZZ'").fetchone()
    assert rec["class"] == "MUT-01"
    prov = json.loads(rec["provenance"])
    assert prov["szz_source"] == "szz" and prov["fix_sha"]
    gt = json.loads(rec["ground_truth_locations"])
    assert gt == [{"file": "calc.py", "start_line": 2, "end_line": 2}]
    # audit sample dumped
    files = list((tmp_path / "audit" / "szz_sample").glob("*.json"))
    assert len(files) == 1
