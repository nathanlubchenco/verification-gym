"""`gym score`: pre-specified metrics (HANDOFF §7 — do not extend or trim) and
the gym-events/1 stream (Appendix B).

Definitions fixed in DECISIONS: D9 (location overlap, ±2 slop), D14 (canaries
excluded from §7 metrics; separate gate), D15 (AUROC/Brier score construction).
"""

from __future__ import annotations

import json
import math
import random
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from .config import Config

EVENT_SCHEMA = "gym-events/1"
OVERLAP_SLOP = 2
BOOTSTRAP_REPS = 2000
ARM_GAP_MIN_N = 15
LOW_POWER_FLOOR_KEY = "low_power"


# ---------- primitives ----------

def wilson_ci(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 1.0)
    phat = k / n
    denom = 1 + z * z / n
    center = (phat + z * z / (2 * n)) / denom
    half = z * math.sqrt(phat * (1 - phat) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, center - half), min(1.0, center + half))


def auroc(pos: list[float], neg: list[float]) -> float | None:
    if not pos or not neg:
        return None
    wins = 0.0
    for p in pos:
        for q in neg:
            if p > q:
                wins += 1.0
            elif p == q:
                wins += 0.5
    return wins / (len(pos) * len(neg))


def brier_and_bins(pairs: list[tuple[float, bool]], nbins: int = 10):
    """pairs: (p_defective, actually_defective). Returns (brier, reliability bins)."""
    if not pairs:
        return None, []
    brier = sum((p - (1.0 if y else 0.0)) ** 2 for p, y in pairs) / len(pairs)
    bins = []
    for b in range(nbins):
        lo, hi = b / nbins, (b + 1) / nbins
        members = [(p, y) for p, y in pairs
                   if (lo <= p < hi) or (b == nbins - 1 and p == 1.0)]
        if members:
            bins.append({
                "bin_lo": lo, "bin_hi": hi, "n": len(members),
                "mean_p": sum(p for p, _ in members) / len(members),
                "frac_defective": sum(1 for _, y in members if y) / len(members),
            })
    return brier, bins


def bootstrap_gap_ci(gen_outcomes: list[int], szz_outcomes: list[int],
                     seed: int, reps: int = BOOTSTRAP_REPS):
    """Percentile bootstrap CI for detection(GEN) - detection(SZZ)."""
    rng = random.Random(f"gap:{seed}")
    delta = sum(gen_outcomes) / len(gen_outcomes) - sum(szz_outcomes) / len(szz_outcomes)
    deltas = []
    for _ in range(reps):
        g = [rng.choice(gen_outcomes) for _ in gen_outcomes]
        s = [rng.choice(szz_outcomes) for _ in szz_outcomes]
        deltas.append(sum(g) / len(g) - sum(s) / len(s))
    deltas.sort()
    lo = deltas[int(0.025 * reps)]
    hi = deltas[min(reps - 1, int(0.975 * reps))]
    return delta, lo, hi


def _norm_path(p: str) -> str:
    for prefix in ("a/", "b/", "./"):
        if p.startswith(prefix):
            p = p[len(prefix):]
    return p


def location_overlap(gt: list[dict], reported: list[dict],
                     slop: int = OVERLAP_SLOP) -> bool:
    for g in gt:
        gf = _norm_path(g["file"])
        for r in reported:
            if _norm_path(r["file"]) != gf:
                continue
            if (g["start_line"] - slop <= r["end_line"]
                    and r["start_line"] - slop <= g["end_line"]):
                return True
    return False


def outcome_for(defective: bool, verdict: dict | None, abstained: bool,
                gt: list[dict]) -> str:
    if abstained or verdict is None:
        return "abstained"
    if not defective:
        return "false_positive" if verdict["defect_found"] else "true_negative"
    if not verdict["defect_found"]:
        return "missed"
    return "detected" if location_overlap(gt, verdict["locations"]) else "misdirected_flag"


def defectiveness_p(verdict: dict | None) -> float | None:
    """D15: p(defective) from (defect_found, confidence)."""
    if verdict is None:
        return None
    c = verdict["confidence"]
    return (c if verdict["defect_found"] else 100.0 - c) / 100.0


# ---------- collection ----------

