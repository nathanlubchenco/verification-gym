"""Canary defects (HANDOFF §14.1): trivially detectable, blatant breaks with no
justifying context. Used only for the pipeline self-audit gate (detection must
be >=90%); excluded from §7 metrics (DECISIONS D14). Arm/class tag: CANARY.
"""

from __future__ import annotations

import random
import re

from ..inject import Edit

# each op: (name, line_regex, transform(line) -> new_line | None)
_INT_RE = re.compile(r"(?<![\w.])([1-9]\d{0,5})(?![\w.])")


def _invert_if(line: str) -> str | None:
    m = re.match(r"^(\s*)if (?!not\b)(.+):(\s*(#.*)?)$", line)
    if not m or " else" in line:
        return None
    return f"{m.group(1)}if not ({m.group(2)}):{m.group(3) or ''}"


def _return_none(line: str) -> str | None:
    m = re.match(r"^(\s*)return (?!None\b|True\b|False\b)(.+)$", line)
    if not m or m.group(2).strip().startswith(("#",)):
        return None
    return f"{m.group(1)}return None"


def _eq_to_neq(line: str) -> str | None:
    if " == " not in line or "!=" in line:
        return None
    return line.replace(" == ", " != ", 1)


def _big_constant(line: str) -> str | None:
    m = _INT_RE.search(line)
    if not m or line.lstrip().startswith("#"):
        return None
    val = int(m.group(1))
    return line[:m.start(1)] + str(val + 1000) + line[m.end(1):]


# Only genuinely blatant ops qualify as canaries. eq_to_neq/big_constant were
# tried and removed: landing in test files they read as MUT-grade subtlety and
# dragged the §14.1 gate to 87.5% (see WORKLOG 2026-07-03). They remain below
# for reference/tests but are not used for canary generation.
CANARY_OPS = [
    ("invert_if", _invert_if),
    ("return_none", _return_none),
]
RETIRED_OPS = [
    ("eq_to_neq", _eq_to_neq),
    ("big_constant", _big_constant),
]


_NON_SOURCE = re.compile(r"(^|/)(tests?|examples?|docs?)(/|_)|_test\.py$|^test_")


def find_canary_edit(path: str, file_text: str, rng: random.Random) -> tuple[str, Edit] | None:
    """Pick a blatant, uniquely-applicable single-line break, seeded. Returns
    (op_name, Edit) or None if the file offers no usable site. Test/example
    files are excluded: a broken line there is not blatant to a reviewer."""
    if _NON_SOURCE.search(path):
        return None
    lines = file_text.split("\n")
    sites: list[tuple[str, str, str]] = []
    for line in lines:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if file_text.count(line) != 1:
            continue  # edit anchor must be unique in the file
        for op_name, op in CANARY_OPS:
            new_line = op(line)
            if new_line is not None and new_line != line:
                sites.append((op_name, line, new_line))
    if not sites:
        return None
    op_name, old, new = rng.choice(sorted(sites))
    return op_name, Edit(path=path, old=old, new=new)
