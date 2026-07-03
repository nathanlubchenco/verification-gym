"""`gym generate`: build the commit pool, assign it to arms, and create review
items + defect records. Payloads are written to data/payloads/, ground truth
only to SQLite (HANDOFF §3/§4.2).
"""

from __future__ import annotations

import json
import random
import sqlite3
from dataclasses import dataclass

from . import gitrepo, mine
from .arms.canary import find_canary_edit
from .config import Config
from .difftools import parse_diff
from .ids import make_id
from .inject import InjectedChange, InjectionError, build_injected_change
from .payload import Payload, payload_chars, payload_from_commit, save_payload

MUT_CLASSES = ["MUT-01", "MUT-02", "MUT-03", "MUT-04", "MUT-05"]
GEN_CLASSES = ["GEN-01", "GEN-02", "GEN-03", "GEN-04", "GEN-05", "GEN-06"]
SZZ_ESTIMATE = 100          # planning constant for the clean-count arithmetic
POOL_SLACK = 1.35           # extra pool to absorb payload-budget/site rejections
CANARY_TARGET = 24          # >=20 required (§14.1)


@dataclass
class Needs:
    clean: int
    mut_carriers: int
    gen_carriers: int
    canary_carriers: int


def compute_needs(cfg: Config) -> Needs:
    n = cfg.targets.n_per_class
    defective = len(MUT_CLASSES) * n + len(GEN_CLASSES) * n + SZZ_ESTIMATE
    f = cfg.targets.clean_fraction
    clean = round(defective * f / (1 - f))
    return Needs(
        clean=clean,
        mut_carriers=int(len(MUT_CLASSES) * n * POOL_SLACK),
        gen_carriers=int(len(GEN_CLASSES) * n * POOL_SLACK),
        canary_carriers=int(CANARY_TARGET * 1.5),
    )


def validated_repos(conn: sqlite3.Connection) -> list[str]:
    return [r["name"] for r in
            conn.execute("SELECT name FROM repos WHERE validated=1 ORDER BY name")]


def ensure_pool(cfg: Config, conn: sqlite3.Connection, quota_per_repo: int,
                progress=print) -> int:
    total = 0
    for name in validated_repos(conn):
        have = conn.execute("SELECT COUNT(*) c FROM commit_pool WHERE repo=?",
                            (name,)).fetchone()["c"]
        if have < quota_per_repo:
            repo_dir = cfg.root / cfg.data_dir / "repos" / name
            rng = random.Random(f"{cfg.seed}:mine:{name}")
            progress(f"mining {name} (have {have}, want {quota_per_repo}) ...")
            pool = mine.mine_clean_pool(repo_dir, quota=quota_per_repo, rng=rng)
            for c in pool:
                conn.execute(
                    "INSERT OR IGNORE INTO commit_pool"
                    " (repo, sha, subject, body, files_json, commit_date)"
                    " VALUES (?,?,?,?,?,?)",
                    (name, c.sha, c.subject, c.body, json.dumps(c.files),
                     c.date.isoformat()),
                )
            conn.commit()
        total += conn.execute("SELECT COUNT(*) c FROM commit_pool WHERE repo=?",
                              (name,)).fetchone()["c"]
    return total


def assign_pool(cfg: Config, conn: sqlite3.Connection) -> dict[str, int]:
    """Seeded disjoint assignment of pool commits to arms (D6: carriers and
    clean items come from the same distribution). Idempotent: only assigns
    currently-unassigned rows, honoring global category shortfalls."""
    needs = compute_needs(cfg)
    want = {
        "CLEAN": int(needs.clean * 1.15),
        "MUT_CARRIER": needs.mut_carriers,
        "GEN_CARRIER": needs.gen_carriers,
        "CANARY_CARRIER": needs.canary_carriers,
    }
    # used CLEAN commits are re-tagged 'CLEAN_USED:<item>'; they still count
    have = {k: conn.execute(
        "SELECT COUNT(*) c FROM commit_pool WHERE assigned_to=? OR assigned_to LIKE ?",
        (k, f"{k}_USED:%"),
    ).fetchone()["c"] for k in want}
    rows = conn.execute(
        "SELECT repo, sha FROM commit_pool WHERE assigned_to IS NULL"
        " ORDER BY repo, sha").fetchall()
    rng = random.Random(f"{cfg.seed}:assign")
    rows = list(rows)
    rng.shuffle(rows)
    i = 0
    for cat in ("CLEAN", "MUT_CARRIER", "GEN_CARRIER", "CANARY_CARRIER"):
        while have[cat] < want[cat] and i < len(rows):
            conn.execute("UPDATE commit_pool SET assigned_to=? WHERE repo=? AND sha=?",
                         (cat, rows[i]["repo"], rows[i]["sha"]))
            have[cat] += 1
            i += 1
    conn.commit()
    return have


def _unique_id(conn: sqlite3.Connection, prefix: str, rng: random.Random,
               table: str, col: str) -> str:
    while True:
        candidate = make_id(prefix, rng)
        hit = conn.execute(f"SELECT 1 FROM {table} WHERE {col}=?", (candidate,)).fetchone()
        if not hit:
            return candidate


def _payload_dir(cfg: Config):
    return cfg.root / cfg.data_dir / "payloads"


