# WORKLOG (append-only, timestamped)

## 2026-07-02

- **17:30** Run start. Read HANDOFF.md in full. Committed it unmodified as the first commit (`a10a6e7`) to pin the spec.
- **17:30** Environment recon: macOS (Darwin 24.3.0), 8 cores, 24 GB RAM, ample disk. Python 3.14.0 system, `uv 0.11.2` available. `ANTHROPIC_API_KEY` present. `GYM_GENERATOR_MODEL`, `GYM_VERIFIER_MODEL`, `GYM_SPEND_CAP_USD`, `GYM_SEED` **not set** — see ASSUMPTIONS A1–A3 and DECISIONS D2.
- **17:30** Discrepancy found: §15 pre-registration says "Committed to git before the run" but the repo had zero commits and all §15 blanks are empty. Not modifying §15 per rule 5. Logged as ASSUMPTION A4.
- **17:31** Created audit trail files (DECISIONS.md, ASSUMPTIONS.md, WORKLOG.md). Beginning Phase 0: repo selection/validation, spend forecast, skeleton layout, implementation plan.

- **17:55** Task 0.1–0.2 done: skeleton, config, git plumbing, db schema, repo validation. Three validation rounds needed — dead ends: (1) license detector missed BSD/SPDX (Pallets license bodies never say "BSD"); (2) `uv venv` failed on existing dirs (needed --clear); (3) system py3.14 broke older pinned test plugins (pinned venvs to 3.12); (4) my unpinned pytest overrode repo-pinned test deps. Result: click, jinja2, attrs, requests PASS; tenacity (LOC 1827 < 5k), flask/rich/httpx (red suites) rejected — logged substitutions per §8.
- **18:05** LLM client (cache/cap/ledger), ids, difftools, mine.py (CLEAN filters D13), payload.py (Appendix A verbatim) built test-first; 26 tests green. Dead end: requests repo has a commit with corrupt timezone `+518:00` — added parse_git_date fallback.
- **18:10** Phase 0 forecast from 40 real payloads: mean 8.4k tokens/review (2.68 chars/token measured via free count_tokens); forecast ≈$120 < $125 cap. PHASE0_REPORT.md written. Spend: $0.00. GO Phase 1.

## 2026-07-03

- **Phase 1 complete.** Review/score/leakcheck/report/smoke/reproduce all wired; smoke green 52s, $0.77. Full CLEAN (433) + canary (24) generation from mined pool (846 commits, 4 repos).
- **Dead end (important):** first §14.1 canary gate FAILED at 21/24 (87.5%). Diagnosis: eq_to_neq and big_constant canary ops are MUT-grade subtle, and two misses landed in test files; a third was found-but-mislocalized (D9 rule working as designed). Fix: canary ops restricted to invert_if/return_none, test/example files excluded; purge + regenerate + re-review → 24/24 PASS. Metric definitions untouched (rule 2).
- Null test: 6/30 clean items flagged (20% FP on this sample) — machinery sane; the level itself is a Phase 5 result.
- SZZ + GEN arm modules written and unit-tested ahead of their phases. Spend: $6.12.

- **Phase 2 (MUT) complete:** 242 items (50/50/50/45/47) — all classes ≥ floor, no LOW-POWER flags. Two guard bugs caught by tests along the way: AST-equality alone misses string-literal mutations (added tokenize span check); equivalent-mutant trap documented. Leakcheck green over 796 payloads.
- **Phase 4 (SZZ) started in parallel** (pydriller reads only, safe next to MUT worktrees): precision filters P1-P3, LLM post-hoc labels; 91 items at last check, target 150.
- **Phase 3 (GEN) launched:** 6 per-class processes, no carrier reuse within class (cross-class reuse allowed — clustering noted for LIMITATIONS), suite-rejection gate against carrier baselines in per-repo venvs (worktree shadowing site-packages via PYTHONPATH). Attempt budget 120/class keeps worst-case spend in forecast.
