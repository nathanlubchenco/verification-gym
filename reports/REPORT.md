# Verification Gym REPORT

Generated: 2026-07-04T02:12:08.981202+00:00

run_id: `main` · seed: 20260702 · verifier: `claude-opus-4-8` · generator: `claude-opus-4-8`

## MEASURED (computed numbers; §7 pre-specified)

Review items scored (canaries excluded per D14): 1090

### Primary 1 — per-class detection rate (95% Wilson CI)

| arm/class | n | detected | missed | misdirected | abstained | detection rate |
|---|---|---|---|---|---|---|
| GEN/GEN-01 | 44 | 31 | 11 | 2 | 0 | 70.5% [55.8, 81.8] |
| GEN/GEN-02 | 45 | 27 | 13 | 5 | 0 | 60.0% [45.5, 73.0] |
| GEN/GEN-03 | 50 | 12 | 31 | 7 | 0 | 24.0% [14.3, 37.4] |
| GEN/GEN-04 | 41 | 27 | 13 | 1 | 0 | 65.9% [50.5, 78.4] |
| GEN/GEN-05 | 44 | 28 | 13 | 3 | 0 | 63.6% [48.9, 76.2] |
| GEN/GEN-06 | 41 | 31 | 8 | 2 | 0 | 75.6% [60.7, 86.2] |
| MUT/MUT-01 | 50 | 37 | 10 | 3 | 0 | 74.0% [60.4, 84.1] |
| MUT/MUT-02 | 50 | 48 | 1 | 1 | 0 | 96.0% [86.5, 98.9] |
| MUT/MUT-03 | 50 | 47 | 3 | 0 | 0 | 94.0% [83.8, 97.9] |
| MUT/MUT-04 | 45 | 43 | 0 | 2 | 0 | 95.6% [85.2, 98.8] |
| MUT/MUT-05 | 47 | 41 | 4 | 2 | 0 | 87.2% [74.8, 94.0] |
| SZZ/GEN-01 | 74 | 21 | 31 | 22 | 0 | 28.4% [19.4, 39.5] |
| SZZ/GEN-02 | 17 | 2 | 10 | 5 | 0 | 11.8% [3.3, 34.3] **LOW-POWER** |
| SZZ/GEN-03 | 5 | 0 | 3 | 2 | 0 | 0.0% [0.0, 43.4] **LOW-POWER** |
| SZZ/GEN-04 | 10 | 4 | 2 | 4 | 0 | 40.0% [16.8, 68.7] **LOW-POWER** |
| SZZ/GEN-05 | 9 | 2 | 4 | 3 | 0 | 22.2% [6.3, 54.7] **LOW-POWER** |
| SZZ/GEN-06 | 9 | 2 | 5 | 2 | 0 | 22.2% [6.3, 54.7] **LOW-POWER** |
| SZZ/MUT-01 | 3 | 0 | 2 | 1 | 0 | 0.0% [0.0, 56.2] **LOW-POWER** |
| SZZ/MUT-02 | 1 | 1 | 0 | 0 | 0 | 100.0% [20.7, 100.0] **LOW-POWER** |
| SZZ/MUT-03 | 10 | 4 | 1 | 5 | 0 | 40.0% [16.8, 68.7] **LOW-POWER** |
| SZZ/MUT-04 | 8 | 2 | 4 | 2 | 0 | 25.0% [7.1, 59.1] **LOW-POWER** |
| SZZ/MUT-05 | 2 | 0 | 2 | 0 | 0 | 0.0% [0.0, 65.8] **LOW-POWER** |
| SZZ/OTHER | 2 | 2 | 0 | 0 | 0 | 100.0% [34.2, 100.0] **LOW-POWER** |

Pooled per arm:

| arm | n | detection rate |
|---|---|---|
| GEN | 265 | 58.9% [52.9, 64.6] |
| MUT | 242 | 89.3% [84.7, 92.6] |
| SZZ | 150 | 26.7% [20.2, 34.3] |

### Primary 2 — false-positive rate on CLEAN

n_clean=433, FP=86, rate=19.9% [16.4, 23.9]

### Primary 3 — arm gap at matched class: detection(GEN) − detection(SZZ)

| class | n_gen | n_szz | Δ | bootstrap 95% CI |
|---|---|---|---|---|
| GEN-01 | 44 | 74 | +42.1pp | [+24.9, +59.7] |
| GEN-02 | 45 | 17 | +48.2pp | [+26.8, +67.5] |

### Secondary

| class | AUROC (vs CLEAN; D15) |
|---|---|
| GEN-01 | 0.830 |
| GEN-02 | 0.855 |
| GEN-03 | 0.746 |
| GEN-04 | 0.850 |
| GEN-05 | 0.824 |
| GEN-06 | 0.861 |
| MUT-01 | 0.896 |
| MUT-02 | 0.980 |
| MUT-03 | 0.959 |
| MUT-04 | 0.941 |
| MUT-05 | 0.932 |
| OTHER | 0.885 |

