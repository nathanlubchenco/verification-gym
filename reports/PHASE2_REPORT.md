# PHASE 2 REPORT — MUT Arm at Full Sample Size

Date: 2026-07-03 · Cumulative spend: **$6.30** (MUT generation is API-free)

## What was built / run

- `gym/arms/mut.py`: five deterministic, seeded operators (MUT-01..05 per §5)
  injected into carrier commits (D6). Guards per site: unique full-line anchor,
  mutated file still parses, **AST must differ** (rejects comment edits), and a
  tokenize pass rejects edits landing inside string literals (both guards were
  added after tests exposed the "equivalent mutant" trap — a mutation inside a
  string compiles fine, changes the AST constant, and would have been a
  semantic no-op labeled defective).
- One defect per carrier; neediest-class-first assignment across 337 carriers.

## Results

| class | items | vs target 50 | vs floor 30 |
|---|---|---|---|
| MUT-01 boundary/off-by-one | 50 | full | ok |
| MUT-02 logic operator swap | 50 | full | ok |
| MUT-03 same-type arg swap | 50 | full | ok |
| MUT-04 error-handling swallow | 45 | short (site scarcity: `raise` directly under `except` is rare in touched files) | ok |
| MUT-05 default/config change | 47 | short (def-signature defaults scarce) | ok |

242 MUT items total; **no class below floor — no LOW-POWER flags needed for MUT.**
Leakcheck green over all 796 payloads (CLEAN 433 + CANARY 24 + MUT 242 + SZZ so far).

## Notes

- MUT-03 "same-type variable/argument swap" is approximated textually
  (two bare-name call arguments swapped); actual type-sameness is not verified.
  Recorded for LIMITATIONS.md.
- SZZ mining (Phase 4) was started in parallel and is populating; GEN (Phase 3)
  runs next with per-class process parallelism.

## Exit criteria (§10 Phase 2: MUT at full sample size)

- [x] All five MUT classes populated; 3 of 5 at full n=50, all ≥ floor 30
- [x] Leakcheck green

**GO for Phase 3.**
