"""SQLite storage. Ground truth (defect_records) is never written into payload
files; the verifier-visible world is payloads only (HANDOFF §3)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS repos (
    name TEXT PRIMARY KEY,
    url TEXT NOT NULL,
    commit_sha TEXT,
    loc INTEGER,
    license TEXT,
    history_years REAL,
    tests_passed INTEGER,
    test_seconds REAL,
    validated INTEGER NOT NULL DEFAULT 0,
    notes TEXT,
    validated_at TEXT
);
CREATE TABLE IF NOT EXISTS commit_pool (
    repo TEXT NOT NULL,
    sha TEXT NOT NULL,
    subject TEXT,
    body TEXT,
    files_json TEXT,
    commit_date TEXT,
    assigned_to TEXT,            -- CLEAN | MUT_CARRIER | GEN_CARRIER | CANARY_CARRIER | NULL
    PRIMARY KEY (repo, sha)
);
CREATE TABLE IF NOT EXISTS defect_records (
    defect_id TEXT PRIMARY KEY,
    arm TEXT NOT NULL,           -- MUT | GEN | SZZ | CANARY
    class TEXT NOT NULL,
    repo TEXT NOT NULL,
    injection_method TEXT NOT NULL,
    carrier_sha TEXT,
    ground_truth_diff TEXT NOT NULL,
    ground_truth_locations TEXT NOT NULL,  -- json [{file,start_line,end_line}]
    provenance TEXT NOT NULL,              -- json
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS review_items (
    item_id TEXT PRIMARY KEY,
    defect_id TEXT,              -- NULL for clean items
    repo TEXT NOT NULL,
    payload_path TEXT NOT NULL,
    defective INTEGER NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS verdicts (
    item_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    raw_response TEXT,
    verdict_json TEXT,           -- NULL => abstained
    abstained INTEGER NOT NULL DEFAULT 0,
    tokens_in INTEGER, tokens_out INTEGER,
    latency_ms INTEGER, cost_usd REAL,
    prompt_hash TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (item_id, run_id)
);
CREATE TABLE IF NOT EXISTS llm_cache (
    cache_key TEXT PRIMARY KEY,  -- model|prompt_hash|seed
    model TEXT NOT NULL,
    prompt_hash TEXT NOT NULL,
    seed INTEGER NOT NULL,
    response_text TEXT NOT NULL,
    tokens_in INTEGER, tokens_out INTEGER,
    latency_ms INTEGER, cost_usd REAL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS gen_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    class TEXT NOT NULL,
    repo TEXT NOT NULL,
    sha TEXT NOT NULL,
    outcome TEXT NOT NULL,       -- accepted | suite_caught | parse_failure |
                                 -- anchor_failure | invalid_edit | oversized_payload
    note TEXT,
    ts TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS carrier_baselines (
    repo TEXT NOT NULL,
    sha TEXT NOT NULL,
    ok INTEGER,                  -- 1 pass, 0 fail/timeout (suite infeasible at carrier)
    seconds REAL,
    note TEXT,
    PRIMARY KEY (repo, sha)
);
CREATE TABLE IF NOT EXISTS spend_ledger (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL DEFAULT (datetime('now')),
    model TEXT NOT NULL,
    purpose TEXT NOT NULL,
    tokens_in INTEGER, tokens_out INTEGER,
    cost_usd REAL NOT NULL
);
"""


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    conn.executescript(SCHEMA)
    return conn


def spend_total(conn: sqlite3.Connection) -> float:
    row = conn.execute("SELECT COALESCE(SUM(cost_usd), 0) AS t FROM spend_ledger").fetchone()
    return float(row["t"])
