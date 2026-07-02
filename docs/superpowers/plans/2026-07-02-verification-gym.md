# Verification Gym v0 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task (inline execution per DECISIONS D11). Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the `gym` CLI harness per HANDOFF.md — measure LLM verifier defect-detection across CLEAN/MUT/GEN/SZZ arms with pre-specified metrics, deterministic cached re-runs, and a complete audit trail.

**Architecture:** A single Python package `gym/` driven by `config.yaml` + env vars. SQLite holds defect records, review items, verdicts, an LLM call cache keyed `(model, prompt_hash, seed)`, and a spend ledger with a hard cap. Review payloads (what the verifier sees) live as flat files fully separated from ground truth. Injected defects (MUT/GEN) ride inside real historical "carrier" commits so defective and clean items share a superficial distribution (D6). Scoring emits a versioned JSONL event stream (`gym-events/1`).

**Tech Stack:** Python ≥3.11 via uv; `anthropic` SDK; `pyyaml`; `pydriller` (Phase 4); `numpy` + `matplotlib` (scoring/report); `pytest` for self-tests. No web UI, no plugins.

## Global Constraints (verbatim from HANDOFF.md)

- Metrics, arms, thresholds, exit criteria are fixed; infeasibility → Fallback Hierarchy §11, never redefinition.
- Leakcheck: "Zero tolerance; hard fail."
- Verifier prompt template is fixed (Appendix A), one pass per item, blind randomized order.
- Cache every model call keyed by `(model, prompt_hash, seed)`; `gym reproduce` regenerates REPORT.md byte-comparable (modulo timestamps) from cache only.
- Hard-stop all API calls at cumulative spend ≥ `GYM_SPEND_CAP_USD`; persist partial state cleanly.
- Target n=50 defective/class (floor 30, LOW-POWER flag below floor, never drop); ~40% CLEAN.
- Event schema `gym-events/1` (Appendix B) is a public API.
- Never drop GEN-03. No secrets in repo. `gym smoke` <15 min.

---

## File Structure

```
verification-gym/
  pyproject.toml, uv.lock, config.yaml, .gitignore
  gym/
    __init__.py
    cli.py            # argparse: repos generate leakcheck review score report smoke reproduce
    config.py         # Config dataclass; yaml + env override (GYM_*)
    db.py             # sqlite schema + helpers (data/gym.db)
    ids.py            # opaque id generation (leak-safe: no arm/class in ids)
    llm.py            # Anthropic client: cache, spend ledger, hard cap, pricing
    gitrepo.py        # clone/pin/log/diff/show plumbing (subprocess git)
    repos.py          # gym repos: validate candidates (pytest, license, LOC, history)
    mine.py           # mainline-commit mining + clean filters (D5, D13) + carrier pool
    payload.py        # build review payload files + Appendix A prompt rendering
    inject.py         # apply a defect diff onto a carrier commit's post-state
    arms/
      __init__.py
      clean.py        # Arm 0
      mut.py          # Arm 1: MUT-01..05 seeded operators
      gen.py          # Arm 3 phase: GEN-01..06 via generator model + test rejection
      szz.py          # Arm 4 phase: pydriller SZZ (+ bugsinpy fallback)
      canary.py       # §14 canary defects
    leakcheck.py      # zero-tolerance payload scan
    review.py         # blind randomized verifier loop, JSON parse + one re-ask
    score.py          # outcomes, Wilson, bootstrap, AUROC, Brier, events JSONL
    report.py         # REPORT.md + matplotlib PNGs
  tests/              # pytest self-tests per module
  data/               # gitignored: repos/, payloads/, gym.db
  events/             # run_<id>.jsonl (committed)
  audit/szz_sample/
  reports/
```

## Core interfaces (used by every later task)

