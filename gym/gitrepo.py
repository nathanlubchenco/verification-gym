"""Thin git plumbing over subprocess. All reads are by-sha so the working tree
stays pinned; nothing here mutates repo state except clone."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

RECORD_SEP = "\x1e"
FIELD_SEP = "\x1f"


def parse_git_date(s: str) -> datetime:
    """ISO date from git %aI. Git preserves corrupt author timezones (e.g.
    '+518:00' in old requests history); fall back to UTC on bad offsets."""
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        from datetime import timezone

        return datetime.fromisoformat(s[:19]).replace(tzinfo=timezone.utc)


class GitError(RuntimeError):
    pass


def run_git(repo: Path | str, *args: str, check: bool = True) -> str:
    for attempt in range(4):
        proc = subprocess.run(
            ["git", "-C", str(repo), "-c", "core.pager=cat", *args],
            capture_output=True, text=True,
        )
        if proc.returncode == 0:
            return proc.stdout
        # transient lock contention between parallel generator processes
        if "lock" in proc.stderr.lower() and attempt < 3:
            import time

            time.sleep(0.5 * (attempt + 1))
            continue
        break
    if check:
        raise GitError(f"git {' '.join(args)} failed: {proc.stderr.strip()}")
    return proc.stdout


def clone(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        ["git", "clone", "--quiet", url, str(dest)], capture_output=True, text=True
    )
    if proc.returncode != 0:
        raise GitError(f"clone {url} failed: {proc.stderr.strip()}")


def head_sha(repo: Path | str) -> str:
    return run_git(repo, "rev-parse", "HEAD").strip()


@dataclass
class Commit:
    sha: str
    date: datetime
    subject: str
    body: str
    files: list[str]

    @property
    def message(self) -> str:
        return f"{self.subject}\n\n{self.body}".strip()


def log_commits(
    repo: Path | str,
    rev_range: str | None = None,
    *,
    no_merges: bool = False,
    max_count: int | None = None,
    paths: list[str] | None = None,
) -> list[Commit]:
    """Newest-first commits with touched file lists (name-only, vs first parent)."""
    fmt = f"%H{FIELD_SEP}%aI{FIELD_SEP}%s{FIELD_SEP}%b{RECORD_SEP}"
    args = ["log", f"--pretty=format:{fmt}", "--name-only"]
    if no_merges:
        args.append("--no-merges")
    if max_count:
        args.append(f"--max-count={max_count}")
    if rev_range:
        args.append(rev_range)
    if paths:
        args.extend(["--", *paths])
    out = run_git(repo, *args)
    # Output interleaves "<header>\x1e" records with each commit's file list:
    # splitting on \x1e yields [hdr0, files0+hdr1, files1+hdr2, ..., files_last].
    chunks = out.split(RECORD_SEP)
    headers: list[str] = []
    file_blocks: list[str] = []
    for i, chunk in enumerate(chunks):
        if i == 0:
            headers.append(chunk)
            continue
        lines = chunk.split("\n")
        hdr_idx = next((j for j, ln in enumerate(lines) if FIELD_SEP in ln), None)
        if hdr_idx is None:
            file_blocks.append(chunk)
        else:
            file_blocks.append("\n".join(lines[:hdr_idx]))
            headers.append("\n".join(lines[hdr_idx:]))
    while len(file_blocks) < len(headers):
        file_blocks.append("")

    commits = []
    for header, files_blob in zip(headers, file_blocks):
        if FIELD_SEP not in header:
            continue
        sha, date_s, subject, body = header.split(FIELD_SEP, 3)
        files = [ln.strip() for ln in files_blob.splitlines() if ln.strip()]
        commits.append(
            Commit(sha=sha.strip(), date=parse_git_date(date_s),
                   subject=subject, body=body.strip(), files=sorted(files))
        )
    return commits


def commit_diff(repo: Path | str, sha: str) -> str:
    """Unified diff of a commit against its first parent (root: against empty)."""
    return run_git(repo, "show", "--format=", "--no-color", sha)


def file_at(repo: Path | str, sha: str, path: str) -> str:
    return run_git(repo, "show", f"{sha}:{path}")


def file_exists_at(repo: Path | str, sha: str, path: str) -> bool:
    try:
        run_git(repo, "cat-file", "-e", f"{sha}:{path}")
        return True
    except GitError:
        return False


def first_commit_date(repo: Path | str) -> datetime:
    # rev-list --max-parents=0 finds root commit(s); take the oldest.
    roots = run_git(repo, "rev-list", "--max-parents=0", "HEAD").split()
    dates = [
        parse_git_date(run_git(repo, "show", "-s", "--format=%aI", r).strip())
        for r in roots
    ]
    return min(dates)
