"""Arm 2 — GEN: LLM-generated subtle defects (HANDOFF §5, GEN-01..06).

Per accepted defect: generator model proposes a single edit to a carrier
commit's post-state; the edit must anchor uniquely, still parse, change the
AST, and — where the carrier's test suite is feasible — survive it. Defects
the suite catches are rejected and the rejection rate per class is recorded
(gen_attempts table): that number is itself a finding.

GEN-03 (test-weakening) targets test files and is never dropped (§11 F2).
GEN-06 may also rewrite the PR description (the description is part of the
defect per §6).
"""

from __future__ import annotations

import ast
import json
import os
import random
import re
import sqlite3
import subprocess
import tempfile
import time
from pathlib import Path

from .. import gitrepo
from ..config import Config
from ..inject import Edit, InjectionError, build_injected_change
from ..llm import SpendCapExceeded, call_model
from ..payload import Payload

GEN_CLASSES = ["GEN-01", "GEN-02", "GEN-03", "GEN-04", "GEN-05", "GEN-06"]

GEN_SPECS = {
    "GEN-01": "a subtle semantic error in domain logic: the code handles a "
              "specific edge case incorrectly (wrong boundary, wrong default on "
              "an unusual path, wrong order of operations) while remaining "
              "correct on the common path",
    "GEN-02": "a cross-file invariant violation: change code in one file so it "
              "silently breaks an assumption that other code in this change "
              "relies on (a contract between functions/files: shape, ordering, "
              "encoding, sentinel value, locking discipline)",
    "GEN-03": "a test-weakening change: loosen an assertion, delete a test "
              "case branch, widen a tolerance, or mock out the very unit the "
              "test is supposed to exercise, so the test still passes but no "
              "longer catches regressions",
    "GEN-04": "a concurrency or resource-handling defect: introduce a race "
              "window, leave a resource unclosed on an error path, or make a "
              "retried operation non-idempotent",
    "GEN-05": "an input-validation or path-handling regression: weaken or skip "
              "validation of untrusted input, mishandle a path edge case "
              "(absolute/relative, trailing separator, encoding), or accept a "
              "value that should be rejected",
    "GEN-06": "a spec divergence: make the code contradict its own docstring, "
              "comment, or the PR description (e.g. docstring promises "
              "inclusive bounds but code is exclusive). The observable "
              "documentation must stay as-is or become misleading",
}

SYSTEM_PROMPT = (
    "You are constructing evaluation data for a private code-review benchmark. "
    "You will be shown a real merged change from an open-source repository. "
    "Introduce exactly one additional flaw of the requested kind into one of "
    "the shown files, as a minimal edit.\n"
    "Requirements:\n"
    "- plausible-looking and consistent with the repository's style;\n"
    "- subtle enough that a hurried human reviewer would plausibly approve it;\n"
    "- it must NOT add or change any comments, and must not reference this "
    "task in any way;\n"
    "- the edited file must remain syntactically valid Python;\n"
    "- where possible it should not be caught by the project's test suite.\n"
    "Respond with ONLY a JSON object:\n"
    '{"file": "<path from the shown files>", "old": "<exact contiguous snippet '
    'copied verbatim from that file, 1-8 lines, unique within the file>", '
    '"new": "<replacement snippet>", "note": "<one sentence: what the flaw is '
    'and when it bites>"'
    ', "new_description": "<optional replacement PR description; only if '
    'rewriting the description is part of the flaw>"}'
)

GEN_MAX_TOKENS = 2500
# attempts budget = factor * n_per_class; 2.4 keeps GEN's worst-case API spend
# within the Phase 0 forecast envelope while allowing ~58% rejection headroom
MAX_ATTEMPTS_PER_CLASS_FACTOR = 2.4
SUITE_TIMEOUT_S = 150

_TEST_FILE = re.compile(r"(^|/)test(s)?(/|_)|_test\.py$")


def is_test_file(path: str) -> bool:
    return bool(_TEST_FILE.search(path))


