# PHASE 4 REPORT — SZZ Arm (real historical defects)

Date: 2026-07-03 · Cumulative spend at phase close: **$35.6** (SZZ labeling ≈ $4.4)

Note: Phases 3 and 4 ran overlapped (§10 effort weights; Phase 4 was flagged as
the schedule risk, so it was started early in parallel with GEN generation).

## What was built / run

`gym/arms/szz.py`: pydriller-based SZZ. Bug-fix commits identified by strict
keyword+issue-ref heuristics; fixed lines blamed back to introducing commits
(`Git.get_commits_last_modified_lines`); each introducer reconstructed as a
review-time diff with its own commit message as the PR description.

**Precision filters (§5 requires ≥2; three applied):**
- **P1** only non-blank, non-comment deleted lines participate in blame; an
  introducer counts only if ≥1 such line is attributed to it.
- **P2** fix commits touching >5 files ignored (large refactors → noisy blame).
- **P3** introducers that are merges, whitespace-only, or >300 changed lines
  dropped; introducers already used by any other arm or the CLEAN set excluded.

**Ground truth:** each blamed line's content is located in the introducer's
post-state file → exact post-change line coordinates (D9). Items whose blamed
lines could not be located are skipped, not approximated.

**Post-hoc class labels:** LLM-assisted (generator model), mapping onto the 11
class taxonomy + OTHER; the label rationale is stored in provenance (§5
requirement). The fix-commit message (ground truth) is visible to the labeler,
never to the verifier.

## Results

- **150 usable SZZ items** (exit bar: ≥30 — met 5×; BugsInPy fallback F3 not needed).
- Sources: 127 distinct fix commits → introducers across requests (58),
  jinja2 (41), click (32), attrs (19).
- Post-hoc class distribution: GEN-01 74, GEN-02 17, MUT-03 10, GEN-04 10,
  GEN-06 9, GEN-05 9, MUT-04 8, GEN-03 5, MUT-01 3, OTHER 2, MUT-05 2, MUT-02 1.
  Real defects skew heavily to subtle semantic errors — itself a finding.
- **`audit/szz_sample/`: 20 randomly sampled items** with full provenance
  (introducer/fix shas, blamed lines, label rationale, GT locations,
  introducing diff) for the operator's manual precision audit (§5b).

## Exit criteria (§10 Phase 4)

- [x] ≥30 real-defect items (150)
- [x] ≥2 precision-improving filters implemented and documented (3)
- [x] Audit sample dumped

**Phase 4 complete.** Arm-gap analysis (§7.3) will be computable for classes
with n≥15 on both GEN and SZZ sides (GEN-01, GEN-02 at minimum).
