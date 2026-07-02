# HANDOFF: Verification Gym v0 — Autonomous Build Specification

**Audience:** You are an autonomous coding agent (Claude Code). This document is your complete brief. You will receive no clarifications, no answers to questions, and no mid-run feedback. Everything you need to decide is either specified here or delegated to you explicitly under §2 (Priority Stack) and §11 (Fallback Hierarchy).

**Operator:** Nathan. He will audit your work after the run ends, using your logs. He will not respond during the run.

---

## 0. Operating Rules (read before anything else)

1. **Do not ask questions.** When the spec is ambiguous, resolve the ambiguity using the Priority Stack (§2), record the decision in `DECISIONS.md` (§12), and proceed.
2. **Do not silently redefine anything.** Metrics, arms, thresholds, and exit criteria in this document are fixed. If one becomes infeasible, execute the Fallback Hierarchy (§11) and log it. Never adjust a definition to make a result achievable.
3. **Known-answer validation only.** "The output looks reasonable" is not validation anywhere in this project. Every pipeline stage must be validated against inputs with known correct outputs (canaries, §14).
4. **Everything is audited later.** Optimize for a human being able to reconstruct, verify, and re-run every claim you make. A correct result that cannot be audited is a failed result.
5. **Do not modify §15 (Pre-Registration).** It was completed by the operator before you started.

---

## 1. Mission

Build a **verification gym**: a reusable, model-agnostic harness that measures how well an LLM verifier (code reviewer) detects defects in code changes, broken down by defect class, with honest statistics.

The scientific question this instrument serves: **is verification easier than generation for frontier models?** — i.e., can a model reliably catch defects of the kinds models (and humans) produce? The gym does not answer this in one run; it makes the question *measurable, repeatable, and comparable across models over time*.

Design consequence #1: the harness must outlive the model building it. **Generator model and verifier model are independent configuration parameters** (env vars, §9), even if both are the same model during this run. Nothing in the codebase may assume a specific model.

Design consequence #2: the gym's output feeds a downstream statistical-process-control (SPC) monitor that charts defect-detection rates over time using EWMA/CUSUM. You are not building that monitor. You **are** building the event stream it will consume (§13, Appendix B). Treat the event schema as a public API.

---

## 2. Priority Stack

When any two goals conflict, the higher item wins. Log the conflict and the resolution.

1. **Measurement correctness** — no ground-truth leakage, no biased sampling, no metric drift.
2. **Auditability & reproducibility** — deterministic re-runs from cached model calls; complete logs.
3. **Cross-model reusability** — clean model abstraction; config-driven.
4. **Statistical power** — hit per-class sample targets (§9).
5. **Taxonomy breadth** — cover all defect classes (§5).
6. **Performance & polish** — last. No UI. Speed only matters if it blocks 1–5.

---

## 3. Core Definitions

- **Review item:** one unit of verifier work — a code diff plus context, presented blind. Either defective (exactly one injected/known defect) or clean.
- **Defect record:** `{defect_id, arm, class, repo, injection_method, ground_truth_diff, ground_truth_locations, provenance}`. Ground truth is stored **outside** anything the verifier can see.
- **Arm:** a source of review items. Four arms: CLEAN, MUT, GEN, SZZ (§5).
- **Verdict:** the verifier's structured output for one review item (schema in §6).
- **Detection:** verdict has `defect_found = true` AND `class_guess` is any value AND at least one reported location overlaps the ground-truth hunk(s). Flagging *something* in the wrong place is a false alarm on a defective item — score it as a miss, and log it separately as `misdirected_flag`.
- **False positive:** `defect_found = true` on a CLEAN item.

---

## 4. Functional Requirements (pipeline stages)

Build a CLI tool (`gym`) with these subcommands, all config-driven (single `config.yaml` + env vars):

1. `gym repos` — clone, pin (commit hash), and validate target repos (§8): test suite passes, license check, size check.
2. `gym generate` — produce review items for all arms per the sampling plan (§9). Persist defect records to SQLite; persist review payloads (what the verifier will see) separately.
3. `gym leakcheck` — scan every review payload for ground-truth contamination: defect IDs, arm names, class labels, injection markers, tell-tale comments. **Zero tolerance; hard fail.**
4. `gym review` — run the verifier over review items. Blind, randomized order, one item per call. Cache every model call keyed by `(model, prompt_hash, seed)` so re-runs are free and deterministic.
5. `gym score` — compute all metrics in §7 from verdicts + ground truth. Emit the event stream (Appendix B).
6. `gym report` — generate `REPORT.md` + charts (matplotlib, static PNG): per-class detection with CIs, FP rate, calibration plot, arm comparison, cost per review.
7. `gym smoke` — end-to-end run: 1 repo, n=2 per class, completes in <15 minutes.
8. `gym reproduce` — regenerate `REPORT.md` byte-comparable from cached calls only (no new API spend).

