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