```python
# config.py
@dataclass
class Config:
    seed: int; generator_model: str; verifier_model: str; spend_cap_usd: float
    data_dir: Path; events_dir: Path; reports_dir: Path
    repos: list[RepoSpec]          # name, url, pin
    n_per_class: int; floor_per_class: int; clean_fraction: float
    payload_budget_chars: int      # A7: oversized items excluded, not truncated
    pricing: dict[str, ModelPrice] # input/output USD per MTok
def load_config(path="config.yaml") -> Config  # env GYM_* overrides

# llm.py
class SpendCapExceeded(RuntimeError): ...
@dataclass
class LLMResult:
    text: str; tokens_in: int; tokens_out: int; latency_ms: int
    cost_usd: float; prompt_hash: str; from_cache: bool
def call_model(cfg, db, *, model: str, system: str | None, prompt: str,
               max_tokens: int, purpose: str) -> LLMResult
# 1) prompt_hash = sha256(canonical json of request)  2) cache hit -> return
# 3) cap check: ledger_total + est > cap -> SpendCapExceeded  4) call, ledger, cache

# db.py tables
# repos(name PK, url, commit, loc, license, validated_at, notes)
# commit_pool(repo, sha, subject, body, files_json, assigned_to)  -- mined candidates
# defect_records(defect_id PK, arm, class, repo, injection_method, carrier_sha,
#                ground_truth_diff, ground_truth_locations, provenance, created_at)
# review_items(item_id PK, defect_id NULL, repo, payload_path, defective, created_at)
# verdicts(item_id, run_id, raw, verdict_json, outcome_inputs..., prompt_hash, ts)
# llm_cache(cache_key PK, model, prompt_hash, seed, response_text, tokens_in,
#           tokens_out, latency_ms, cost_usd, created_at)
# spend_ledger(id, ts, model, purpose, tokens_in, tokens_out, cost_usd)

# payload.py — payload file contains ONLY: description, unified diff, post-change
# contents of touched files. item_id is opaque (ids.py: "it-" + hex from seeded RNG).
def build_payload(...) -> PayloadPaths
def render_prompt(payload) -> str   # Appendix A verbatim

# score.py
def wilson_ci(k: int, n: int, z: float = 1.96) -> tuple[float, float]
def outcome_for(item, verdict) -> str  # detected|missed|misdirected_flag|
                                       # false_positive|true_negative|abstained
def emit_events(run_id, ...) -> Path   # gym-events/1 JSONL
```

---

## Phase 0 tasks (detailed)

### Task 0.1: Project skeleton + config
- [ ] `uv init` layout: pyproject (requires-python >=3.11; deps anthropic, pyyaml, numpy, matplotlib, pytest; pydriller deferred to Phase 4), .gitignore (data/, .venv), package dirs.
- [ ] Write `config.yaml` with defaults from DECISIONS D2–D4 and candidate repo list.
- [ ] `gym/config.py` + `tests/test_config.py`: yaml load, env override precedence (GYM_SEED etc.), missing-file error. TDD: test first, fail, implement, pass, commit.

### Task 0.2: Repo validation (`gym repos`)
- [ ] `gym/gitrepo.py`: `clone(url, dest)`, `checkout(sha)`, `head_sha()`, `log(...)`, `show(...)`, `diff(...)` via subprocess with `-c core.pager=cat`; unit tests against a tiny fixture repo created in tmp_path.
- [ ] `gym/repos.py`: for each candidate — clone to `data/repos/<name>`, pin HEAD sha into db+config snapshot, LOC count (`*.py` non-test lines, 5k–100k band), license file check (MIT/BSD/Apache), history ≥3 years (first commit date), `uv run --with . pytest` in an isolated venv with 5-min timeout → green (failures→reject, skips ok per A8).
- [ ] `gym/cli.py` skeleton with `repos` subcommand; run it for real; record pass/fail per candidate in WORKLOG + db. Substitutions logged.

### Task 0.3: Spend forecast + PHASE0_REPORT.md
- [ ] Measure real payload sizes: sample ~30 mined commits from validated repos, build draft payloads, count chars→tokens (chars/3.6 heuristic cross-checked with `count_tokens` on 3 samples).
- [ ] Forecast = review calls (items × tokens × verifier price) + GEN generation (attempts × price with assumed 50% rejection) + SZZ labeling + canaries/smoke + 15% margin. Write arithmetic into PHASE0_REPORT.md.
- [ ] If forecast > cap: apply §9 scale-down arithmetic (shed repos before classes, never below floor), log in DECISIONS.
- [ ] PHASE0_REPORT.md: built/decisions/exit-checklist/spend/go-no-go. Commit.

## Phase 1 tasks (detailed)

### Task 1.1: db + ids + llm client
- [ ] `gym/db.py` schema init + CRUD helpers; tests: round-trip each table, idempotent init.
- [ ] `gym/ids.py`: seeded opaque ids; test: no substring from {arm names, class labels, "canary", "defect"}.
- [ ] `gym/llm.py`: tests with a fake transport — cache hit returns identical result & no spend; cap exceeded raises before call; ledger accumulates; pricing math exact. Real client uses `anthropic.Anthropic()`, non-streaming `messages.create`, `max_tokens` per purpose.

### Task 1.2: Commit mining (`gym/mine.py`)
- [ ] Mine mainline commits older than 6 months (window observable) excluding merges of merges, docs-only, >N files, >budget size; parse fix-keyword regex; revert detection; later-fix line-overlap filter (D13). Tests on fixture repo with a planted "clean" and a "later-fixed" commit.
- [ ] Partition pool per repo with seeded RNG into disjoint sets: CLEAN items, MUT carriers, GEN carriers (SZZ independent). Persist to `commit_pool.assigned_to`.