Storage: SQLite for records/verdicts, JSONL for the event stream, flat files for payloads. Python 3.11+, `uv` or pinned `requirements.txt`.

---

## 5. Defect Taxonomy and Arms

### Arm 0 — CLEAN (negative controls)
Real merged PRs from repo history presumed clean: no revert, and no later bug-fix commit touching the same lines within 6 months of merge (use old history so the window is observable). Target mix: **~40% of all review items are clean.** The verifier must never be able to infer defect base rate from ordering or metadata.

### Arm 1 — MUT (deterministic mutation operators; seeded)
| Class | Description |
|---|---|
| MUT-01 | Boundary / off-by-one (`<` ↔ `<=`, ±1 in indices/ranges) |
| MUT-02 | Logic operator swap (`and`↔`or`, `==`↔`!=`, dropped negation) |
| MUT-03 | Same-type variable/argument swap |
| MUT-04 | Error-handling removal or swallow (except-pass, retry removal) |
| MUT-05 | Default/config value change (timeouts, limits, flags) |

### Arm 2 — GEN (LLM-generated subtle defects; generator model = `GYM_GENERATOR_MODEL`)
Generation prompt must require: plausible-looking, consistent with repo style, would plausibly survive a hurried human review, and where feasible passes the existing test suite. Reject and regenerate any defect the test suite catches, and **record the rejection rate per class** — that number is itself a finding.

| Class | Description |
|---|---|
| GEN-01 | Subtle semantic error in domain logic (wrong edge case) |
| GEN-02 | Cross-file invariant violation (change breaks an assumption held elsewhere) |
| GEN-03 | Test-weakening (loosened assertion, deleted case, widened tolerance, mocking the unit under test) |
| GEN-04 | Concurrency/resource (race window, unclosed resource, non-idempotent retry) |
| GEN-05 | Input-validation / path-handling regression |
| GEN-06 | Spec divergence (code contradicts its own docstring / PR description) |

GEN-03 is priority-weighted: it maps directly onto the operator's proxy-metric ladder. Do not drop it under any scope reduction.

### Arm 3 — SZZ (real historical defects; the gold control)
Mine defect-introducing commits from repo history using SZZ (via `pydriller`): identify bug-fix commits (issue links + keyword heuristics), blame the fixed lines back to introducing commits, filter cosmetic/whitespace/rename noise. Reconstruct each defect-introducing commit as a review-time diff. Label class post hoc using the taxonomy above (LLM-assisted labeling is fine; store the rationale).

SZZ quality is the known risk. Requirements: (a) implement at least two precision-improving filters and document them; (b) dump **20 randomly sampled SZZ items with full provenance** into `audit/szz_sample/` for the operator's manual precision audit; (c) if after honest effort SZZ yields <30 usable items, execute Fallback F3 (§11): substitute or supplement with **BugsInPy** (curated real Python defects with fix pairs) and record the substitution.

**Why three defective arms:** GEN defects are drawn from a model's own defect distribution — a verifier from the same family may detect them at a biased rate. MUT is unbiased but shallow. SZZ/BugsInPy is the reality anchor. The arm-vs-arm detection comparison at matched class labels is a primary analysis (§7), not a nice-to-have.

---

## 6. Verifier Protocol

- **Input:** unified diff + full post-change contents of every touched file + the PR-style description (for GEN-06, the description is part of the defect). One context strategy for the primary run: **diff + full touched files**. Alternative strategies (diff-only, retrieval-augmented) are out of scope; leave the interface pluggable.
- **Blindness:** no arm/class/base-rate/ordering information. Randomize item order with the run seed. Identical prompt template for every item (Appendix A).
- **Output:** strict JSON: `{defect_found: bool, confidence: 0–100, locations: [{file, start_line, end_line}], class_guess: string|null, severity: "low"|"med"|"high"|null, rationale: string}`. Malformed JSON → one re-ask with a format reminder → if still malformed, score as abstention and log.
- **One pass per item.** No self-consistency sampling in v0 (cost); leave a config hook.

---

