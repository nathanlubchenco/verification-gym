"""Unified diff parsing: hunk headers and changed-line ranges.

Used for (a) the CLEAN-arm later-fix overlap filter (DECISIONS D13) and
(b) ground-truth defect locations in post-change coordinates (DECISIONS D9).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
FILE_RE = re.compile(r"^diff --git a/(.*) b/(.*)$")


@dataclass(frozen=True)
class Hunk:
    old_start: int
    old_len: int
    new_start: int
    new_len: int


def parse_diff(diff_text: str) -> dict[str, list[Hunk]]:
    """Map new-side path -> hunks. Renames keyed by the b/ path; /dev/null skipped."""
    result: dict[str, list[Hunk]] = {}
    current: str | None = None
    for line in diff_text.splitlines():
        m = FILE_RE.match(line)
        if m:
            current = m.group(2)
            result.setdefault(current, [])
            continue
        if line.startswith("+++ "):
            path = line[4:].strip()
            if path == "/dev/null":
                current = None
            elif path.startswith("b/"):
                current = path[2:]
                result.setdefault(current, [])
            continue
        m = HUNK_RE.match(line)
        if m and current is not None:
            result[current].append(Hunk(
                old_start=int(m.group(1)), old_len=int(m.group(2) or 1),
                new_start=int(m.group(3)), new_len=int(m.group(4) or 1),
            ))
    return {p: hs for p, hs in result.items() if hs}


def changed_new_ranges(diff_text: str) -> dict[str, list[tuple[int, int]]]:
    """Per new-side file: (start,end) line ranges of added/modified lines, in
    post-change coordinates. Contiguous changed lines are merged into one range."""
    result: dict[str, list[tuple[int, int]]] = {}
    current: str | None = None
    new_line = 0
    run_start: int | None = None

    def close_run():
        nonlocal run_start
        if current is not None and run_start is not None:
            result.setdefault(current, []).append((run_start, new_line - 1))
        run_start = None

    for line in diff_text.splitlines():
        if line.startswith("+++ "):
            close_run()
            path = line[4:].strip()
            current = None if path == "/dev/null" else path.removeprefix("b/")
            continue
        m = HUNK_RE.match(line)
        if m:
            close_run()
            new_line = int(m.group(3))
            continue
        if current is None:
            continue
        if line.startswith("+") and not line.startswith("+++"):
            if run_start is None:
                run_start = new_line
            new_line += 1
        elif line.startswith("-") and not line.startswith("---"):
            continue  # deletion: no new-side line consumed
        elif line.startswith((" ", "\\")):
            close_run()
            if line.startswith(" "):
                new_line += 1
        else:
            close_run()
    close_run()
    return result


def ranges_overlap(a: list[tuple[int, int]], b: list[tuple[int, int]],
                   slop: int = 0) -> bool:
    for s1, e1 in a:
        for s2, e2 in b:
            if s1 - slop <= e2 and s2 - slop <= e1:
                return True
    return False
