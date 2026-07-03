# PHASE 5 REPORT — Full Run, Report, Self-Audit

Date: 2026-07-03 · **Final cumulative spend: $77.99** (cap $125; forecast $120)

## The run

All 1,114 review items reviewed blind under run_id `main` with
`claude-opus-4-8` as both generator and verifier (D2), seed 20260702:

| arm | items | detection rate [95% Wilson] |
|---|---|---|
| CLEAN (negative controls) | 433 | FP rate **19.9%** [16.4, 23.9] |
| MUT (seeded mutations) | 242 | **89.3%** [84.7, 92.6] |
| GEN (model-written subtle defects) | 265 | **58.9%** [52.9, 64.6] |
| SZZ (real historical defects) | 150 | **26.7%** [20.2, 34.3] |
| CANARY (pipeline gate, excluded from metrics) | 24 | 100% |

Arm gap (§7.3, matched classes with n≥15 both arms, bootstrap 95% CI):
GEN-01 **+42.1pp** [+24.9, +59.7]; GEN-02 **+48.2pp** [+26.8, +67.5].
Hardest class overall: SZZ-labeled GEN-02 (12%); hardest injected class:
**GEN-03 test-weakening at 24%** — the operator's priority class.
Abstentions: 0 across 1,114 (76 re-asks resolved all malformed JSON).
Full tables, secondaries (AUROC, Brier 0.136, localization precision 0.848,
misdirected 13.8%), and charts: `reports/REPORT.md`. Interpretation:
REPORT.md § INFERRED. Event stream: `events/run_main.jsonl` (gym-events/1).

## §14 self-audit

1. **Canary suite:** 24 canaries, detection **100%** (gate ≥90%). ✅
   (First attempt failed at 87.5% — pipeline bug, fixed; see PHASE1_REPORT.)
2. **Null test:** CLEAN-only mini-run done in Phase 1; FP machinery sane. ✅
3. **Leak test:** `gym leakcheck` green over all 1,114 payloads in the final run. ✅
4. **Determinism:** `gym reproduce` regenerates REPORT.md **byte-comparable**
   modulo the timestamp line, from cache/db only, zero API spend. ✅
5. **Smoke:** `gym smoke` green in **48s** (<15 min) with the final code. ✅
6. **LIMITATIONS.md:** 17 adversarial entries including the pre-registered
   same-model-bias entry (§14.6 verbatim requirement). ✅

## Deviations and incidents (all logged as they happened)

- Canary operator fix (Phase 1, F1) — WORKLOG 2026-07-03, PHASE1_REPORT.
- GEN suite-gate runner bugs + retro-gate (Phase 3, F1) — PHASE3_REPORT.
- D17: main review moved to Batch API when mid-run telemetry projected $147 >
  cap; final spend $77.99.
- Account credit exhaustion mid-GEN-top-up: GEN stopped at 265/300 (all ≥
  floor; GEN-03 full). Synchronous calls later recovered; batches were never
  rejected. No metric, threshold, or definition was adjusted at any point.
- §15 pre-registration was blank at run start (A4): predictions cannot be
  scored. The §7 outputs it would have been scored against are all in REPORT.md.

## Exit criteria (§10 Phase 5)

- [x] Pre-specified analysis (§7) executed in full — nothing extended, nothing trimmed
- [x] REPORT.md generated with MEASURED vs INFERRED separation
- [x] Self-audit (§14) all green
- [x] LIMITATIONS.md written adversarially

**Run complete.** The instrument is reusable: set `GYM_GENERATOR_MODEL` /
`GYM_VERIFIER_MODEL` and re-run `generate --arms gen` + `review` + `score`
for the cross-model matrix the LIMITATIONS entry calls for.
