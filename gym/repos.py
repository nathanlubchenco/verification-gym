"""`gym repos`: clone, pin, validate target repos per HANDOFF §8.

Criteria: python, permissive license, 5k-100k LOC, pytest green in <5 min,
>=3 years history. Results recorded in db + returned for logging.
"""

from __future__ import annotations

import re
import subprocess
import time
import tomllib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from . import gitrepo
from .config import Config, RepoSpec

PERMISSIVE = re.compile(r"\b(MIT|BSD|Apache)\b", re.IGNORECASE)
TEST_TIMEOUT_S = 300
LOC_MIN, LOC_MAX = 5_000, 100_000
MIN_HISTORY_YEARS = 3.0


@dataclass
class Validation:
    name: str
    passed: bool
    commit: str = ""
    loc: int = 0
    license: str = ""
    history_years: float = 0.0
    tests_passed: bool = False
    test_seconds: float = 0.0
    notes: str = ""


def count_loc(repo_dir: Path) -> int:
    """Non-blank lines across all .py files, excluding test dirs/files and docs."""
    total = 0
    for p in repo_dir.rglob("*.py"):
        rel = p.relative_to(repo_dir)
        parts = {q.lower() for q in rel.parts}
        if parts & {"tests", "test", "docs", "examples", ".git"}:
            continue
        if rel.name.startswith("test_"):
            continue
        try:
            total += sum(1 for ln in p.read_text(errors="replace").splitlines() if ln.strip())
        except OSError:
            continue
    return total


def _load_pyproject(repo_dir: Path) -> dict:
    pp = repo_dir / "pyproject.toml"
    if not pp.exists():
        return {}
    try:
        return tomllib.loads(pp.read_text(errors="replace"))
    except tomllib.TOMLDecodeError:
        return {}


def check_license(repo_dir: Path) -> str:
    """Return matched permissive license name, or '' if none found.

    Checks pyproject SPDX declaration first, then license-file contents —
    BSD/MIT bodies often never name themselves, so match canonical clauses.
    """
    lic = _load_pyproject(repo_dir).get("project", {}).get("license")
    lic_text = lic if isinstance(lic, str) else (lic or {}).get("text", "")
    m = PERMISSIVE.search(lic_text or "")
    if m:
        return m.group(1).upper()
    for name in ("LICENSE", "LICENSE.txt", "LICENSE.md", "LICENSE.rst", "COPYING",
                 "LICENSE.APACHE", "LICENSE.BSD", "LICENSE.MIT"):
        p = repo_dir / name
        if not p.exists():
            continue
        head = p.read_text(errors="replace")[:2500]
        if "Apache License" in head:
            return "APACHE"
        if "Permission is hereby granted, free of charge" in head:
            return "MIT"
        if "Redistribution and use in source and binary forms" in head:
            return "BSD"
        m = PERMISSIVE.search(head)
        if m:
            return m.group(1).upper()
    return ""


def _test_install_targets(repo_dir: Path) -> list[str]:
    """uv pip install args for the package + its test deps: prefer a declared
    test extra, then a PEP 735 dependency group, then requirements files."""
    data = _load_pyproject(repo_dir)
    extras = data.get("project", {}).get("optional-dependencies", {})
    groups = data.get("dependency-groups", {})
    candidates = ("tests", "test", "testing", "dev")
    args = ["."]
    for c in candidates:
        if c in extras:
            args = [f".[{c}]"]
            break
    else:
        for c in candidates:
            if c in groups:
                args = [".", "--group", c]
                break
    for rp in ("requirements/tests.txt", "requirements-dev.txt", "requirements/dev.txt",
               "requirements.txt"):
        if (repo_dir / rp).exists():
            args += ["-r", rp]
            break
    # Only force our own pytest when nothing else will provide (and pin) one.
    if args == ["."]:
        args.append("pytest")
    return args


