"""`gym leakcheck`: zero-tolerance scan of every review payload for
ground-truth contamination (HANDOFF §4.3). Any hit is a hard fail.

Checked per payload (description + diff + file contents):
  - class labels / arm names (MUT-NN, GEN-NN, SZZ, CANARY, standalone CLEAN);
  - tell-tale tooling phrases ("injected defect", "mutation operator",
    "ground truth", "verification gym", "bugsinpy");
  - the id shape used by this harness, and every actual defect/item id in the db.
"""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from .config import Config

PATTERNS: list[tuple[str, re.Pattern]] = [
    ("class label MUT-NN", re.compile(r"\bMUT-\d{2}\b")),
    ("class label GEN-NN", re.compile(r"\bGEN-\d{2}\b")),
    ("arm name SZZ", re.compile(r"\bSZZ\b")),
    ("canary marker", re.compile(r"\bcanar(y|ies)\b", re.IGNORECASE)),
    ("arm name CLEAN (standalone uppercase)", re.compile(r"\bCLEAN\b")),
    ("phrase 'injected defect'", re.compile(r"injected\s+defect", re.IGNORECASE)),
    ("phrase 'defect injection'", re.compile(r"defect\s+injection", re.IGNORECASE)),
    ("phrase 'mutation operator'", re.compile(r"mutation\s+operator", re.IGNORECASE)),
    ("phrase 'ground truth'", re.compile(r"ground.?truth", re.IGNORECASE)),
    ("phrase 'verification gym'", re.compile(r"verification.?gym", re.IGNORECASE)),
    ("bugsinpy marker", re.compile(r"bugsinpy", re.IGNORECASE)),
    ("harness id shape", re.compile(r"\b(?:d|it)-[0-9a-f]{10}\b")),
]


@dataclass
class Violation:
    payload: str
    rule: str
    snippet: str


def _payload_text(path: Path) -> str:
    d = json.loads(path.read_text())
    return "\n".join([d["description"], d["diff"], *d["files"].values()])


def scan_payloads(cfg: Config, conn: sqlite3.Connection) -> list[Violation]:
    ids = [r[0] for r in conn.execute("SELECT defect_id FROM defect_records")]
    ids += [r[0] for r in conn.execute("SELECT item_id FROM review_items")]
    violations: list[Violation] = []
    payload_dir = cfg.root / cfg.data_dir / "payloads"
    files = sorted(payload_dir.glob("*.json")) if payload_dir.exists() else []
    for f in files:
        text = _payload_text(f)
        for rule, pat in PATTERNS:
            m = pat.search(text)
            if m:
                lo = max(0, m.start() - 40)
                violations.append(Violation(f.name, rule, text[lo:m.end() + 40]))
        for known_id in ids:
            if known_id in text:
                violations.append(Violation(f.name, f"known id {known_id}", known_id))
    return violations
