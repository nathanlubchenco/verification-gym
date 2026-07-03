# LIMITATIONS — written adversarially

Every reason a skeptic could distrust the headline numbers. If you plan to
quote REPORT.md, read this first.

## The one the operator pre-registered (§14.6)

1. **Generator = verifier = the same model (`claude-opus-4-8`).** The GEN-arm
   headline is presumptively biased: a verifier reviewing defects drawn from
   its own defect distribution may detect them at an unrepresentative rate (in
   either direction — familiarity could help detection, or shared blind spots
   could suppress it). **The SZZ arm is the trustworthy real-defect number**
   until the cross-model matrix is run. The harness keeps generator and
   verifier as independent env-var parameters precisely for that follow-up.

## Ground-truth validity

2. **"Presumed clean" is a presumption.** CLEAN items are old mainline commits
   with no revert and no fix-flavored commit touching the same lines (±3 slop)
   within 6 months (D5/D13). Defects fixed later than 6 months, never fixed,
   or fixed with unmatched commit messages survive the filter. The measured
   "false-positive rate" is therefore an upper bound: some FPs may be real
   defects. The gate-review sample already flagged 6/30 presumed-clean commits.
3. **The CLEAN filter is line-approximate.** Line coordinates drift between a
   commit and a later fix; hunk-overlap with slop is a heuristic, and fix
   detection relies on commit-message regexes (English fix-keyword conventions).
4. **SZZ has known systematic biases.** Blame-based introducer identification
   mislabels refactors, misses defects introduced by omission, and inherits
   fix-commit identification errors. Three precision filters and a 20-item
   manual audit sample (audit/szz_sample/) mitigate but do not eliminate this.
   SZZ ground-truth *locations* map blamed line contents back to the
   introducer's post-state by exact string match — multi-occurrence lines can
   widen GT.
5. **SZZ class labels are LLM-assigned** (post hoc, rationale stored, fix
   message visible to the labeler). Label noise directly moves the per-class
   SZZ rates and the §7.3 arm gap. The labeler is also the same base model.

## Injected-defect realism

6. **Carrier framing.** MUT/GEN/canary defects ride inside real commits, but
   the *combination* (carrier message + unrelated defect hunk) has no real
   commit where everything is explained. A verifier that flags "hunk unrelated
   to stated intent" does well here — that skill transfers to review, but it
   is not identical to catching organically-authored bugs.
7. **GEN suite gate was feasible for only 13% of accepted items** (35/265).
   Old carriers cannot execute under 2026 venvs; `requests` is repo-level
   infeasible (one persistent env-dependent test failure, n=3 sample). For the
   other 87%, "passes the existing test suite" is unverified — some GEN
   defects might have been caught by their era's suite. Recorded per item
   (`provenance.suite_feasible`).
8. **MUT-03 is approximate:** "same-type variable/argument swap" is
   implemented as a textual swap of two bare-name call arguments; type
   sameness is not verified. Some MUT-03 items may be type errors a static
   checker would catch rather than subtle semantic swaps.
9. **Cross-class carrier reuse in GEN.** A carrier commit may host defects for
   more than one GEN class (never two items in the same class). Items sharing
   a carrier are statistically clustered; per-class CIs treat them as
   independent.

## Protocol and scoring

10. **Location-overlap detection is strict** (D9: ±2 lines of the defect
    hunk). A verifier that identifies the defect semantically but reports a
    related line >2 lines away scores `misdirected_flag`, not `detected` —
    this was observed on a canary during Phase 1. Detection rates are
    therefore conservative; the misdirected-flag rate is reported separately.
11. **AUROC/Brier depend on an interpretation of `confidence`** (D15:
    p(defective) = confidence if flagged else 100−confidence). Appendix A does
    not define confidence semantics; a different mapping changes those
    secondary metrics (not detection/FP).
12. **One prompt, one pass, no thinking** (D16). Results characterize the
    verifier under the fixed Appendix A protocol at default inference
    settings — not the model's ceiling. Latency is recorded as 0 for batched
    reviews (D17); token/cost numbers are exact.
13. **Repos are all Python, permissively-licensed, well-tested, 5k–100k LOC**
    (4 validated of 8 candidates). Generalization beyond that population is
    inference, not measurement. All four repos almost certainly appear in the
    verifier's training data; memorized code may aid (or bias) review.
14. **Old commits are old.** The CLEAN-window requirement pushes all
    carrier/clean commits ≥1 year back (often much older). Coding styles and
    defect patterns of older code may not represent current development.

## Run integrity

15. **The operator's §15 pre-registration was found blank** and the repo had
    no pre-run commit; predictions cannot be scored against §7 outputs (A4).
16. **Account credits ran out mid-run** (after MUT/SZZ generation and the
    non-GEN review batch submission; internal spend cap was NOT hit).
    Consequences at time of writing: GEN topped out at 265/300 (all classes ≥
    floor 30; no LOW-POWER flags), and any review shortfall is visible in the
    per-class `n` columns of REPORT.md. Every command resumes verbatim once
    credits exist; the cache guarantees already-obtained verdicts are never
    re-bought.
17. **Canary ops were revised once** after the first gate run failed at 87.5%
    (Phase 1, F1 fix-forward): ops restricted and test files excluded, canaries
    regenerated, gate re-run → 100%. Metric definitions were never touched.
    The failed gate run remains in WORKLOG and the git history.