## 7. Metrics and Statistical Analysis Plan (pre-specified — do not extend or trim)

**Primary:**
1. Per-class detection rate (per §3 definition) with **95% Wilson score intervals**, reported per arm and pooled across repos.
2. False-positive rate on CLEAN with Wilson CI.
3. **Arm gap at matched class:** detection(GEN) − detection(SZZ) per class where both arms have n≥15, with bootstrap CIs. This is the self-distribution-bias probe.

**Secondary:** AUROC per class using `confidence`; localization precision (fraction of detections whose reported location overlaps ground truth — already required for "detection," so report the misdirected-flag rate separately); calibration (reliability curve + Brier score); cost per review (tokens, latency, USD) per class — pipe into the event stream.

**Reporting rules:** report every pre-specified metric whether flattering or not; CIs everywhere; no p-value hunting; a `MEASURED vs INFERRED` section in the report that explicitly separates computed numbers from your interpretations.

---

## 8. Repository Selection

Criteria: Python; permissive license (MIT/BSD/Apache); 5k–100k LOC; pytest suite green in <5 min on this machine; ≥3 years of commit history; active issue tracker (SZZ needs linkable fixes). Select **3–5** from this candidate list, validating each: `requests`, `click`, `flask`, `httpx`, `tenacity`, `attrs`, `jinja2`, `rich`. Substitutions allowed if a candidate fails validation — log why.

---

## 9. Sample Sizes, Budget, Configuration

- **Target:** n=50 defective items per class per the pooled run (11 classes ≈ 550 defective) + ~370 CLEAN → ~920 review items. **Floor:** n=30/class. Below floor for a class → report it with a LOW-POWER flag, don't drop it.
- **Phase 0 duty:** forecast total API spend (items × est. tokens × price for both generation and review) and write it to `PHASE0_REPORT.md` **before** any full-scale run. If forecast > `GYM_SPEND_CAP_USD`, scale n down proportionally across classes (never below floor; shed repos before classes) and log the arithmetic.
- **Env vars:** `ANTHROPIC_API_KEY` (present), `GYM_GENERATOR_MODEL`, `GYM_VERIFIER_MODEL`, `GYM_SPEND_CAP_USD`, `GYM_SEED`. Hard-stop all API calls if cumulative spend reaches the cap; persist partial state cleanly.

---

## 10. Phases and Exit Criteria

Each phase ends with `PHASE<k>_REPORT.md`: what was built, decisions made, exit-criteria checklist, spend so far, go/no-go for next phase. Self-assessed honestly — the operator will check.

- **Phase 0 — Recon & plan.** Repo selection/validation, spend forecast, skeleton layout. *Exit:* ≥3 repos validated; forecast under cap.
- **Phase 1 — Harness spine.** CLEAN arm + canary defects (§14) + `review`/`score`/`leakcheck`/`smoke` working end-to-end. *Exit:* smoke passes; canary detection ≥90%; leakcheck clean.
- **Phase 2 — MUT arm** at full sample size.
- **Phase 3 — GEN arm.** Includes rejection-rate tracking. *Exit:* all six GEN classes populated to floor or logged as infeasible.
- **Phase 4 — SZZ arm** (or BugsInPy fallback). *Exit:* ≥30 real-defect items + audit sample dumped.
- **Phase 5 — Full run & report.** Execute the pre-specified analysis (§7), generate `REPORT.md`, run the self-audit (§14), write `LIMITATIONS.md`.

Relative effort weights: 0:1:2:2:3:2. Phase 4 is the schedule risk; do not let it starve Phase 5 — a finished report over three arms beats an unfinished one over four.

---

## 11. Fallback Hierarchy (when blocked)

Apply in order; log every activation with its trigger:

- **F1:** Fix forward within the current phase's effort weight.
- **F2:** Reduce scope along pre-approved axes only: fewer repos → smaller n (≥ floor) → drop alternative-context hooks. Never drop GEN-03; never touch metric definitions.
- **F3:** Substitute SZZ with BugsInPy (or run both partially).
- **F4:** Declare an arm failed, document the post-mortem in `PHASE<k>_REPORT.md`, continue with remaining arms.

Never: pause to wait for input; invent new metrics; relax the leakcheck; report an unpowered number without its flag.

## Hard Constraints & Anti-Goals

No web UI. No fine-tuning. No plugin architecture. No secrets in the repo. No repos beyond the size band. No claim in `REPORT.md` that `gym reproduce` cannot regenerate.

