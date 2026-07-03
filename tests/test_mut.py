"""MUT operators: site discovery, sanity guards, and generation flow."""

import subprocess

import pytest

from gym.arms.mut import find_sites, generate_mut

CODE = '''\
def check(a, b, limit=10, strict=True):
    if a < b and b == limit:
        return True
    if not strict:
        return compare(a, b)
    try:
        risky()
    except ValueError:
        raise RuntimeError("bad")
'''


def test_find_sites_per_class():
    sites = find_sites("m.py", CODE)
    assert any("a <= b" in e.new for e in sites["MUT-01"])
    assert any(" or " in e.new or "!=" in e.new or e.new.strip() == "if strict:"
               for e in sites["MUT-02"])
    assert any("compare(b, a)" in e.new for e in sites["MUT-03"])
    assert any(e.new.strip() == "pass" for e in sites["MUT-04"])
    assert any("limit=100" in e.new or "strict=False" in e.new
               for e in sites["MUT-05"])


def test_no_sites_inside_strings_or_comments():
    code = 's = "a < b and c == d"\n# if a < b:\nx = 1\n'
    sites = find_sites("m.py", code)
    assert not sites["MUT-01"] and not sites["MUT-02"]  # AST-equality guard


def test_mut04_requires_except_context():
    code = "def f():\n    raise ValueError()\n"
    assert not find_sites("m.py", code)["MUT-04"]


@pytest.fixture()
def env(tmp_path, fixture_repo):
    from gym import db as dbmod
    from gym import generate
    from gym.config import Config, ModelPrice, Targets

    cfg = Config(
        seed=7, generator_model="m", verifier_model="m", spend_cap_usd=1.0,
        data_dir="data", events_dir="events", reports_dir="reports",
        payload_budget_chars=100000, targets=Targets(1, 1, 0.4),
        pricing={"m": ModelPrice(5.0, 25.0)}, repos=[], root=tmp_path,
    )
    dest = tmp_path / "data" / "repos" / "fx"
    dest.parent.mkdir(parents=True)
    subprocess.run(["git", "clone", "-q", str(fixture_repo), str(dest)], check=True)
    conn = dbmod.connect(cfg.db_path)
    conn.execute("INSERT INTO repos (name, url, validated) VALUES ('fx','local',1)")
    conn.commit()
    generate.ensure_pool(cfg, conn, quota_per_repo=10, progress=lambda *a: None)
    generate.assign_pool(cfg, conn, want={"MUT_CARRIER": 3})
    return cfg, conn


def test_generate_mut_creates_items(env):
    cfg, conn = env
    made = generate_mut(cfg, conn, n_per_class=1, progress=lambda *a: None)
    # fixture repo's clamp commit offers MUT-01 sites (x < lo, x > hi)
    assert made["MUT-01"] >= 1
    row = conn.execute(
        "SELECT d.*, i.item_id FROM defect_records d JOIN review_items i"
        " ON i.defect_id=d.defect_id WHERE d.arm='MUT'").fetchone()
    assert row["class"].startswith("MUT-")
    assert row["ground_truth_diff"].startswith("diff --git")
    # idempotent: re-run creates nothing new at same target
    again = generate_mut(cfg, conn, n_per_class=1, progress=lambda *a: None)
    assert again == made