@dataclass
class ItemResult:
    item_id: str
    repo: str
    defective: bool
    arm: str            # CLEAN | MUT | GEN | SZZ | CANARY
    klass: str | None
    verdict: dict | None
    abstained: bool
    gt: list[dict]
    outcome: str
    tokens_in: int
    tokens_out: int
    latency_ms: int
    cost_usd: float
    prompt_hash: str
    ts: str
    provenance: dict


def collect(cfg: Config, conn: sqlite3.Connection, run_id: str) -> list[ItemResult]:
    rows = conn.execute(
        """SELECT i.item_id, i.repo, i.defective, v.verdict_json, v.abstained,
                  v.tokens_in, v.tokens_out, v.latency_ms, v.cost_usd,
                  v.prompt_hash, v.created_at,
                  d.arm, d.class AS klass, d.ground_truth_locations, d.provenance
           FROM verdicts v
           JOIN review_items i ON i.item_id = v.item_id
           LEFT JOIN defect_records d ON d.defect_id = i.defect_id
           WHERE v.run_id = ? ORDER BY i.item_id""",
        (run_id,),
    ).fetchall()
    results = []
    for r in rows:
        verdict = json.loads(r["verdict_json"]) if r["verdict_json"] else None
        gt = json.loads(r["ground_truth_locations"]) if r["ground_truth_locations"] else []
        defective = bool(r["defective"])
        results.append(ItemResult(
            item_id=r["item_id"], repo=r["repo"], defective=defective,
            arm=(r["arm"] or "CLEAN"), klass=r["klass"],
            verdict=verdict, abstained=bool(r["abstained"]), gt=gt,
            outcome=outcome_for(defective, verdict, bool(r["abstained"]), gt),
            tokens_in=r["tokens_in"] or 0, tokens_out=r["tokens_out"] or 0,
            latency_ms=r["latency_ms"] or 0, cost_usd=r["cost_usd"] or 0.0,
            prompt_hash=r["prompt_hash"] or "", ts=r["created_at"],
            provenance=json.loads(r["provenance"]) if r["provenance"] else {},
        ))
    return results


# ---------- §7 computation ----------