---

## 12. Audit Trail (mandatory, append-only)

- `DECISIONS.md` — numbered; every non-trivial choice: options considered, choice, reason, spec section it interprets.
- `ASSUMPTIONS.md` — every gap-filling assumption where the spec was silent.
- `WORKLOG.md` — timestamped narrative of what you did, including dead ends. Dead ends are data; do not sanitize them.
- Phase reports per §10.

---

## 13. Deliverables & Layout

```
verification-gym/
  README.md            # install, quickstart, config reference
  HANDOFF.md           # this file, unmodified
  config.yaml
  gym/                 # source
  tests/               # harness self-tests
  data/                # sqlite, payloads, cache (gitignored where large)
  events/run_<id>.jsonl
  audit/szz_sample/
  reports/REPORT.md, PHASE*_REPORT.md, LIMITATIONS.md
  DECISIONS.md  ASSUMPTIONS.md  WORKLOG.md
```

---

## 14. Self-Audit & Acceptance (how you know you are done)

1. **Canary suite:** ≥20 trivially detectable defects (syntax-adjacent, blatant logic inversions with comments removed). Verifier detection must be ≥90%; below that, the pipeline — not the model — is presumed broken.
2. **Null test:** a CLEAN-only mini-run; FP machinery produces sane output.
3. **Leak test:** `gym leakcheck` green over every payload in the final run.
4. **Determinism:** `gym reproduce` regenerates `REPORT.md` from cache, byte-comparable modulo timestamps.
5. **Smoke:** `gym smoke` green in <15 min from a fresh clone with only env vars set.
6. **`LIMITATIONS.md`:** written adversarially — every reason a skeptic could distrust the headline numbers, including the ones you'd rather omit. Known entry to include: *in this run, generator = verifier = same model; the GEN-arm headline is presumptively biased and the SZZ/BugsInPy arm is the trustworthy real-defect number until the cross-model matrix is run.*

---

## 15. PRE-REGISTRATION (completed by operator before launch — DO NOT MODIFY)

> Committed to git before the run. Predictions are scored against §7 outputs afterward.

- Predicted pooled detection rate, MUT arm: ______ %  (80% CI: ______–______)
- Predicted pooled detection rate, GEN arm: ______ %  (80% CI: ______–______)
- Predicted pooled detection rate, SZZ/real arm: ______ %  (80% CI: ______–______)
- Predicted FP rate on CLEAN: ______ %
- Predicted sign of the arm gap (GEN − SZZ): ______
- Predicted hardest class: ______   Predicted easiest class: ______
- Predicted probability the agent completes Phase 5 without F4: ______ %
- Expected dominant failure mode of the run itself: ______________________

---

## Appendix A — Verifier Prompt Template (fixed)

```
You are reviewing a proposed code change before merge.

<pr_description>{description}</pr_description>
<diff>{unified_diff}</diff>
<files>{full_contents_of_touched_files_post_change}</files>

Determine whether this change introduces a defect. Respond with ONLY a JSON
object: {"defect_found": bool, "confidence": 0-100, "locations":
[{"file": str, "start_line": int, "end_line": int}], "class_guess":
str|null, "severity": "low"|"med"|"high"|null, "rationale": str}.
If the change is acceptable, defect_found is false and locations is [].
```

## Appendix B — Event Stream Schema (public API; consumed by downstream SPC monitor)

One JSON object per line:

```json
{"ts": "ISO8601", "run_id": str, "repo": str, "item_id": str,
 "arm": "CLEAN|MUT|GEN|SZZ", "class": str|null,
 "generator_model": str|null, "verifier_model": str,
 "verdict": {…verbatim §6 object…},
 "ground_truth": {"defective": bool, "class": str|null},
 "outcome": "detected|missed|misdirected_flag|false_positive|true_negative|abstained",
 "tokens_in": int, "tokens_out": int, "latency_ms": int, "cost_usd": float,
 "seed": int, "prompt_hash": str}
```

Schema changes require a version bump (`"schema": "gym-events/1"` field) — downstream consumers depend on it.

## Appendix C — BugsInPy Fallback Notes

BugsInPy provides curated real defects in major Python projects with buggy/fixed commit pairs. If used: reconstruct the buggy commit as a review-time diff exactly as with SZZ items, label classes post hoc, and tag provenance `"szz_source": "bugsinpy"` so the arms remain distinguishable in analysis.

---

*End of handoff. Begin with Phase 0. Good hunting.*
