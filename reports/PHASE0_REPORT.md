# PHASE 0 REPORT — Recon & Plan

Date: 2026-07-02 · Spend so far: **$0.00** (only the free `count_tokens` endpoint was called)

## What was built

- Project skeleton: uv + pyproject (Python ≥3.11), `gym` CLI entry point, pytest self-tests (all green).
- `gym/config.py` — config.yaml + `GYM_*` env overrides (defaults per DECISIONS D2–D4).
- `gym/gitrepo.py` — git plumbing (by-sha reads; corrupt-timezone tolerant).
- `gym/db.py` — SQLite schema: repos, commit_pool, defect_records, review_items, verdicts, llm_cache, spend_ledger.
- `gym/repos.py` + `gym repos` — full §8 validation (license incl. SPDX/clause-text detection, LOC band, ≥3y history, pytest in isolated py3.12 venv, 5-min timeout).
- `gym/llm.py` — model client with mandatory `(model, prompt_hash, seed)` cache, spend ledger, hard cap (tested with fake transport; cap blocks before any API call).
- `gym/ids.py` — leak-safe opaque ids.
- `gym/difftools.py`, `gym/mine.py` — diff hunk parsing; CLEAN-pool mining with §5 filters (age ≥1y, no revert, later-fix line-overlap rejection per D13).
- `gym/payload.py` — payload builder + **verbatim Appendix A prompt**.
- Implementation plan: `docs/superpowers/plans/2026-07-02-verification-gym.md`.

## Repo validation results (§8)

| repo | verdict | LOC | license | history | tests |
|---|---|---|---|---|---|
| click | **PASS** | 9,871 | BSD | 12.2y | 1676 passed, 2.4s |
| jinja2 | **PASS** | 11,670 | BSD | 19.3y | 911 passed, 1.1s |
| attrs | **PASS** | 5,567 | MIT | 11.4y | 1382 passed, 5.7s |
| requests | **PASS** | 5,192 | APACHE | 15.4y | 619 passed, 73s |
| tenacity | fail | 1,827 | APACHE | — | LOC below 5k band |
| flask | fail | 7,560 | BSD | — | suite red in py3.12 venv (pytest-internals import error from pinned test deps) |
| rich | fail | 35,576 | MIT | — | suite red (parametrize error under fresh venv) |
| httpx | fail | 7,448 | BSD | — | suite hangs waiting on connections (server-dependent tests) |

**4 repos validated** (within the 3–5 selection band). Substitutions/failures logged per §8; commits will be pinned at generate time (validated HEADs recorded in db).

## Spend forecast (§9 Phase 0 duty)

Measured on 40 real mined commits across the 4 validated repos (seed 20260702):
mean in-budget payload = **22,556 chars**; calibrated **2.68 chars/token** via
`count_tokens` (3 samples) → **≈8,400 input tokens per review**. 5/40 (12.5%)
of commits exceeded the 110k-char payload budget and are excluded at sampling
time (A7). Prices: claude-opus-4-8 $5/MTok in, $25/MTok out (cached 2026-07-02).

| Component | Arithmetic | USD |
|---|---|---|
| Reviews (~1,000 calls: 550 defective + ~367 clean + canaries/smoke/null) | 1000 × (8,400×$5 + 400×$25)/1e6 | **$52** |
| GEN generation (300 accepted, assumed 50% rejection → 600 attempts) | 600 × (9,000×$5 + 1,200×$25)/1e6 | **$45** |
| SZZ post-hoc labeling (~150 calls) | 150 × (6,000×$5 + 300×$25)/1e6 | **$6** |
| Malformed-JSON re-asks (~3%) | | **$2** |
| Subtotal | | **$105** |
| +15% margin | | **≈$120** |

**Forecast $120 ≤ cap $125** (default cap; see DECISIONS D3 — `GYM_SPEND_CAP_USD`
overrides). No scale-down required at full n=50/class. Largest uncertainty:
GEN rejection rate — if it exceeds ~65%, apply F2 (reduce n toward floor 30,
shed repos first) and log the arithmetic.

> **Operator note:** `GYM_SPEND_CAP_USD` was not set at run start; the $125
> default was chosen by the agent (D3) to make the operator-designed n=50
> experiment feasible while capping runaway. Set the env var to override.

## Decisions made this phase

D1–D13 in DECISIONS.md; gap-filling assumptions A1–A8 in ASSUMPTIONS.md.
Notable: §15 pre-registration was found blank with no pre-run commit (A4).

## Exit criteria checklist

- [x] ≥3 repos validated (4: click, jinja2, attrs, requests)
- [x] Spend forecast written before any full-scale run; forecast under cap
- [x] Skeleton layout in place; self-tests green (26 tests)

**GO for Phase 1.**
