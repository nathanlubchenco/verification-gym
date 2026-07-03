"""Review payloads: exactly what the verifier sees, nothing else (HANDOFF §3, §6).

A payload is {description, unified diff, post-change contents of touched files}.
Ground truth never enters this module's outputs. The prompt template is
HANDOFF Appendix A, verbatim and fixed.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from . import gitrepo
from .difftools import parse_diff

# Appendix A, verbatim. Placeholders substituted by literal replacement (the
# template contains JSON braces, so str.format is unusable).
PROMPT_TEMPLATE = """You are reviewing a proposed code change before merge.

<pr_description>{description}</pr_description>
<diff>{unified_diff}</diff>
<files>{full_contents_of_touched_files_post_change}</files>

Determine whether this change introduces a defect. Respond with ONLY a JSON
object: {"defect_found": bool, "confidence": 0-100, "locations":
[{"file": str, "start_line": int, "end_line": int}], "class_guess":
str|null, "severity": "low"|"med"|"high"|null, "rationale": str}.
If the change is acceptable, defect_found is false and locations is []."""


@dataclass(frozen=True)
class Payload:
    description: str
    diff: str
    files: dict[str, str]  # new-side path -> post-change content

    def __eq__(self, other):
        return (isinstance(other, Payload)
                and self.description == other.description
                and self.diff == other.diff
                and self.files == other.files)


def payload_from_commit(repo_dir: Path, sha: str, message: str) -> Payload:
    """Payload for a real commit: its diff + post-change touched files."""
    diff = gitrepo.commit_diff(repo_dir, sha)
    touched = sorted(parse_diff(diff))  # new-side paths; deletions excluded
    files = {}
    for path in touched:
        if gitrepo.file_exists_at(repo_dir, sha, path):
            files[path] = gitrepo.file_at(repo_dir, sha, path)
    return Payload(description=message.strip(), diff=diff, files=files)


def render_files_block(files: dict[str, str]) -> str:
    parts = []
    for path in sorted(files):
        parts.append(f"===== {path} =====\n{files[path]}")
    return "\n".join(parts)


def render_prompt(p: Payload) -> str:
    return (PROMPT_TEMPLATE
            .replace("{description}", p.description)
            .replace("{unified_diff}", p.diff)
            .replace("{full_contents_of_touched_files_post_change}",
                     render_files_block(p.files)))


def payload_chars(p: Payload) -> int:
    return len(render_prompt(p))


def save_payload(payload_dir: Path, item_id: str, p: Payload) -> Path:
    payload_dir.mkdir(parents=True, exist_ok=True)
    path = payload_dir / f"{item_id}.json"
    path.write_text(json.dumps(
        {"description": p.description, "diff": p.diff, "files": p.files},
        ensure_ascii=False, sort_keys=True,
    ))
    return path


def load_payload(path: Path) -> Payload:
    d = json.loads(Path(path).read_text())
    return Payload(description=d["description"], diff=d["diff"], files=d["files"])
