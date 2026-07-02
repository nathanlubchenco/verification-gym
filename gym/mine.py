"""Mining of presumed-clean mainline commits (HANDOFF §5 Arm 0; DECISIONS D5, D13).

A commit qualifies for the pool iff:
  - old enough that the 6-month "no later fix" window is fully observable
    (and old history is preferred anyway, §5);
  - touches at least one .py file, at most MAX_FILES files, is not docs-only,
    is not itself a revert, and is not reverted later;
  - within the 6-month window after it, no fix-flavored commit modifies
    overlapping lines of any file it touched (hunk overlap with slop, D13);
  - its diff is not enormous (hard line cap; the payload char budget is
    enforced again at payload-build time, A7).
"""

from __future__ import annotations

import random
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import gitrepo
from .difftools import changed_new_ranges, parse_diff, ranges_overlap

FIX_RE = re.compile(
    r"\bfix(e[sd])?\b|\bbug(fix)?\b|\bregression\b|\bcrash\b|\bsecurity\b"
    r"|\bcve-\d{4}\b|\bfault\b|\bbroken\b|clos(es?|ed) #\d+|fixes #\d+",
    re.IGNORECASE,
)
REVERT_RE = re.compile(r"\brevert(s|ed)?\b", re.IGNORECASE)

WINDOW_DAYS = 183          # "within 6 months of merge"
MIN_AGE_DAYS = 365         # old history so the window is observable (§5)
MAX_FILES = 6
MAX_CHANGED_LINES = 300
OVERLAP_SLOP = 3           # D13


@dataclass
class Candidate:
    sha: str
    subject: str
    body: str
    files: list[str]
    date: datetime


def _cheap_eligible(c: gitrepo.Commit, cutoff: datetime) -> bool:
    if c.date > cutoff:
        return False
    if REVERT_RE.search(c.subject):
        return False
    py_files = [f for f in c.files if f.endswith(".py")]
    if not py_files or len(c.files) > MAX_FILES:
        return False
    return True


def _diff_line_count(diff: str) -> int:
    return sum(1 for ln in diff.splitlines()
               if (ln.startswith("+") or ln.startswith("-"))
               and not ln.startswith(("+++", "---")))


def _reverted_later(c: gitrepo.Commit, later: list[gitrepo.Commit]) -> bool:
    short = c.sha[:7]
    for l in later:
        if REVERT_RE.search(l.subject) or REVERT_RE.search(l.body):
            if c.sha in l.body or short in l.body or f'"{c.subject}"' in l.subject:
                return True
    return False


def _later_fix_overlaps(repo_dir: Path, c: gitrepo.Commit,
                        later_in_window: list[gitrepo.Commit]) -> bool:
    c_ranges = changed_new_ranges(gitrepo.commit_diff(repo_dir, c.sha))
    c_files = set(c_ranges)
    for l in later_in_window:
        if not (FIX_RE.search(l.subject) or FIX_RE.search(l.body)):
            continue
        if not (set(l.files) & c_files):
            continue
        l_hunks = parse_diff(gitrepo.commit_diff(repo_dir, l.sha))
        for path, hunks in l_hunks.items():
            if path not in c_ranges:
                continue
            l_old = [(h.old_start, h.old_start + max(h.old_len - 1, 0)) for h in hunks]
            if ranges_overlap(c_ranges[path], l_old, slop=OVERLAP_SLOP):
                return True
    return False


def mine_clean_pool(repo_dir: Path, *, quota: int, rng: random.Random,
                    now: datetime | None = None) -> list[Candidate]:
    """Return up to `quota` presumed-clean commits, seeded order, filters applied."""
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=MIN_AGE_DAYS)
    commits = gitrepo.log_commits(repo_dir, no_merges=True)  # newest first

    cheap = [c for c in commits if _cheap_eligible(c, cutoff)]
    rng.shuffle(cheap)

    # newest-first index for window scans
    by_date = sorted(commits, key=lambda c: c.date)
    pool: list[Candidate] = []
    for c in cheap:
        if len(pool) >= quota:
            break
        window_end = c.date + timedelta(days=WINDOW_DAYS)
        later = [l for l in by_date if c.date < l.date]
        later_in_window = [l for l in later if l.date <= window_end]
        if _reverted_later(c, later):
            continue
        diff = gitrepo.commit_diff(repo_dir, c.sha)
        if _diff_line_count(diff) > MAX_CHANGED_LINES:
            continue
        if _later_fix_overlaps(repo_dir, c, later_in_window):
            continue
        pool.append(Candidate(sha=c.sha, subject=c.subject, body=c.body,
                              files=c.files, date=c.date))
    return pool
