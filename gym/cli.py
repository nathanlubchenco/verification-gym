"""gym CLI: repos | generate | leakcheck | review | score | report | smoke | reproduce."""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import sys
import time

from . import db as dbmod
from .config import Config, load_config

DEFAULT_RUN_ID = "main"


def _open(args) -> tuple[Config, "object"]:
    cfg = load_config(args.config)
    return cfg, dbmod.connect(cfg.db_path)


def cmd_repos(args) -> int:
    from . import repos as reposmod

    cfg, conn = _open(args)
    validated = 0
    for spec in cfg.repos:
        if validated >= args.max_validated:
            print(f"-- reached {args.max_validated} validated repos; skipping rest")
            break
        print(f"validating {spec.name} ...", flush=True)
        v = reposmod.validate_repo(cfg, spec)
        reposmod.record_validation(conn, spec, v)
        status = "PASS" if v.passed else "FAIL"
        print(f"  {status} loc={v.loc} license={v.license} history={v.history_years:.1f}y "
              f"tests={'ok' if v.tests_passed else 'no'} ({v.test_seconds:.0f}s) {v.notes[:200]}")
        validated += int(v.passed)
    print(f"validated {validated} repos")
    return 0 if validated >= 3 else 1


def _generate_into(cfg: Config, conn, arms: list[str], progress=print) -> None:
    from . import generate as gen

    needs = gen.compute_needs(cfg)
    total_want = (int(needs.clean * 1.15) + needs.mut_carriers
                  + needs.gen_carriers + needs.canary_carriers)
    n_repos = max(1, len(gen.validated_repos(conn)))
    gen.ensure_pool(cfg, conn, quota_per_repo=(total_want // n_repos) + 20,
                    progress=progress)
    gen.assign_pool(cfg, conn)
    if "clean" in arms:
        gen.generate_clean(cfg, conn, n=needs.clean, progress=progress)
    if "canary" in arms:
        gen.generate_canaries(cfg, conn, n=gen.CANARY_TARGET, progress=progress)
    if "mut" in arms:
        from .arms import mut

        mut.generate_mut(cfg, conn, n_per_class=cfg.targets.n_per_class,
                         progress=progress)
    if "gen" in arms:
        from .arms import gen as genarm

        genarm.generate_gen(cfg, conn, n_per_class=cfg.targets.n_per_class,
                            progress=progress)
    if "szz" in arms:
        from .arms import szz

        szz.generate_szz(cfg, conn, progress=progress)


AVAILABLE_ARMS = ["clean", "canary"]  # extended as phases land: mut, gen, szz


def cmd_generate(args) -> int:
    cfg, conn = _open(args)
    arms = AVAILABLE_ARMS if args.arms == "all" else args.arms.split(",")
    _generate_into(cfg, conn, arms)
    for row in conn.execute(
        "SELECT COALESCE(d.arm,'CLEAN') arm, COUNT(*) c FROM review_items i"
        " LEFT JOIN defect_records d ON d.defect_id=i.defect_id GROUP BY 1 ORDER BY 1"):
        print(f"  {row['arm']}: {row['c']} items")
    return 0


def cmd_leakcheck(args) -> int:
    from .leakcheck import scan_payloads

    cfg, conn = _open(args)
    violations = scan_payloads(cfg, conn)
    if violations:
        print(f"LEAKCHECK FAILED: {len(violations)} violation(s)")
        for v in violations[:50]:
            print(f"  {v.payload}: {v.rule}: ...{v.snippet!r}...")
        return 1
    n = conn.execute("SELECT COUNT(*) c FROM review_items").fetchone()["c"]
    print(f"leakcheck clean over {n} payloads")
    return 0


def cmd_review(args) -> int:
    from .review import run_reviews

    cfg, conn = _open(args)
    s = run_reviews(cfg, conn, args.run_id, cache_only=args.cache_only)
    print(json.dumps(s, indent=1))
    return 3 if s["aborted"] else 0


def _score(cfg, conn, run_id):
    from .score import collect, compute_scores, emit_events

    results = collect(cfg, conn, run_id)
    scores = compute_scores(cfg, results)
    events_path = emit_events(cfg, conn, run_id, results)
    return results, scores, events_path


def cmd_score(args) -> int:
    cfg, conn = _open(args)
    results, scores, events_path = _score(cfg, conn, args.run_id)
    print(f"scored {len(results)} verdicts -> events at {events_path}")
    cg = scores["canary_gate"]
    print(f"canary gate: {cg['detected']}/{cg['n']} "
          f"({'PASS' if cg['pass'] else 'FAIL/absent'})")
    fp = scores["false_positive"]
    print(f"clean FP: {fp['fp']}/{fp['n_clean']}")
    return 0


def cmd_report(args) -> int:
    from .report import write_report

    cfg, conn = _open(args)
    _, scores, _ = _score(cfg, conn, args.run_id)
    path = write_report(cfg, conn, args.run_id, scores)
    print(f"wrote {path}")
    return 0


def _strip_ts(text: str) -> str:
    return "\n".join(ln for ln in text.splitlines()
                     if not ln.startswith("Generated: "))


def cmd_reproduce(args) -> int:
    """Regenerate REPORT.md from stored verdicts/cache only; byte-compare
    (modulo the Generated timestamp line) against the existing report."""
    from .report import write_report

    cfg, conn = _open(args)
    existing_path = cfg.root / cfg.reports_dir / "REPORT.md"
    if not existing_path.exists():
        print("no existing REPORT.md to compare against", file=sys.stderr)
        return 1
    before = existing_path.read_text()
    _, scores, _ = _score(cfg, conn, args.run_id)
    path = write_report(cfg, conn, args.run_id, scores)
    after = path.read_text()
    same = _strip_ts(before) == _strip_ts(after)
    print(f"reproduce: byte-comparable modulo timestamps: {same}")
    return 0 if same else 1


def cmd_smoke(args) -> int:
    """End-to-end mini run in an isolated smoke sandbox; <15 min (§4.7)."""
    from . import generate as gen
    from .leakcheck import scan_payloads
    from .report import write_report
    from .review import run_reviews

    t0 = time.monotonic()
    cfg, main_conn = _open(args)
    smoke_root = cfg.root / cfg.data_dir / "smoke"
    (smoke_root / cfg.data_dir).mkdir(parents=True, exist_ok=True)
    repos_link = smoke_root / cfg.data_dir / "repos"
    if not repos_link.exists():
        os.symlink(cfg.root / cfg.data_dir / "repos", repos_link)
    scfg = dataclasses.replace(cfg, root=smoke_root)
    sconn = dbmod.connect(scfg.db_path)

    repo_row = main_conn.execute(
        "SELECT name, url FROM repos WHERE validated=1 ORDER BY name LIMIT 1"
    ).fetchone()
    if not repo_row:
        print("smoke: no validated repos; run `gym repos` first", file=sys.stderr)
        return 1
    sconn.execute("INSERT OR IGNORE INTO repos (name, url, validated) VALUES (?,?,1)",
                  (repo_row["name"], repo_row["url"]))
    sconn.commit()
    print(f"smoke: repo={repo_row['name']}")

    gen.ensure_pool(scfg, sconn, quota_per_repo=40)
    gen.assign_pool(scfg, sconn, want={"CLEAN": 10, "CANARY_CARRIER": 8,
                                       "MUT_CARRIER": 12, "GEN_CARRIER": 8})
    gen.generate_clean(scfg, sconn, n=6)
    gen.generate_canaries(scfg, sconn, n=4)
    if "mut" in AVAILABLE_ARMS:
        from .arms import mut

        mut.generate_mut(scfg, sconn, n_per_class=2)
    if "gen" in AVAILABLE_ARMS:
        from .arms import gen as genarm

        genarm.generate_gen(scfg, sconn, n_per_class=2)

    violations = scan_payloads(scfg, sconn)
    if violations:
        print(f"smoke: LEAKCHECK FAILED ({len(violations)})", file=sys.stderr)
        return 1
    print("smoke: leakcheck clean")

    s = run_reviews(scfg, sconn, "smoke")
    print(f"smoke: reviewed={s['reviewed']} abstained={s['abstained']}"
          f" cost=${s['cost_usd']:.2f}")
    if s["aborted"]:
        print("smoke: aborted on spend cap", file=sys.stderr)
        return 3

    _, scores, events_path = _score(scfg, sconn, "smoke")
    path = write_report(scfg, sconn, "smoke", scores)

    # mirror smoke spend into the main ledger so the cap stays global
    smoke_spend = dbmod.spend_total(sconn)
    already = main_conn.execute(
        "SELECT COALESCE(SUM(cost_usd),0) t FROM spend_ledger WHERE purpose='smoke-mirror'"
    ).fetchone()["t"]
    delta = smoke_spend - already
    if delta > 0:
        main_conn.execute(
            "INSERT INTO spend_ledger (model, purpose, tokens_in, tokens_out, cost_usd)"
            " VALUES (?,?,0,0,?)", (cfg.verifier_model, "smoke-mirror", delta))
        main_conn.commit()

    elapsed = time.monotonic() - t0
    ok = elapsed < 900
    print(f"smoke: report={path} events={events_path}")
    print(f"smoke: completed in {elapsed:.0f}s (<900s: {ok})")
    return 0 if ok else 1


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="gym")
    parser.add_argument("--config", default="config.yaml")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("repos", help="clone, pin, and validate target repos")
    p.add_argument("--max-validated", type=int, default=5)
    p.set_defaults(func=cmd_repos)

    p = sub.add_parser("generate", help="produce review items for all arms")
    p.add_argument("--arms", default="all")
    p.set_defaults(func=cmd_generate)

    p = sub.add_parser("leakcheck", help="scan payloads for contamination (hard fail)")
    p.set_defaults(func=cmd_leakcheck)

    p = sub.add_parser("review", help="run the verifier over review items")
    p.add_argument("--run-id", default=DEFAULT_RUN_ID)
    p.add_argument("--cache-only", action="store_true")
    p.set_defaults(func=cmd_review)

    p = sub.add_parser("score", help="compute §7 metrics + emit event stream")
    p.add_argument("--run-id", default=DEFAULT_RUN_ID)
    p.set_defaults(func=cmd_score)

    p = sub.add_parser("report", help="generate REPORT.md + charts")
    p.add_argument("--run-id", default=DEFAULT_RUN_ID)
    p.set_defaults(func=cmd_report)

    p = sub.add_parser("smoke", help="end-to-end mini run (<15 min)")
    p.set_defaults(func=cmd_smoke)

    p = sub.add_parser("reproduce", help="regenerate REPORT.md from cache only")
    p.add_argument("--run-id", default=DEFAULT_RUN_ID)
    p.set_defaults(func=cmd_reproduce)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
