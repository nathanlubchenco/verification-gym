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
