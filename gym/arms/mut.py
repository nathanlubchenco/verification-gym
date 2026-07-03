"""Arm 1 — MUT: deterministic, seeded mutation operators (HANDOFF §5).

MUT-01 boundary/off-by-one   (< <-> <=, > <-> >=)
MUT-02 logic operator swap   (and <-> or, == <-> !=, dropped negation)
MUT-03 same-type arg swap    (f(a, b) -> f(b, a), bare-name args)
MUT-04 error-handling swallow (raise under except -> pass)
MUT-05 default/config change (numeric/bool default in def signature, x10/flip)

Guards: the edit anchor (full line) must be unique in the file; the mutated
file must still parse; the AST must actually differ (rejects mutations that
landed inside strings/comments — "equivalent mutant" trap).
"""

from __future__ import annotations

import ast
import io
import json
import random
import re
import sqlite3
import tokenize

from .. import gitrepo
from ..config import Config
from ..inject import Edit, InjectionError, build_injected_change
from ..payload import Payload

MUT_CLASSES = ["MUT-01", "MUT-02", "MUT-03", "MUT-04", "MUT-05"]


def _mut01(line: str, prev: str) -> list[str]:
    out = []
    if " < " in line:
        out.append(line.replace(" < ", " <= ", 1))
    if " <= " in line:
        out.append(line.replace(" <= ", " < ", 1))
    if " > " in line:
        out.append(line.replace(" > ", " >= ", 1))
    if " >= " in line:
        out.append(line.replace(" >= ", " > ", 1))
    return out


def _mut02(line: str, prev: str) -> list[str]:
    out = []
    if " and " in line:
        out.append(line.replace(" and ", " or ", 1))
    if " or " in line:
        out.append(line.replace(" or ", " and ", 1))
    if " == " in line:
        out.append(line.replace(" == ", " != ", 1))
    if " != " in line:
        out.append(line.replace(" != ", " == ", 1))
    m = re.match(r"^(\s*(?:if|while|elif) )not (.+)$", line)
    if m:
        out.append(f"{m.group(1)}{m.group(2)}")
    return out


_CALL2 = re.compile(r"\b([A-Za-z_]\w*)\(([a-z_]\w*), ([a-z_]\w*)\)")


def _mut03(line: str, prev: str) -> list[str]:
    m = _CALL2.search(line)
    if not m or m.group(2) == m.group(3):
        return []
    swapped = f"{m.group(1)}({m.group(3)}, {m.group(2)})"
    return [line[:m.start()] + swapped + line[m.end():]]


def _mut04(line: str, prev: str) -> list[str]:
    if re.match(r"^\s*raise\b", line) and re.match(r"^\s*except\b.*:\s*(#.*)?$", prev):
        indent = re.match(r"^\s*", line).group(0)
        return [f"{indent}pass"]
    return []


_DEF_NUM = re.compile(r"=(\d+)([,)])")


def _mut05(line: str, prev: str) -> list[str]:
    if not re.match(r"^\s*(async )?def \w+\(", line):
        return []
    out = []
    m = _DEF_NUM.search(line)
    if m:
        out.append(line[:m.start()] + f"={int(m.group(1)) * 10}{m.group(2)}" + line[m.end():])
    if "=True" in line:
        out.append(line.replace("=True", "=False", 1))
    elif "=False" in line:
        out.append(line.replace("=False", "=True", 1))
    return out


OPS = {"MUT-01": _mut01, "MUT-02": _mut02, "MUT-03": _mut03,
       "MUT-04": _mut04, "MUT-05": _mut05}


_STRING_TOKENS = {tokenize.STRING}
for _name in ("FSTRING_START", "FSTRING_MIDDLE", "FSTRING_END"):
    if hasattr(tokenize, _name):
        _STRING_TOKENS.add(getattr(tokenize, _name))


def _string_spans(text: str) -> list[tuple[tuple[int, int], tuple[int, int]]]:
    spans = []
    try:
        for tok in tokenize.generate_tokens(io.StringIO(text).readline):
            if tok.type in _STRING_TOKENS:
                spans.append((tok.start, tok.end))
    except (tokenize.TokenError, IndentationError, SyntaxError):
        pass
    return spans


