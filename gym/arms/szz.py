"""Arm 3 — SZZ: real historical defects mined via pydriller (HANDOFF §5).

Pipeline: find bug-fix commits (keyword + issue-ref heuristics) -> blame the
fixed lines back to introducing commits (pydriller SZZ) -> precision filters ->
reconstruct the introducing commit as a review-time diff -> post-hoc class
label via LLM (rationale stored in provenance).

Precision filters (§5 requires >=2; we apply 3):
  P1  only non-blank, non-comment deleted lines participate in blame, and an
      introducer counts only if >=1 such line is attributed to it;
  P2  fix commits touching more than MAX_FIX_FILES files are ignored
      (large refactors produce noisy blame);
  P3  introducers that are merges, whitespace-only, or huge (>300 changed
      lines) are dropped, as are introducers already used by any other arm.

Ground-truth locations: each blamed line's content is located in the
introducer's post-state file, giving exact post-change coordinates (D9).
20 randomly sampled items with full provenance are dumped to audit/szz_sample/.
"""

from __future__ import annotations

import json
import random
import re
import sqlite3
from pathlib import Path

from .. import gitrepo
from ..config import Config
from ..llm import SpendCapExceeded, call_model
from ..payload import Payload, payload_from_commit

FIX_STRICT_RE = re.compile(
    r"\bfix(e[sd])?\b.*(#\d+|\bbug\b|\bregression\b|\bcrash\b|\bissue\b)"
    r"|\b(bug|regression|crash)\b.*\bfix(e[sd])?\b"
    r"|\bfix(es|ed)? #\d+|\bcloses? #\d+.*\bbug\b",
    re.IGNORECASE | re.DOTALL,
)
MAX_FIX_FILES = 5
MAX_INTRODUCER_LINES = 300
AUDIT_SAMPLE_N = 20

TAXONOMY_FOR_LABELING = """\
MUT-01: boundary / off-by-one error (< vs <=, +-1 in indices/ranges)
MUT-02: logic operator error (and/or swapped, ==/!= swapped, wrong negation)
MUT-03: same-type variable/argument swap or wrong variable used
MUT-04: error handling missing, removed, or swallowed
MUT-05: wrong default/config value (timeouts, limits, flags)
GEN-01: subtle semantic error in domain logic (wrong edge case)
GEN-02: cross-file invariant violation (assumption broken elsewhere)
GEN-03: test-weakening (assertion loosened, case missing, over-mocking)
GEN-04: concurrency/resource defect (race, unclosed resource, non-idempotent retry)
GEN-05: input-validation / path-handling defect
GEN-06: spec divergence (code contradicts docstring/description)
OTHER: none of the above fits"""

LABEL_SYSTEM = (
    "You classify real historical software defects into a fixed taxonomy. "
    "Respond with ONLY a JSON object: "
    '{"class": "<one taxonomy id>", "rationale": "<2-3 sentences>"}'
)


def _code_lines(deleted: list[tuple[int, str]]) -> list[tuple[int, str]]:
    out = []
    for num, content in deleted:
        s = content.strip()
        if s and not s.startswith("#"):
            out.append((num, content))
    return out


def find_fix_commits(repo_dir: Path) -> list[gitrepo.Commit]:
    fixes = []
    for c in gitrepo.log_commits(repo_dir, no_merges=True):
        if not FIX_STRICT_RE.search(f"{c.subject}\n{c.body}"):
            continue
        py = [f for f in c.files if f.endswith(".py")]
        if not py or len(c.files) > MAX_FIX_FILES:      # P2
            continue
        fixes.append(c)
    return fixes


def blame_introducers(repo_dir: Path, fix: gitrepo.Commit):
    """Returns {introducer_sha: {file: [line_content, ...]}} using pydriller's
    SZZ implementation, restricted to code lines (P1)."""
    from pydriller import Git

    g = Git(str(repo_dir))
    commit = g.get_commit(fix.sha)
    out: dict[str, dict[str, list[str]]] = {}
    for mod in commit.modified_files:
        if not (mod.new_path or mod.old_path or "").endswith(".py"):
            continue
        deleted = _code_lines(mod.diff_parsed.get("deleted", []))
        if not deleted:
            continue
        try:
            blamed = g.get_commits_last_modified_lines(commit, mod)
        except Exception:
            continue
        deleted_contents = sorted({content.strip() for _, content in deleted})
        key = mod.old_path or mod.new_path
        for _path, shas in blamed.items():
            for sha in shas:
                out.setdefault(sha, {})[key] = deleted_contents
    return out