def build_gen_prompt(klass: str, description: str, diff: str,
                     files: dict[str, str]) -> str:
    parts = [
        f"Requested flaw kind: {GEN_SPECS[klass]}",
        "",
        "The merged change you are modifying:",
        f"<pr_description>{description}</pr_description>",
        f"<diff>{diff}</diff>",
        "Full post-change contents of the touched files:",
    ]
    for path in sorted(files):
        parts.append(f"===== {path} =====\n{files[path]}")
    if klass == "GEN-03":
        parts.append("The flaw MUST be in one of the test files shown above.")
    if klass == "GEN-06":
        parts.append("If useful, you may also supply new_description to make "
                     "the stated intent contradict the code.")
    parts.append("Respond with ONLY the JSON object.")
    return "\n".join(parts)


def parse_gen_edit(text: str) -> dict | None:
    from ..review import _extract_json

    obj = _extract_json(text)
    if not obj:
        return None
    if not all(isinstance(obj.get(k), str) and obj.get(k) for k in ("file", "old", "new")):
        return None
    if obj["old"] == obj["new"]:
        return None
    nd = obj.get("new_description")
    if nd is not None and not isinstance(nd, str):
        return None
    return {"file": obj["file"].strip(), "old": obj["old"], "new": obj["new"],
            "note": str(obj.get("note", "")), "new_description": nd}


def _valid_python_edit(text: str, old: str, new: str) -> bool:
    if old not in text or text.count(old) != 1:
        return False
    mutated = text.replace(old, new, 1)
    try:
        a1, a2 = ast.parse(text), ast.parse(mutated)
    except SyntaxError:
        return False
    return ast.dump(a1) != ast.dump(a2)


# ---------- test-suite gate ----------

def _venv_python(cfg: Config, repo: str) -> Path:
    return cfg.root / cfg.data_dir / "venvs" / repo / "bin" / "python"


def _run_pytest_at(cfg: Config, repo: str, sha: str,
                   edits: list[Edit] | None) -> tuple[bool, float, str]:
    """Run the repo's suite at `sha` (+ optional edits) in a temp worktree,
    using the validation venv with the worktree shadowing site-packages."""
    repo_dir = cfg.root / cfg.data_dir / "repos" / repo
    py = _venv_python(cfg, repo)
    if not py.exists():
        return False, 0.0, "no validation venv"
    with tempfile.TemporaryDirectory(prefix="vgts-") as td:
        wt = Path(td) / "wt"
        gitrepo.run_git(repo_dir, "worktree", "add", "--quiet", "--detach",
                        str(wt), sha)
        try:
            for e in edits or []:
                target = wt / e.path
                target.write_text(target.read_text().replace(e.old, e.new, 1))
            env = dict(os.environ)
            src = wt / "src"
            env["PYTHONPATH"] = f"{src}:{wt}" if src.exists() else str(wt)
            start = time.monotonic()
            try:
                proc = subprocess.run(
                    [str(py), "-m", "pytest", "-q", "-x", "-p", "no:cacheprovider"],
                    cwd=wt, env=env, capture_output=True, text=True,
                    timeout=SUITE_TIMEOUT_S,
                )
            except subprocess.TimeoutExpired:
                return False, time.monotonic() - start, "timeout"
            secs = time.monotonic() - start
            tail = (proc.stdout or "").strip().splitlines()
            return proc.returncode == 0, secs, (tail[-1] if tail else "")
        finally:
            gitrepo.run_git(repo_dir, "worktree", "remove", "--force", str(wt))


def baseline_ok(cfg: Config, conn: sqlite3.Connection, repo: str,
                sha: str) -> bool:
    row = conn.execute("SELECT ok FROM carrier_baselines WHERE repo=? AND sha=?",
                       (repo, sha)).fetchone()
    if row is not None:
        return bool(row["ok"])
    ok, secs, note = _run_pytest_at(cfg, repo, sha, None)
    conn.execute(
        "INSERT OR REPLACE INTO carrier_baselines (repo, sha, ok, seconds, note)"
        " VALUES (?,?,?,?,?)", (repo, sha, int(ok), secs, note))
    conn.commit()
    return ok


