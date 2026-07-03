# PHASE 1 REPORT — Harness Spine

Date: 2026-07-03 · Cumulative spend: **$6.12** (smoke $0.77 mirrored + gate reviews)

## What was built

- `gym/inject.py` — defect injection into carrier commits via temp git worktrees, so
  defective diffs are byte-format-identical to clean ones (D6; no shape leak).
- `gym/arms/clean.py` semantics inside `gym/generate.py` — 433 CLEAN items live.
- `gym/arms/canary.py` — canary generation (24 items live).
- `gym/leakcheck.py` + `gym leakcheck` — zero-tolerance scan (labels, phrases, id
  shapes, every actual db id). Green over all 457 payloads.
- `gym/review.py` + `gym review` — blind seeded order, verbatim Appendix A prompt,
  strict JSON parse → one re-ask → abstention; resumable; clean cap abort.
- `gym/score.py` + `gym score` — all §7 metrics (Wilson CIs, arm gap bootstrap,
  AUROC/Brier per D15, localization/misdirected split) + `gym-events/1` stream.
- `gym/report.py` + `gym report` — deterministic REPORT.md + 4 charts.
- `gym smoke` — isolated end-to-end sandbox run; `gym reproduce` — byte-compare.
- MUT arm module landed early (Phase 2 ready); GEN and SZZ modules written and
  unit-tested (Phases 3–4 ready).

## Dead end worth recording (§14.1 gate failure and fix)

First canary review scored **21/24 = 87.5% — below the 90% gate**. Per §14.1 the
pipeline was presumed broken, and it was: two of my four canary operators
(`eq_to_neq`, `big_constant`) are MUT-grade subtlety, not "blatant", and both
misses had landed in **test files** where a flipped assertion reads as noise.
The third miss was semantically detected but localized 6 lines away (the fixed
D9 rule correctly scores that as `misdirected_flag`). Fix (F1): canary ops
restricted to `invert_if` + `return_none`, test/example files excluded as
canary targets; canaries purged and regenerated (payloads re-leakchecked).
Re-review: **24/24 = 100% PASS**. Metric definitions were not touched.

## Exit criteria checklist (§10 Phase 1)

- [x] `gym smoke` passes end-to-end in 52s (<15 min), leakcheck clean, report+events written
- [x] Canary detection ≥90%: **100% (24/24)**
- [x] Leakcheck green over every payload (457)
- [x] Null test: 30 CLEAN-only reviews scored sanely — FP 6/30 (20.0%), outcomes
      and Wilson CIs produced. (The FP level itself is a Phase 5 result; n=30 here.)

## Notes for the operator

- The verifier flags ~20% of presumed-clean historical commits on this small
  sample. Whether that is verifier over-triggering or residual true defects in
  "presumed clean" commits is undecidable from inside the harness — carried to
  LIMITATIONS.md.
- Review spend so far is reusable: gate verdicts were made under run_id `main`,
  the same run the full Phase 5 review resumes.

**GO for Phase 2 (MUT at full n).**