def _introducer_ok(repo_dir: Path, sha: str) -> bool:                 # P3
    parents = gitrepo.run_git(repo_dir, "rev-list", "--parents", "-n", "1",
                              sha).split()
    if len(parents) != 2:       # merge or root
        return False
    diff = gitrepo.commit_diff(repo_dir, sha)
    n_changed = sum(1 for ln in diff.splitlines()
                    if ln.startswith(("+", "-")) and not ln.startswith(("+++", "---")))
    if n_changed == 0 or n_changed > MAX_INTRODUCER_LINES:
        return False
    diff_w = gitrepo.run_git(repo_dir, "show", "--format=", "-w", sha)
    if not any(l.startswith(("+", "-")) and not l.startswith(("+++", "---"))
               for l in diff_w.splitlines()):
        return False            # whitespace-only
    return True


def _gt_from_blamed_lines(repo_dir: Path, sha: str,
                          blamed: dict[str, list[str]]) -> dict[str, list[tuple[int, int]]]:
    gt: dict[str, list[tuple[int, int]]] = {}
    for path, contents in blamed.items():
        if not gitrepo.file_exists_at(repo_dir, sha, path):
            continue
        file_lines = gitrepo.file_at(repo_dir, sha, path).split("\n")
        hits = []
        for want in contents:
            for i, line in enumerate(file_lines, start=1):
                if line.strip() == want:
                    hits.append(i)
        if hits:
            hits = sorted(set(hits))
            ranges = []
            start = prev = hits[0]
            for h in hits[1:]:
                if h == prev + 1:
                    prev = h
                    continue
                ranges.append((start, prev))
                start = prev = h
            ranges.append((start, prev))
            gt[path] = ranges
    return gt


def label_defect(cfg: Config, conn, intro: gitrepo.Commit, fix: gitrepo.Commit,
                 diff: str) -> tuple[str, str]:
    prompt = (
        f"Taxonomy:\n{TAXONOMY_FOR_LABELING}\n\n"
        f"A defect was introduced by this commit:\n"
        f"<message>{intro.message[:1500]}</message>\n<diff>{diff[:12000]}</diff>\n\n"
        f"It was later fixed by a commit described as:\n"
        f"<fix_message>{fix.message[:1500]}</fix_message>\n\n"
        "Classify the introduced defect. Respond with ONLY the JSON object."
    )
    r = call_model(cfg, conn, model=cfg.generator_model, system=LABEL_SYSTEM,
                   prompt=prompt, max_tokens=400, purpose="szz-label")
    from ..review import _extract_json

    obj = _extract_json(r.text) or {}
    klass = str(obj.get("class", "OTHER")).strip()
    valid = {ln.split(":")[0] for ln in TAXONOMY_FOR_LABELING.splitlines()}
    if klass not in valid:
        klass = "OTHER"
    return klass, str(obj.get("rationale", ""))[:800]


