"""gym CLI: repos | generate | leakcheck | review | score | report | smoke | reproduce."""

from __future__ import annotations

import argparse
import sys

from . import db as dbmod
from .config import load_config


def cmd_repos(args) -> int:
    from . import repos as reposmod

    cfg = load_config(args.config)
    conn = dbmod.connect(cfg.db_path)
    validated = 0
    want = args.max_validated
    for spec in cfg.repos:
        if validated >= want:
            print(f"-- reached {want} validated repos; skipping remaining candidates")
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


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="gym")
    parser.add_argument("--config", default="config.yaml")
    sub = parser.add_subparsers(dest="command", required=True)

    p_repos = sub.add_parser("repos", help="clone, pin, and validate target repos")
    p_repos.add_argument("--max-validated", type=int, default=5)
    p_repos.set_defaults(func=cmd_repos)

    for name, help_text in [
        ("generate", "produce review items for all arms"),
        ("leakcheck", "scan payloads for ground-truth contamination"),
        ("review", "run the verifier over review items"),
        ("score", "compute metrics and emit event stream"),
        ("report", "generate REPORT.md and charts"),
        ("smoke", "end-to-end mini run"),
        ("reproduce", "regenerate REPORT.md from cache only"),
    ]:
        p = sub.add_parser(name, help=help_text)
        p.set_defaults(func=lambda a, n=name: _not_implemented(n))

    args = parser.parse_args(argv)
    return args.func(args)


def _not_implemented(name: str) -> int:
    print(f"gym {name}: not implemented yet (see plan phases)", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
