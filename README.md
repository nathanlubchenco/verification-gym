# verification-gym

A reusable, model-agnostic harness that measures how well an LLM verifier
(code reviewer) detects defects in code changes, broken down by defect class,
with honest statistics. Built to the specification in [HANDOFF.md](HANDOFF.md);
every non-trivial choice is logged in [DECISIONS.md](DECISIONS.md) /
[ASSUMPTIONS.md](ASSUMPTIONS.md) / [WORKLOG.md](WORKLOG.md).

## Install

Requires `git` and [uv](https://docs.astral.sh/uv/) (Python ≥3.11 is managed
automatically):

```sh
uv sync
uv run pytest -q          # harness self-tests
```

## Configuration

`config.yaml` holds all defaults. Environment variables override:

| env var | meaning | default |
|---|---|---|
| `ANTHROPIC_API_KEY` | API credentials (required for review/generate) | — |
| `GYM_GENERATOR_MODEL` | model that writes GEN-arm defects | `claude-opus-4-8` |
| `GYM_VERIFIER_MODEL` | model under measurement | `claude-opus-4-8` |
| `GYM_SPEND_CAP_USD` | hard stop for cumulative API spend | `125` |
| `GYM_SEED` | run seed (ordering, sampling, cache key) | `20260702` |

Every model call is cached in SQLite keyed by `(model, prompt_hash, seed)`;
re-runs are free and deterministic.

## Quickstart

```sh
uv run gym repos              # clone, pin, validate target repos (§8 criteria)
uv run gym smoke              # end-to-end mini run in an isolated sandbox (<15 min)

uv run gym generate           # build review items for all available arms
uv run gym leakcheck          # zero-tolerance contamination scan (hard fail)
uv run gym review             # run the verifier, blind + randomized (resumable)
uv run gym score              # §7 metrics + events/run_<id>.jsonl (gym-events/1)
uv run gym report             # reports/REPORT.md + charts
uv run gym reproduce          # regenerate REPORT.md from cache; byte-compare
```

## Layout

```
gym/                 source (config, git plumbing, mining, injection, arms/,
                     leakcheck, review, score, report, cli)
tests/               harness self-tests (no API calls)
data/                gitignored: repo clones, payloads, sqlite, venvs, smoke sandbox
events/run_<id>.jsonl  public event stream (schema gym-events/1, Appendix B)
audit/szz_sample/    20 SZZ items with full provenance for manual precision audit
reports/             REPORT.md, PHASE*_REPORT.md, LIMITATIONS.md, charts/
```

## Design invariants

- **Blindness:** the verifier sees only `{description, diff, post-change files}`
  rendered through the fixed Appendix A prompt. Ground truth lives only in
  SQLite; `gym leakcheck` hard-fails on any contamination.
- **No shape leak:** injected defects (MUT/GEN/canary) ride inside real
  historical "carrier" commits produced by git itself, drawn from the same
  mined pool as CLEAN items.
- **Pre-specified metrics:** §7 only — per-class detection with Wilson CIs,
  CLEAN FP rate, GEN−SZZ arm gap with bootstrap CIs, AUROC/Brier/localization/
  cost secondaries. Classes below the n=30 floor are flagged LOW-POWER, never
  dropped.
- **Spend cap:** all API calls stop hard at `GYM_SPEND_CAP_USD`; partial state
  persists and every command resumes.