def run_test_suite(repo_dir: Path, venv_dir: Path, timeout_s: int = TEST_TIMEOUT_S) -> tuple[bool, float, str]:
    """Create isolated venv, install package + test deps, run pytest. Returns
    (passed, seconds, note). Skips are fine; failures/errors are not (A8)."""
    # Pin venvs to 3.12: candidate suites and their pinned plugins predate 3.14.
    subprocess.run(
        ["uv", "venv", "--quiet", "--clear", "-p", "3.12", str(venv_dir)],
        check=True, capture_output=True,
    )
    py = venv_dir / "bin" / "python"
    install = subprocess.run(
        ["uv", "pip", "install", "--quiet", "--python", str(py),
         *_test_install_targets(repo_dir)],
        cwd=repo_dir, capture_output=True, text=True,
    )
    if install.returncode == 0:
        # ensure a pytest exists without overriding a pinned one
        has_pytest = subprocess.run(
            [str(py), "-c", "import pytest"], capture_output=True
        ).returncode == 0
        if not has_pytest:
            install = subprocess.run(
                ["uv", "pip", "install", "--quiet", "--python", str(py), "pytest"],
                cwd=repo_dir, capture_output=True, text=True,
            )
    if install.returncode != 0:
        return False, 0.0, f"install failed: {install.stderr[-400:]}"
    start = time.monotonic()
    try:
        proc = subprocess.run(
            [str(py), "-m", "pytest", "-q", "-x", "-p", "no:cacheprovider"],
            cwd=repo_dir, capture_output=True, text=True, timeout=timeout_s,
        )
    except subprocess.TimeoutExpired:
        return False, time.monotonic() - start, f"pytest exceeded {timeout_s}s"
    secs = time.monotonic() - start
    if proc.returncode != 0:
        tail = (proc.stdout + proc.stderr)[-400:]
        return False, secs, f"pytest exit {proc.returncode}: {tail}"
    return True, secs, proc.stdout.strip().splitlines()[-1] if proc.stdout else "ok"


def validate_repo(cfg: Config, spec: RepoSpec) -> Validation:
    dest = cfg.root / cfg.data_dir / "repos" / spec.name
    v = Validation(name=spec.name, passed=False)
    try:
        if not dest.exists():
            gitrepo.clone(spec.url, dest)
        if spec.pin:
            gitrepo.run_git(dest, "checkout", "--quiet", spec.pin)
        v.commit = gitrepo.head_sha(dest)
        v.loc = count_loc(dest)
        v.license = check_license(dest)
        age = datetime.now(timezone.utc) - gitrepo.first_commit_date(dest)
        v.history_years = age.days / 365.25
        checks = []
        if not (LOC_MIN <= v.loc <= LOC_MAX):
            checks.append(f"LOC {v.loc} outside [{LOC_MIN},{LOC_MAX}]")
        if not v.license:
            checks.append("no permissive license found")
        if v.history_years < MIN_HISTORY_YEARS:
            checks.append(f"history {v.history_years:.1f}y < {MIN_HISTORY_YEARS}y")
        if checks:
            v.notes = "; ".join(checks)
            return v
        venv_dir = cfg.root / cfg.data_dir / "venvs" / spec.name
        v.tests_passed, v.test_seconds, note = run_test_suite(dest, venv_dir)
        v.notes = note
        v.passed = v.tests_passed
        return v
    except Exception as exc:  # validation must never crash the run; record and move on
        v.notes = f"error: {exc}"
        return v


def record_validation(conn, spec: RepoSpec, v: Validation) -> None:
    conn.execute(
        """INSERT OR REPLACE INTO repos
           (name, url, commit_sha, loc, license, history_years, tests_passed,
            test_seconds, validated, notes, validated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?, datetime('now'))""",
        (spec.name, spec.url, v.commit, v.loc, v.license, v.history_years,
         int(v.tests_passed), v.test_seconds, int(v.passed), v.notes),
    )
    conn.commit()
