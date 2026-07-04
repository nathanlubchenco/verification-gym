"""Metric primitives against hand-computed values, plus outcome classification."""

import pytest

from gym.score import (auroc, brier_and_bins, bootstrap_gap_ci, location_overlap,
                       outcome_for, wilson_ci)


def test_wilson_ci_known_value():
    lo, hi = wilson_ci(8, 10)
    assert lo == pytest.approx(0.4902, abs=1e-3)
    assert hi == pytest.approx(0.9433, abs=1e-3)


def test_wilson_ci_edges():
    assert wilson_ci(0, 0) == (0.0, 1.0)
    lo, hi = wilson_ci(0, 20)
    assert lo == 0.0 and hi < 0.2
    lo, hi = wilson_ci(20, 20)
    assert hi == 1.0 and lo > 0.8


def test_auroc_hand_computed():
    assert auroc([0.9, 0.8], [0.1, 0.85]) == pytest.approx(0.75)
    assert auroc([0.5], [0.5]) == pytest.approx(0.5)   # tie -> 0.5
    assert auroc([], [0.1]) is None


def test_brier():
    b, bins = brier_and_bins([(1.0, True), (0.0, False)])
    assert b == pytest.approx(0.0)
    b, _ = brier_and_bins([(0.7, True), (0.4, False)])
    assert b == pytest.approx(((0.7 - 1) ** 2 + 0.4 ** 2) / 2)


def test_location_overlap_slop_and_path_normalization():
    gt = [{"file": "pkg/a.py", "start_line": 10, "end_line": 12}]
    assert location_overlap(gt, [{"file": "b/pkg/a.py", "start_line": 13, "end_line": 14}])
    assert location_overlap(gt, [{"file": "./pkg/a.py", "start_line": 8, "end_line": 9}])
    assert not location_overlap(gt, [{"file": "pkg/a.py", "start_line": 20, "end_line": 25}])
    assert not location_overlap(gt, [{"file": "other.py", "start_line": 10, "end_line": 12}])


V_FOUND_AT = {"defect_found": True, "confidence": 90,
              "locations": [{"file": "a.py", "start_line": 5, "end_line": 6}],
              "class_guess": None, "severity": "high", "rationale": ""}
V_FOUND_ELSEWHERE = {**V_FOUND_AT,
                     "locations": [{"file": "a.py", "start_line": 50, "end_line": 51}]}
V_NOT_FOUND = {"defect_found": False, "confidence": 80, "locations": [],
               "class_guess": None, "severity": None, "rationale": ""}
GT = [{"file": "a.py", "start_line": 4, "end_line": 6}]


def test_outcome_for_all_cases():
    assert outcome_for(True, V_FOUND_AT, False, GT) == "detected"
    assert outcome_for(True, V_FOUND_ELSEWHERE, False, GT) == "misdirected_flag"
    assert outcome_for(True, V_NOT_FOUND, False, GT) == "missed"
    assert outcome_for(True, None, True, GT) == "abstained"
    assert outcome_for(False, V_FOUND_AT, False, []) == "false_positive"
    assert outcome_for(False, V_NOT_FOUND, False, []) == "true_negative"
    assert outcome_for(False, None, True, []) == "abstained"


def test_bootstrap_gap_ci_seeded_and_sane():
    gen = [1, 1, 1, 0] * 5   # 75% detection
    szz = [1, 0, 0, 0] * 5   # 25% detection
    delta, lo, hi = bootstrap_gap_ci(gen, szz, seed=1)
    assert delta == pytest.approx(0.5)
    assert lo < 0.5 < hi
    assert (delta, lo, hi) == bootstrap_gap_ci(gen, szz, seed=1)  # deterministic


def test_event_labels_come_from_run_records_not_config(tmp_path, monkeypatch):
    """Regression (found by external audit): events must label verifier/generator
    from the run's own records; config at emit time may be a different model."""
    import json
    import subprocess

    from gym import db as dbmod
    from gym import generate
    from gym.config import Config, ModelPrice, Targets
    from gym.review import run_reviews
    from gym.score import collect, emit_events

    cfg = Config(
        seed=7, generator_model="gen-model-x", verifier_model="ver-model-x",
        spend_cap_usd=5.0, data_dir="data", events_dir="events",
        reports_dir="reports", payload_budget_chars=100000,
        targets=Targets(1, 1, 0.4),
        pricing={"ver-model-x": ModelPrice(5.0, 25.0)}, repos=[], root=tmp_path,
    )
    # reuse the fixture repo builder inline
    repo = tmp_path / "src-repo"
    repo.mkdir()
    for args in (["init", "-q", "-b", "main"], ["config", "user.email", "t@e.c"],
                 ["config", "user.name", "T"]):
        subprocess.run(["git", "-C", str(repo), *args], check=True)
    (repo / "m.py").write_text("def f(a, b):\n    if a < b:\n        return a\n    return b\n")
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", "feat: add f",
                    "--date", "2020-01-01T00:00:00"], check=True,
                   env={**__import__("os").environ,
                        "GIT_COMMITTER_DATE": "2020-01-01T00:00:00"})
    dest = tmp_path / "data" / "repos" / "fx"
    dest.parent.mkdir(parents=True)
    subprocess.run(["git", "clone", "-q", str(repo), str(dest)], check=True)

    conn = dbmod.connect(cfg.db_path)
    conn.execute("INSERT INTO repos (name, url, validated) VALUES ('fx','local',1)")
    conn.commit()
    generate.ensure_pool(cfg, conn, quota_per_repo=5, progress=lambda *a: None)
    generate.assign_pool(cfg, conn, want={"CLEAN": 1})
    generate.generate_clean(cfg, conn, n=1, progress=lambda *a: None)

    class T:
        def complete(self, **kw):
            return {"text": json.dumps({"defect_found": False, "confidence": 9,
                                        "locations": [], "class_guess": None,
                                        "severity": None, "rationale": ""}),
                    "tokens_in": 10, "tokens_out": 5, "latency_ms": 1}

    run_reviews(cfg, conn, "r", transport=T(), progress=lambda *a: None)

    # emit under a DIFFERENT config (simulates emitting after a model switch)
    cfg2 = Config(**{**cfg.__dict__, "verifier_model": "other-model",
                     "generator_model": "other-gen"})
    out = emit_events(cfg2, conn, "r", collect(cfg2, conn, "r"))
    event = json.loads(out.read_text().splitlines()[0])
    assert event["verifier_model"] == "ver-model-x"   # from the run, not cfg2
    assert event["generator_model"] is None           # clean item: no generator
