"""Inject a defect into a real carrier commit (DECISIONS D6).

The review item presents one change: parent(carrier) -> carrier-with-defect.
The diff is produced by git in a temporary worktree so defective items are
byte-format-identical to CLEAN items (no shape leak, HANDOFF §5 blindness).

Ground truth = the changed lines of the defect-only diff (carrier -> edited),
which are already in presented post-change coordinates (DECISIONS D9; the ±2
slop is applied at scoring time).
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from . import gitrepo
from .difftools import changed_new_ranges, parse_diff


class InjectionError(RuntimeError):
    pass


@dataclass(frozen=True)
class Edit:
    path: str
    old: str
    new: str


@dataclass
class InjectedChange:
    presented_diff: str                       # parent -> carrier+defect
    defect_diff: str                          # carrier -> carrier+defect
    gt_locations: dict[str, list[tuple[int, int]]]  # post-change coords
    post_files: dict[str, str]                # touched files, post-change
    carrier_sha: str = ""
    edits: list[Edit] = field(default_factory=list)


def build_injected_change(repo_dir: Path, carrier_sha: str,
                          edits: list[Edit]) -> InjectedChange:
    if not edits:
        raise InjectionError("no edits supplied")
    # root commits have no parent to diff against; callers must skip them
    parents = gitrepo.run_git(repo_dir, "rev-list", "--parents", "-n", "1",
                              carrier_sha).split()
    if len(parents) < 2:
        raise InjectionError(f"carrier {carrier_sha[:8]} has no parent")

    with tempfile.TemporaryDirectory(prefix="vgwt-") as td:
        wt = Path(td) / "wt"
        gitrepo.run_git(repo_dir, "worktree", "add", "--quiet", "--detach",
                        str(wt), carrier_sha)
        try:
            for e in edits:
                target = wt / e.path
                if not target.exists():
                    raise InjectionError(f"{e.path} not present at carrier")
                text = target.read_text()
                n = text.count(e.old)
                if n != 1:
                    raise InjectionError(
                        f"edit target occurs {n} times in {e.path} (need exactly 1)")
                target.write_text(text.replace(e.old, e.new, 1))

            defect_diff = gitrepo.run_git(wt, "diff", "--no-color")
            presented_diff = gitrepo.run_git(wt, "diff", "--no-color",
                                             f"{carrier_sha}^")
            gt = changed_new_ranges(defect_diff)
            post_files = {}
            for path in sorted(parse_diff(presented_diff)):
                fp = wt / path
                if fp.exists():
                    post_files[path] = fp.read_text()
        finally:
            gitrepo.run_git(repo_dir, "worktree", "remove", "--force", str(wt))
    return InjectedChange(presented_diff=presented_diff, defect_diff=defect_diff,
                          gt_locations=gt, post_files=post_files,
                          carrier_sha=carrier_sha, edits=list(edits))