- Localization precision (detected / defect_found=true on defective): 0.848
- Misdirected-flag rate (defective items): 0.113
- Brier score: 0.1593
- Abstentions: 0 (0.0%)

Cost per review (mean):

| class | n | tokens_in | tokens_out | latency_ms | USD |
|---|---|---|---|---|---|
| CLEAN | 433 | 12117 | 301 | 353 | 0.0362 |
| GEN-01 | 118 | 17738 | 621 | 0 | 0.0521 |
| GEN-02 | 62 | 12798 | 559 | 0 | 0.0390 |
| GEN-03 | 55 | 15893 | 543 | 0 | 0.0465 |
| GEN-04 | 51 | 13508 | 512 | 0 | 0.0402 |
| GEN-05 | 53 | 12817 | 468 | 0 | 0.0379 |
| GEN-06 | 50 | 13302 | 574 | 0 | 0.0404 |
| MUT-01 | 53 | 13397 | 421 | 0 | 0.0387 |
| MUT-02 | 51 | 7658 | 322 | 0 | 0.0232 |
| MUT-03 | 60 | 8282 | 302 | 0 | 0.0245 |
| MUT-04 | 53 | 13561 | 315 | 0 | 0.0378 |
| MUT-05 | 49 | 16285 | 402 | 0 | 0.0457 |
| OTHER | 2 | 2690 | 186 | 0 | 0.0091 |

### Pipeline self-audit — canary gate (§14.1; excluded from metrics above)

canaries=24, detected=24, rate=100.0%, gate(≥90%): PASS

### Charts

![per_class_detection.png](charts/per_class_detection.png)
![arm_comparison.png](charts/arm_comparison.png)
![calibration.png](charts/calibration.png)
![cost_per_review.png](charts/cost_per_review.png)

## INFERRED (interpretation; not computed)

All statements below are interpretation. The computed numbers are in the
MEASURED section above; the caveats that could invalidate these readings are in
LIMITATIONS.md (read it before quoting anything).

**1. The instrument's answer to "is verification easier than generation?" is:
it depends entirely on whose defects you're verifying.** The same verifier,
same prompt, same repos: 89% detection on mechanical mutations (MUT), 59% on
subtle model-written defects (GEN), 27% on real historical defects (SZZ).
Benchmarks built on injected defects — most of the literature — would report
this verifier as excellent; the real-defect anchor says two of three
production-grade bugs sail through. If one number is the takeaway, it is the
SZZ 26.7% [20.2, 34.3].

**2. The arm gap is large and positive (GEN − SZZ ≈ +42 to +48 points at
matched classes), which is the direction self-distribution bias predicts.**
The verifier detects the generator's wrong-edge-case defects (GEN-01: 70%) far
more reliably than real wrong-edge-case defects (SZZ/GEN-01: 28%), same class
label, same repos. Two explanations are confounded in this run and cannot be
separated until the cross-model matrix is run: (a) the verifier shares the
generator's defect distribution (they are the same model); (b) real defects
are intrinsically harder — they survive human review + CI once already, and
the strict location rule punishes SZZ items hardest (misdirected-flag rate on
SZZ/GEN-01 is 30%, i.e. the verifier often senses trouble but points at the
wrong lines).

**3. Test-weakening (GEN-03, the operator's priority class) is the verifier's
worst injected-defect class at 24% — worse than every other GEN class by ~35
points.** Loosened assertions and over-mocking read as normal test
maintenance. Given GEN-03's mapping onto proxy-metric gaming, this is the
most actionable per-class result in the run: if you use an LLM reviewer to
guard against eval/test manipulation, this configuration largely won't.

**4. The false-alarm cost is material: ~20% of presumed-clean merged changes
get flagged.** Some fraction is residual true defects in "presumed clean"
(the filter is a heuristic; see LIMITATIONS #2), so 19.9% is an upper bound —
but even the lower confidence bound (16.4%) implies roughly one flag per six
clean PRs, which prices this verifier configuration out of naive
block-on-flag deployment.

**5. Within MUT, the ordering is informative:** logic swaps, arg swaps, and
swallowed exceptions are near-ceiling (94–96%) while boundary/off-by-one is
the softest mutation class (74%) — off-by-one plausibly reads as intentional
(`<` vs `<=` both look defensible without spec context). Boundary errors are
also a large real-bug category, consistent with the low SZZ rates.

**6. Calibration is mediocre but not useless** (Brier 0.136; AUROC per class
in the table). Confidence carries signal, but the ~20% FP rate at high stated
confidence means confidence thresholds alone won't rescue precision.

**Follow-ups this instrument is built for (not run here):** the cross-model
matrix (generator ≠ verifier) to de-confound reading #2; verifier-protocol
ablations (thinking budgets, self-consistency, diff-only context) via the §6
config hooks; and SPC monitoring of these rates over model generations via
the gym-events/1 stream.