### Task 1.3: Payload builder + leakcheck
- [ ] `gym/payload.py`: reconstruct commit diff + post-state touched files from git; payload = description(commit subject+body, sanitized of issue URLs? -> keep verbatim, log), diff, files. Enforce char budget (A7: exclude oversized). Tests: fixture commit → exact expected payload; oversized exclusion.
- [ ] `gym/leakcheck.py`: scan all payload files for: defect_id/item_id patterns beyond the item's own id? (ids never appear in payloads at all — assert), tokens `MUT-0`, `GEN-0`, `SZZ`, `CLEAN` (word-bounded uppercase), "canary", "injected defect", "mutation operator", "ground truth", and any db defect_id string. Hard fail exit≠0 on any hit. Tests: clean payload passes; each contaminant class caught.

### Task 1.4: CLEAN arm + canaries
- [ ] `gym/arms/clean.py`: turn assigned CLEAN commits into review_items (defective=False). Test: counts, no defect_record rows.
- [ ] `gym/inject.py`: apply defect edit to carrier post-state, produce combined unified diff + GT locations (post-change coords, ±2 context per D9). Tests: line-accurate GT on fixture.
- [ ] `gym/arms/canary.py`: ≥20 blatant defects (inverted condition, `return None` swap, deleted null-check, `==`→`=` adjacent-syntax, off-by-1000 constant...) injected via inject.py into carriers, defect_records arm='MUT' class='CANARY'? — NO: canaries get arm tag 'CANARY' internally, excluded from §7 metrics, used only for §14 gate. Log decision inline.

### Task 1.5: Review loop + scoring + events
- [ ] `gym/review.py`: load review_items for run, shuffle with run-seed RNG, render Appendix A prompt, `call_model`, strict JSON parse (`json.loads`, schema check), one re-ask with format reminder, else abstention verdict. Persist verdicts. Tests with fake LLM: happy path, malformed→re-ask→ok, malformed×2→abstained, SpendCapExceeded → clean partial persist.
- [ ] `gym/score.py`: outcome_for per §3/D9 (incl. misdirected_flag), wilson_ci (tested against known values: k=8,n=10 → (0.490,0.943) etc.), per-class tables, FP rate, AUROC (rank-based, ties=0.5), Brier + reliability bins, bootstrap arm-gap (seeded), events JSONL with schema field. Tests: hand-computed miniature dataset.
- [ ] `gym/report.py`: REPORT.md sections incl. MEASURED vs INFERRED; PNGs: per-class detection w/ CIs, FP, calibration, arm comparison, cost/review. Deterministic output ordering (sorted keys) for reproduce.

### Task 1.6: smoke + null test + PHASE1_REPORT
- [ ] `gym smoke`: 1 repo, n=2/class available arms + canaries + clean, end-to-end incl. leakcheck, score, report to a scratch dir; assert <15 min.
- [ ] Canary gate run: canary detection ≥90% required. Null test: CLEAN-only mini-run.
- [ ] PHASE1_REPORT.md + commit.

## Phases 2–5 (planned in detail at phase start per D10)

- **Phase 2 (MUT):** seeded AST-guided operators MUT-01..05 over carrier post-states; equivalence guard (mutated code must differ semantically — compile + quick heuristic); populate to scaled n; leakcheck; PHASE2_REPORT.
- **Phase 3 (GEN):** generator prompt per §5 (plausible, style-consistent, survives hurried review, passes tests where feasible); parse proposed edit; inject; run repo test suite (timeout); reject caught defects, record per-class rejection rate; GEN-03 targets test files (weakening) — note test-suite-rejection interplay: test-weakening runs suite too (must pass by construction); PHASE3_REPORT.
- **Phase 4 (SZZ):** pydriller; fix-commit id via issue links+keywords; blame to introducers; filters: (a) exclude whitespace/comment/rename-only lines, (b) exclude fix commits touching >K files, (c) recency/window guards; reconstruct introducer diff as review item; LLM-assisted post-hoc class labels with stored rationale; 20-sample dump to audit/szz_sample/; <30 usable → F3 BugsInPy.
- **Phase 5:** full generate→leakcheck→review→score→report; §14 self-audit incl. `gym reproduce` byte-compare (normalize timestamps); LIMITATIONS.md; score §15 (blank — note in report per A4).

## Self-review notes
- Spec coverage: all §4 subcommands mapped (repos 0.2, generate 1.4/2/3/4, leakcheck 1.3, review 1.5, score 1.5, report 1.5, smoke 1.6, reproduce Phase 5).
- Canary arm exclusion from §7 metrics is an interpretation → recorded in DECISIONS when implemented.
- Type consistency: all tasks consume `Config`/`call_model`/`build_payload` signatures defined above.