def add_review_item(cfg: Config, conn: sqlite3.Connection, rng: random.Random, *,
                    repo: str, p: Payload, defective: bool,
                    defect_id: str | None) -> str | None:
    """Persist payload + review_item if within budget; returns item_id or None."""
    if payload_chars(p) > cfg.payload_budget_chars:
        return None
    item_id = _unique_id(conn, "it", rng, "review_items", "item_id")
    path = save_payload(_payload_dir(cfg), item_id, p)
    conn.execute(
        "INSERT INTO review_items (item_id, defect_id, repo, payload_path, defective)"
        " VALUES (?,?,?,?,?)",
        (item_id, defect_id, repo, str(path.relative_to(cfg.root)), int(defective)),
    )
    conn.commit()
    return item_id


def add_defect_record(conn: sqlite3.Connection, rng: random.Random, *, arm: str,
                      klass: str, repo: str, injection_method: str,
                      change: InjectedChange, provenance: dict) -> str:
    defect_id = _unique_id(conn, "d", rng, "defect_records", "defect_id")
    gt = [{"file": f, "start_line": s, "end_line": e}
          for f, ranges in sorted(change.gt_locations.items()) for s, e in ranges]
    conn.execute(
        "INSERT INTO defect_records (defect_id, arm, class, repo, injection_method,"
        " carrier_sha, ground_truth_diff, ground_truth_locations, provenance)"
        " VALUES (?,?,?,?,?,?,?,?,?)",
        (defect_id, arm, klass, repo, injection_method, change.carrier_sha,
         change.defect_diff, json.dumps(gt), json.dumps(provenance, sort_keys=True)),
    )
    conn.commit()
    return defect_id


def _carriers(conn: sqlite3.Connection, category: str) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT p.* FROM commit_pool p WHERE p.assigned_to=? AND NOT EXISTS"
        " (SELECT 1 FROM defect_records d WHERE d.carrier_sha=p.sha AND d.repo=p.repo)"
        " ORDER BY p.repo, p.sha",
        (category,),
    ).fetchall()


def _existing_count(conn, arm: str) -> int:
    return conn.execute(
        "SELECT COUNT(*) c FROM defect_records d JOIN review_items i"
        " ON i.defect_id = d.defect_id WHERE d.arm=?", (arm,)
    ).fetchone()["c"]


def generate_clean(cfg: Config, conn: sqlite3.Connection, n: int,
                   progress=print) -> int:
    rng = random.Random(f"{cfg.seed}:clean")
    have = conn.execute(
        "SELECT COUNT(*) c FROM review_items WHERE defective=0").fetchone()["c"]
    made = 0
    used_shas = _used_clean_shas(conn)
    rows = conn.execute(
        "SELECT * FROM commit_pool WHERE assigned_to='CLEAN' ORDER BY repo, sha"
    ).fetchall()
    rows = list(rows)
    random.Random(f"{cfg.seed}:cleanorder").shuffle(rows)
    for row in rows:
        if have + made >= n:
            break
        if (row["repo"], row["sha"]) in used_shas:
            continue
        repo_dir = cfg.root / cfg.data_dir / "repos" / row["repo"]
        msg = f'{row["subject"]}\n\n{row["body"]}'.strip()
        p = payload_from_commit(repo_dir, row["sha"], msg)
        item_id = add_review_item(cfg, conn, rng, repo=row["repo"], p=p,
                                  defective=False, defect_id=None)
        if item_id:
            conn.execute(
                "UPDATE commit_pool SET assigned_to='CLEAN_USED:'||? WHERE repo=? AND sha=?",
                (item_id, row["repo"], row["sha"]))
            conn.commit()
            made += 1
    progress(f"clean: created {made} items (target {n}, prior {have})")
    return made


def _used_clean_shas(conn) -> set[tuple[str, str]]:
    return {
        (r["repo"], r["sha"]) for r in conn.execute(
            "SELECT repo, sha FROM commit_pool WHERE assigned_to LIKE 'CLEAN_USED:%'")
    }


def generate_canaries(cfg: Config, conn: sqlite3.Connection, n: int,
                      progress=print) -> int:
    rng = random.Random(f"{cfg.seed}:canary")
    have = _existing_count(conn, "CANARY")
    made = 0
    for row in _carriers(conn, "CANARY_CARRIER"):
        if have + made >= n:
            break
        repo_dir = cfg.root / cfg.data_dir / "repos" / row["repo"]
        files = [f for f in json.loads(row["files_json"]) if f.endswith(".py")]
        rng.shuffle(files)
        change = None
        op_name = ""
        for path in files:
            if not gitrepo.file_exists_at(repo_dir, row["sha"], path):
                continue
            text = gitrepo.file_at(repo_dir, row["sha"], path)
            found = find_canary_edit(path, text, rng)
            if not found:
                continue
            op_name, edit = found
            try:
                change = build_injected_change(repo_dir, row["sha"], [edit])
                break
            except InjectionError:
                change = None
        if change is None:
            continue
        msg = f'{row["subject"]}\n\n{row["body"]}'.strip()
        p = Payload(description=msg, diff=change.presented_diff,
                    files=change.post_files)
        defect_id = add_defect_record(
            conn, rng, arm="CANARY", klass="CANARY", repo=row["repo"],
            injection_method=f"canary:{op_name}", change=change,
            provenance={"carrier": row["sha"], "op": op_name},
        )
        item_id = add_review_item(cfg, conn, rng, repo=row["repo"], p=p,
                                  defective=True, defect_id=defect_id)
        if item_id is None:
            conn.execute("DELETE FROM defect_records WHERE defect_id=?", (defect_id,))
            conn.commit()
            continue
        made += 1
    progress(f"canary: created {made} items (target {n}, prior {have})")
    return made