def generate_szz(cfg: Config, conn: sqlite3.Connection, target: int = 150,
                 progress=print) -> int:
    from ..generate import add_review_item, _unique_id

    rng = random.Random(f"{cfg.seed}:szz")
    have = conn.execute(
        "SELECT COUNT(*) c FROM defect_records d JOIN review_items i"
        " ON i.defect_id=d.defect_id WHERE d.arm='SZZ'").fetchone()["c"]
    made = 0
    used_shas = {r[0] for r in conn.execute(
        "SELECT carrier_sha FROM defect_records WHERE carrier_sha IS NOT NULL")}
    used_shas |= {r[0] for r in conn.execute(
        "SELECT sha FROM commit_pool WHERE assigned_to LIKE 'CLEAN_USED:%'")}

    repos = [r["name"] for r in conn.execute(
        "SELECT name FROM repos WHERE validated=1 ORDER BY name")]
    candidates: list[tuple[str, gitrepo.Commit, gitrepo.Commit, dict]] = []
    for repo in repos:
        repo_dir = cfg.root / cfg.data_dir / "repos" / repo
        fixes = find_fix_commits(repo_dir)
        progress(f"szz: {repo}: {len(fixes)} candidate fix commits")
        for fix in fixes:
            intro_map = blame_introducers(repo_dir, fix)
            for sha, blamed in intro_map.items():
                if sha in used_shas or not any(blamed.values()):
                    continue
                if not _introducer_ok(repo_dir, sha):
                    continue
                candidates.append((repo, sha, fix, blamed))

    rng.shuffle(candidates)
    progress(f"szz: {len(candidates)} filtered introducer candidates")
    seen_intro: set[tuple[str, str]] = set()
    audit_rows = []
    for repo, sha, fix, blamed in candidates:
        if have + made >= target:
            break
        if (repo, sha) in seen_intro:
            continue
        seen_intro.add((repo, sha))
        repo_dir = cfg.root / cfg.data_dir / "repos" / repo
        gt = _gt_from_blamed_lines(repo_dir, sha, blamed)
        if not gt:
            continue
        intro_commits = gitrepo.log_commits(repo_dir, rev_range=f"{sha}~1..{sha}")
        if not intro_commits:
            continue
        intro = intro_commits[0]
        p = payload_from_commit(repo_dir, sha, intro.message)
        diff = p.diff
        try:
            klass, rationale = label_defect(cfg, conn, intro, fix, diff)
        except SpendCapExceeded as exc:
            progress(f"HARD STOP in SZZ labeling: {exc}")
            break
        defect_id = _unique_id(conn, "d", rng, "defect_records", "defect_id")
        gt_json = [{"file": f, "start_line": s, "end_line": e}
                   for f, ranges in sorted(gt.items()) for s, e in ranges]
        provenance = {
            "szz_source": "szz", "fix_sha": fix.sha, "fix_subject": fix.subject,
            "label_rationale": rationale,
            "blamed_lines": {f: c for f, c in blamed.items() if c},
        }
        conn.execute(
            "INSERT INTO defect_records (defect_id, arm, class, repo,"
            " injection_method, carrier_sha, ground_truth_diff,"
            " ground_truth_locations, provenance) VALUES (?,?,?,?,?,?,?,?,?)",
            (defect_id, "SZZ", klass, repo, "szz:pydriller", sha, diff,
             json.dumps(gt_json), json.dumps(provenance, sort_keys=True)),
        )
        conn.commit()
        item_id = add_review_item(cfg, conn, rng, repo=repo, p=p,
                                  defective=True, defect_id=defect_id)
        if item_id is None:
            conn.execute("DELETE FROM defect_records WHERE defect_id=?", (defect_id,))
            conn.commit()
            continue
        made += 1
        audit_rows.append({"defect_id": defect_id, "repo": repo,
                           "introducer_sha": sha, "fix_sha": fix.sha,
                           "fix_subject": fix.subject, "class": klass,
                           "rationale": rationale, "gt": gt_json})
        if made % 20 == 0:
            progress(f"szz: {made} items so far")

    _dump_audit_sample(cfg, conn, rng)
    progress(f"szz: created {made} items (prior {have})")
    return made


def _dump_audit_sample(cfg: Config, conn, rng: random.Random) -> None:
    rows = conn.execute(
        "SELECT d.*, i.item_id, i.payload_path FROM defect_records d"
        " JOIN review_items i ON i.defect_id=d.defect_id"
        " WHERE d.arm='SZZ' ORDER BY d.defect_id").fetchall()
    if not rows:
        return
    sample = rng.sample(rows, min(AUDIT_SAMPLE_N, len(rows)))
    out_dir = cfg.root / "audit" / "szz_sample"
    out_dir.mkdir(parents=True, exist_ok=True)
    for r in sample:
        prov = json.loads(r["provenance"])
        doc = {
            "defect_id": r["defect_id"], "repo": r["repo"],
            "class": r["class"], "introducer_sha": r["carrier_sha"],
            "fix_sha": prov["fix_sha"], "fix_subject": prov["fix_subject"],
            "label_rationale": prov["label_rationale"],
            "blamed_lines": prov["blamed_lines"],
            "ground_truth_locations": json.loads(r["ground_truth_locations"]),
            "introducing_diff": r["ground_truth_diff"],
            "review_item": r["item_id"],
        }
        (out_dir / f'{r["defect_id"]}.json').write_text(
            json.dumps(doc, indent=1, sort_keys=True))
