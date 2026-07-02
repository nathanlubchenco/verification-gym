# ASSUMPTIONS (append-only, numbered)

Gap-filling assumptions where HANDOFF.md is silent. Each cites the spec section it fills a gap in.

- **A1** (§9): `GYM_GENERATOR_MODEL` / `GYM_VERIFIER_MODEL` env vars are unset. Assume the operator intends config-file defaults overridable by env. Defaults chosen in DECISIONS D2.
- **A2** (§9): `GYM_SPEND_CAP_USD` unset. This is the operator's personal API key; assume a conservative default cap is preferred over an aggressive one. Default set in DECISIONS D3.
- **A3** (§9): `GYM_SEED` unset. Assume any fixed, documented seed is acceptable. Default `GYM_SEED=20260702` (run date), set in config.yaml.
- **A4** (§15): Pre-registration blanks are empty and the repo had no commits at run start, though §15 claims it was committed before launch. Assume the operator intends the section to stand as-is; I did not fill or modify it. Consequence: predictions cannot be scored after the run; noted for LIMITATIONS.md.
- **A5** (§5, CLEAN): "Real merged PRs" — mining actual GitHub PR objects requires the GitHub API (rate limits, network flakiness, non-reproducible). Assume merged-to-mainline *commits* from repo history (with their commit messages as PR-style descriptions) are an acceptable operationalization of "merged PRs"; most candidate repos use squash-merge or merge commits so mainline commits ≈ PRs. Recorded as DECISIONS D5.
- **A6** (§3/§5): For MUT and GEN arms the spec doesn't say what diff the defect is embedded in. A bare one-line mutation diff would be trivially distinguishable from CLEAN items (shape leak → violates Priority 1, measurement correctness). Assume defects must be injected into real historical "carrier" commits drawn from the same pool as CLEAN items, so defective and clean items share a superficial distribution. Recorded as DECISIONS D6.
- **A7** (§6): "full post-change contents of every touched file" — for very large files this could blow the context window. Assume a hard per-item payload budget with oversized items excluded at sampling time (logged), rather than truncation (truncation could hide ground-truth lines and corrupt measurement).
- **A8** (§8): "pytest suite green in <5 min on this machine" — assume "green" tolerates tests skipped due to missing optional extras, but zero failures/errors.