def compute_scores(cfg: Config, results: list[ItemResult]) -> dict:
    metric = [r for r in results if r.arm != "CANARY"]      # D14
    clean = [r for r in metric if not r.defective]
    defective = [r for r in metric if r.defective]

    def cell(rs: list[ItemResult]) -> dict:
        n = len(rs)
        det = sum(1 for r in rs if r.outcome == "detected")
        lo, hi = wilson_ci(det, n)
        return {
            "n": n, "detected": det,
            "missed": sum(1 for r in rs if r.outcome == "missed"),
            "misdirected_flag": sum(1 for r in rs if r.outcome == "misdirected_flag"),
            "abstained": sum(1 for r in rs if r.outcome == "abstained"),
            "rate": det / n if n else None, "ci95": [lo, hi],
            LOW_POWER_FLOOR_KEY: n < cfg.targets.floor_per_class,
        }

    per_class_arm: dict[str, dict] = {}
    for r in defective:
        key = f"{r.arm}/{r.klass}"
        per_class_arm.setdefault(key, [])
    for key in per_class_arm:
        arm, klass = key.split("/", 1)
        per_class_arm[key] = cell([r for r in defective
                                   if r.arm == arm and r.klass == klass])
    per_arm = {arm: cell([r for r in defective if r.arm == arm])
               for arm in sorted({r.arm for r in defective})}

    fp = sum(1 for r in clean if r.outcome == "false_positive")
    fp_lo, fp_hi = wilson_ci(fp, len(clean))

    # §7.3 arm gap at matched class (GEN - SZZ), bootstrap CI
    arm_gap = {}
    classes = sorted({r.klass for r in defective if r.klass})
    for klass in classes:
        g = [r for r in defective if r.arm == "GEN" and r.klass == klass
             and not r.abstained]
        s = [r for r in defective if r.arm == "SZZ" and r.klass == klass
             and not r.abstained]
        if len(g) >= ARM_GAP_MIN_N and len(s) >= ARM_GAP_MIN_N:
            gd = [1 if r.outcome == "detected" else 0 for r in g]
            sd = [1 if r.outcome == "detected" else 0 for r in s]
            delta, lo, hi = bootstrap_gap_ci(gd, sd, seed=cfg.seed)
            arm_gap[klass] = {"n_gen": len(g), "n_szz": len(s),
                              "delta": delta, "ci95": [lo, hi]}

    # secondary: AUROC per class (D15), calibration, localization, cost
    neg_scores = [p for r in clean if (p := defectiveness_p(r.verdict)) is not None]
    auroc_per_class = {}
    for klass in classes:
        pos = [p for r in defective if r.klass == klass
               and (p := defectiveness_p(r.verdict)) is not None]
        auroc_per_class[klass] = auroc(pos, neg_scores)

    pairs = [(p, r.defective) for r in metric
             if (p := defectiveness_p(r.verdict)) is not None]
    brier, bins = brier_and_bins(pairs)

    flagged_defective = [r for r in defective
                         if r.verdict and r.verdict["defect_found"]]
    loc_precision = (sum(1 for r in flagged_defective if r.outcome == "detected")
                     / len(flagged_defective)) if flagged_defective else None
    misdirected_rate = (sum(1 for r in defective if r.outcome == "misdirected_flag")
                        / len(defective)) if defective else None

    def cost_cell(rs):
        n = len(rs)
        if not n:
            return None
        return {"n": n,
                "mean_tokens_in": sum(r.tokens_in for r in rs) / n,
                "mean_tokens_out": sum(r.tokens_out for r in rs) / n,
                "mean_latency_ms": sum(r.latency_ms for r in rs) / n,
                "mean_cost_usd": sum(r.cost_usd for r in rs) / n}

    cost = {"CLEAN": cost_cell(clean)}
    for klass in classes:
        cost[klass] = cost_cell([r for r in defective if r.klass == klass])

    canaries = [r for r in results if r.arm == "CANARY"]
    canary_detected = sum(1 for r in canaries if r.outcome == "detected")

    return {
        "n_items": len(metric),
        "per_class_arm": dict(sorted(per_class_arm.items())),
        "per_arm": per_arm,
        "false_positive": {"n_clean": len(clean), "fp": fp,
                           "rate": fp / len(clean) if clean else None,
                           "ci95": [fp_lo, fp_hi]},
        "arm_gap_gen_minus_szz": arm_gap,
        "auroc_per_class": auroc_per_class,
        "brier": brier,
        "calibration_bins": bins,
        "localization_precision": loc_precision,
        "misdirected_flag_rate": misdirected_rate,
        "abstention": {"n": sum(1 for r in metric if r.outcome == "abstained"),
                       "rate": (sum(1 for r in metric if r.outcome == "abstained")
                                / len(metric)) if metric else None},
        "cost_per_review": cost,
        "canary_gate": {"n": len(canaries), "detected": canary_detected,
                        "rate": canary_detected / len(canaries) if canaries else None,
                        "pass": (len(canaries) > 0
                                 and canary_detected / len(canaries) >= 0.9)},
    }


# ---------- events (Appendix B) ----------

def emit_events(cfg: Config, conn: sqlite3.Connection, run_id: str,
                results: list[ItemResult]) -> Path:
    events_dir = cfg.root / cfg.events_dir
    events_dir.mkdir(parents=True, exist_ok=True)
    out = events_dir / f"run_{run_id}.jsonl"
    with out.open("w") as f:
        for r in sorted(results, key=lambda x: x.item_id):
            if r.arm == "CANARY":
                continue  # Appendix B arm enum is CLEAN|MUT|GEN|SZZ; canaries
                          # are pipeline self-audit only (D14)
            event = {
                "schema": EVENT_SCHEMA,
                "ts": r.ts, "run_id": run_id, "repo": r.repo,
                "item_id": r.item_id, "arm": r.arm, "class": r.klass,
                "generator_model": cfg.generator_model if r.arm == "GEN" else None,
                "verifier_model": cfg.verifier_model,
                "verdict": r.verdict,
                "ground_truth": {"defective": r.defective, "class": r.klass},
                "outcome": r.outcome,
                "tokens_in": r.tokens_in, "tokens_out": r.tokens_out,
                "latency_ms": r.latency_ms, "cost_usd": r.cost_usd,
                "seed": cfg.seed, "prompt_hash": r.prompt_hash,
            }
            f.write(json.dumps(event, sort_keys=True) + "\n")
    return out