def _record_attempt(conn, klass, repo, sha, outcome, note=""):
    conn.execute(
        "INSERT INTO gen_attempts (class, repo, sha, outcome, note) VALUES (?,?,?,?,?)",
        (klass, repo, sha, outcome, note[:300]))
    conn.commit()


# ---------- main loop ----------

def _repo_speed_order(conn) -> dict[str, float]:
    return {r["name"]: (r["test_seconds"] or 999.0) for r in
            conn.execute("SELECT name, test_seconds FROM repos WHERE validated=1")}


def generate_gen(cfg: Config, conn: sqlite3.Connection, n_per_class: int,
                 only_class: str | None = None,
                 progress=print) -> dict[str, int]:
    """Generate GEN defects. With only_class set, restrict to that class —
    this is the unit of process-level parallelism (one process per class).
    Carrier reuse: never within a class (tracked via defect_records +
    gen_attempts), allowed across classes (logged in LIMITATIONS: clustered
    carriers, not leakage — items are still reviewed blind and independently)."""
    from ..generate import _carriers, add_defect_record, add_review_item

    classes = [only_class] if only_class else GEN_CLASSES
    rng = random.Random(f"{cfg.seed}:gen:{only_class or 'all'}")
    made = {k: 0 for k in classes}
    for row in conn.execute(
            "SELECT d.class k, COUNT(*) c FROM defect_records d JOIN review_items i"
            " ON i.defect_id=d.defect_id WHERE d.arm='GEN' GROUP BY 1"):
        if row["k"] in made:
            made[row["k"]] = row["c"]
    attempts = {k: 0 for k in classes}
    for row in conn.execute("SELECT class k, COUNT(*) c FROM gen_attempts GROUP BY 1"):
        if row["k"] in attempts:
            attempts[row["k"]] = row["c"]
    budget = {k: MAX_ATTEMPTS_PER_CLASS_FACTOR * n_per_class for k in classes}

    # per-class no-reuse: skip carriers already attempted/used by these classes
    used_by_class: dict[str, set[str]] = {k: set() for k in classes}
    q_marks = ",".join("?" for _ in classes)
    for row in conn.execute(
            f"SELECT class k, sha FROM gen_attempts WHERE class IN ({q_marks})",
            classes):
        if row["k"] in used_by_class:
            used_by_class[row["k"]].add(row["sha"])
    for row in conn.execute(
            f"SELECT class k, carrier_sha sha FROM defect_records"
            f" WHERE arm='GEN' AND class IN ({q_marks})", classes):
        if row["k"] in used_by_class and row["sha"]:
            used_by_class[row["k"]].add(row["sha"])

    speed = _repo_speed_order(conn)
    carriers = list(conn.execute(
        "SELECT * FROM commit_pool WHERE assigned_to='GEN_CARRIER'"
        " ORDER BY repo, sha").fetchall())
    rng.shuffle(carriers)
    carriers.sort(key=lambda r: speed.get(r["repo"], 999.0))
    test_carriers = [c for c in carriers
                     if any(is_test_file(f) and f.endswith(".py")
                            for f in json.loads(c["files_json"]))]
    iters = {k: iter(test_carriers if k == "GEN-03" else carriers)
             for k in classes}

    def next_carrier(klass):
        for c in iters[klass]:
            if c["sha"] not in used_by_class[klass]:
                return c
        return None

    while True:
        need = [k for k in classes
                if made[k] < n_per_class and attempts[k] < budget[k]]
        if not need:
            break
        # neediest class first; GEN-03 prioritized on ties (never dropped)
        klass = sorted(need, key=lambda k: (made[k], k != "GEN-03", k))[0]
        carrier = next_carrier(klass)
        if carrier is None:
            progress(f"gen: no carriers left for {klass}; stopping that class")
            budget[klass] = attempts[klass]  # exhausted
            continue
        used_by_class[klass].add(carrier["sha"])
        attempts[klass] += 1
        repo, sha = carrier["repo"], carrier["sha"]
        repo_dir = cfg.root / cfg.data_dir / "repos" / repo

        msg = f'{carrier["subject"]}\n\n{carrier["body"]}'.strip()
        diff = gitrepo.commit_diff(repo_dir, sha)
        files = {}
        for f in json.loads(carrier["files_json"]):
            if f.endswith(".py") and gitrepo.file_exists_at(repo_dir, sha, f):
                files[f] = gitrepo.file_at(repo_dir, sha, f)
        if not files or (klass == "GEN-03"
                         and not any(is_test_file(f) for f in files)):
            _record_attempt(conn, klass, repo, sha, "invalid_edit", "no usable files")
            continue

        prompt = build_gen_prompt(klass, msg, diff, files)
        try:
            r = call_model(cfg, conn, model=cfg.generator_model,
                           system=SYSTEM_PROMPT, prompt=prompt,
                           max_tokens=GEN_MAX_TOKENS, purpose=f"gen:{klass}")
        except SpendCapExceeded as exc:
            progress(f"HARD STOP in GEN: {exc}")
            break
        edit_spec = parse_gen_edit(r.text)
        if edit_spec is None:
            _record_attempt(conn, klass, repo, sha, "parse_failure")
            continue
        path = edit_spec["file"].removeprefix("b/").removeprefix("./")
        if path not in files:
            _record_attempt(conn, klass, repo, sha, "anchor_failure", f"file {path}")
            continue
        if klass == "GEN-03" and not is_test_file(path):
            _record_attempt(conn, klass, repo, sha, "invalid_edit",
                            "GEN-03 edit not in a test file")
            continue
        if not _valid_python_edit(files[path], edit_spec["old"], edit_spec["new"]):
            _record_attempt(conn, klass, repo, sha, "anchor_failure",
                            "snippet not unique/valid")
            continue
        edit = Edit(path=path, old=edit_spec["old"], new=edit_spec["new"])
        try:
            change = build_injected_change(repo_dir, sha, [edit])
        except InjectionError as exc:
            _record_attempt(conn, klass, repo, sha, "anchor_failure", str(exc))
            continue

        suite_checked = False
        if baseline_ok(cfg, conn, repo, sha):
            suite_checked = True
            ok, secs, note = _run_pytest_at(cfg, repo, sha, [edit])
            if not ok:
                _record_attempt(conn, klass, repo, sha, "suite_caught", note)
                continue

        description = (edit_spec["new_description"]
                       if klass == "GEN-06" and edit_spec["new_description"]
                       else msg)
        p = Payload(description=description, diff=change.presented_diff,
                    files=change.post_files)
        defect_id = add_defect_record(
            conn, rng, arm="GEN", klass=klass, repo=repo,
            injection_method=f"gen:{cfg.generator_model}", change=change,
            provenance={"carrier": sha, "file": path, "note": edit_spec["note"],
                        "suite_checked": suite_checked,
                        "description_rewritten": description != msg},
        )
        item_id = add_review_item(cfg, conn, rng, repo=repo, p=p,
                                  defective=True, defect_id=defect_id)
        if item_id is None:
            conn.execute("DELETE FROM defect_records WHERE defect_id=?", (defect_id,))
            conn.commit()
            _record_attempt(conn, klass, repo, sha, "oversized_payload")
            continue
        _record_attempt(conn, klass, repo, sha, "accepted")
        made[klass] += 1
        if sum(made.values()) % 10 == 0:
            progress(f"gen: totals {made}")
    progress(f"gen: final {made}; attempts {attempts}")
    return made


def rejection_rates(conn) -> dict[str, dict]:
    out = {}
    for klass in GEN_CLASSES:
        rows = {r["outcome"]: r["c"] for r in conn.execute(
            "SELECT outcome, COUNT(*) c FROM gen_attempts WHERE class=? GROUP BY 1",
            (klass,))}
        total = sum(rows.values())
        checked = rows.get("accepted", 0) + rows.get("suite_caught", 0)
        out[klass] = {
            "attempts": total, **rows,
            "suite_rejection_rate": (rows.get("suite_caught", 0) / checked
                                     if checked else None),
        }
    return out