def _in_string(spans, lineno: int, col: int) -> bool:
    return any((srow, scol) <= (lineno, col) < (erow, ecol)
               for (srow, scol), (erow, ecol) in spans)


def _sane_mutation(text: str, old_line: str, new_line: str, lineno: int,
                   spans) -> bool:
    """Mutated file must parse, AST must differ (rejects comment edits), and
    the changed char must not sit inside a string literal (rejects no-ops)."""
    col = next((i for i, (a, b) in enumerate(zip(old_line, new_line)) if a != b),
               min(len(old_line), len(new_line)))
    if _in_string(spans, lineno, col):
        return False
    mutated = text.replace(old_line, new_line, 1)
    try:
        a1 = ast.parse(text)
        a2 = ast.parse(mutated)
    except SyntaxError:
        return False
    return ast.dump(a1) != ast.dump(a2)


def find_sites(path: str, text: str) -> dict[str, list[Edit]]:
    """Per MUT class: applicable single-line edits with unique anchors."""
    lines = text.split("\n")
    sites: dict[str, list[Edit]] = {k: [] for k in MUT_CLASSES}
    spans = _string_spans(text)
    prev = ""
    for lineno, line in enumerate(lines, start=1):
        stripped = line.strip()
        if not stripped:
            continue
        if not stripped.startswith("#") and text.count(line) == 1:
            for klass, op in OPS.items():
                for new_line in op(line, prev):
                    if new_line != line and _sane_mutation(text, line, new_line,
                                                           lineno, spans):
                        sites[klass].append(Edit(path=path, old=line, new=new_line))
        prev = line
    return sites


def generate_mut(cfg: Config, conn: sqlite3.Connection, n_per_class: int,
                 progress=print) -> dict[str, int]:
    from ..generate import _carriers, add_defect_record, add_review_item

    rng = random.Random(f"{cfg.seed}:mut")
    made = {k: 0 for k in MUT_CLASSES}
    for row in conn.execute(
            "SELECT d.class k, COUNT(*) c FROM defect_records d JOIN review_items i"
            " ON i.defect_id=d.defect_id WHERE d.arm='MUT' GROUP BY 1"):
        made[row["k"]] = row["c"]

    for carrier in _carriers(conn, "MUT_CARRIER"):
        need = [k for k in MUT_CLASSES if made[k] < n_per_class]
        if not need:
            break
        repo_dir = cfg.root / cfg.data_dir / "repos" / carrier["repo"]
        py_files = [f for f in json.loads(carrier["files_json"]) if f.endswith(".py")]
        all_sites: dict[str, list[Edit]] = {k: [] for k in MUT_CLASSES}
        for path in py_files:
            if not gitrepo.file_exists_at(repo_dir, carrier["sha"], path):
                continue
            text = gitrepo.file_at(repo_dir, carrier["sha"], path)
            for klass, edits in find_sites(path, text).items():
                all_sites[klass].extend(edits)

        # neediest class first, among classes this carrier can serve
        serveable = sorted((k for k in need if all_sites[k]),
                           key=lambda k: (made[k], k))
        placed = False
        for klass in serveable:
            edits = sorted(all_sites[klass], key=lambda e: (e.path, e.old))
            rng.shuffle(edits)
            for edit in edits:
                try:
                    change = build_injected_change(repo_dir, carrier["sha"], [edit])
                except InjectionError:
                    continue
                msg = f'{carrier["subject"]}\n\n{carrier["body"]}'.strip()
                p = Payload(description=msg, diff=change.presented_diff,
                            files=change.post_files)
                defect_id = add_defect_record(
                    conn, rng, arm="MUT", klass=klass, repo=carrier["repo"],
                    injection_method=f"mut:{klass}", change=change,
                    provenance={"carrier": carrier["sha"],
                                "op": klass, "file": edit.path},
                )
                item_id = add_review_item(cfg, conn, rng, repo=carrier["repo"],
                                          p=p, defective=True, defect_id=defect_id)
                if item_id is None:
                    conn.execute("DELETE FROM defect_records WHERE defect_id=?",
                                 (defect_id,))
                    conn.commit()
                    continue
                made[klass] += 1
                placed = True
                break
            if placed:
                break  # one defect per carrier (exactly one injected defect/item)
    progress(f"mut: totals {made}")
    return made
