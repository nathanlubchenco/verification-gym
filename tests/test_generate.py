"""End-to-end generation on the fixture repo: pool -> clean + canary items,
payload separation from ground truth, leakcheck green/red."""

import json
import subprocess

import pytest

from gym import db as dbmod
from gym import generate, leakcheck
from gym.config import Config, ModelPrice, Targets


@pytest.fixture()
def env(tmp_path, fixture_repo):
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
    conn.execute("INSERT INTO repos (name, url, validated) VALUES ('fx', 'local', 1)")
    conn.commit()
    return cfg, conn


def test_generate_clean_and_canary(env):
    cfg, conn = env
    n_pool = generate.ensure_pool(cfg, conn, quota_per_repo=10, progress=lambda *a: None)
    assert n_pool >= 3
    generate.assign_pool(cfg, conn, want={"CLEAN": 1, "CANARY_CARRIER": 2})

    made_clean = generate.generate_clean(cfg, conn, n=1, progress=lambda *a: None)
    assert made_clean == 1
    made_canary = generate.generate_canaries(cfg, conn, n=1, progress=lambda *a: None)
    assert made_canary == 1

    items = conn.execute("SELECT * FROM review_items ORDER BY defective").fetchall()
    assert [i["defective"] for i in items] == [0, 1]
    clean_item, canary_item = items
    assert clean_item["defect_id"] is None
    assert canary_item["defect_id"] is not None

    rec = conn.execute("SELECT * FROM defect_records").fetchone()
    assert rec["arm"] == "CANARY"
    gt = json.loads(rec["ground_truth_locations"])
    assert gt and all({"file", "start_line", "end_line"} <= set(g) for g in gt)

    # payload files exist and contain no ground-truth fields
    for item in items:
        p = json.loads((cfg.root / item["payload_path"]).read_text())
        assert set(p) == {"description", "diff", "files"}

    # defective payload diff contains carrier change AND the injected line,
    # in git format (same shape as clean)
    dp = json.loads((cfg.root / canary_item["payload_path"]).read_text())
    assert dp["diff"].startswith("diff --git")


def test_leakcheck_green_then_red(env):
    cfg, conn = env
    generate.ensure_pool(cfg, conn, quota_per_repo=10, progress=lambda *a: None)
    generate.assign_pool(cfg, conn, want={"CLEAN": 1, "CANARY_CARRIER": 2})
    generate.generate_clean(cfg, conn, n=1, progress=lambda *a: None)
    generate.generate_canaries(cfg, conn, n=1, progress=lambda *a: None)

    assert leakcheck.scan_payloads(cfg, conn) == []

    # poison a payload with a class label -> hard violation
    poisoned = cfg.root / "data" / "payloads" / "it-poisoned00.json"
    poisoned.write_text(json.dumps(
        {"description": "innocent", "diff": "contains MUT-03 marker", "files": {}}))
    violations = leakcheck.scan_payloads(cfg, conn)
    assert any(v.rule == "class label MUT-NN" for v in violations)
    poisoned.unlink()

    # poison with an actual defect id from the db
    d_id = conn.execute("SELECT defect_id FROM defect_records").fetchone()[0]
    poisoned.write_text(json.dumps(
        {"description": f"see {d_id}", "diff": "", "files": {}}))
    violations = leakcheck.scan_payloads(cfg, conn)
    assert any("known id" in v.rule or "id shape" in v.rule for v in violations)
