"""Verifier loop: parsing, re-ask protocol, abstention, cap abort, resume."""

import json

import pytest

from gym import db as dbmod
from gym import generate
from gym.config import Config, ModelPrice, Targets
from gym.review import parse_verdict, run_reviews

GOOD = json.dumps({"defect_found": True, "confidence": 80,
                   "locations": [{"file": "a.py", "start_line": 1, "end_line": 2}],
                   "class_guess": "MUT-01", "severity": "high", "rationale": "x"})


def test_parse_verdict_happy():
    v = parse_verdict(GOOD)
    assert v["defect_found"] is True and v["confidence"] == 80.0
    assert v["locations"][0]["file"] == "a.py"


def test_parse_verdict_fenced_and_prose():
    assert parse_verdict(f"Here you go:\n```json\n{GOOD}\n```") is not None


def test_parse_verdict_rejects_bad_shapes():
    assert parse_verdict("not json at all") is None
    assert parse_verdict('{"defect_found": "yes"}') is None
    assert parse_verdict(json.dumps({
        "defect_found": False, "confidence": 10, "locations": "none",
        "class_guess": None, "severity": None, "rationale": ""})) is None
    assert parse_verdict(json.dumps({
        "defect_found": False, "confidence": 10,
        "locations": [{"file": 3, "start_line": 1, "end_line": 2}],
        "class_guess": None, "severity": None, "rationale": ""})) is None


def test_parse_verdict_clamps_confidence():
    v = parse_verdict(json.dumps({
        "defect_found": False, "confidence": 250, "locations": [],
        "class_guess": None, "severity": None, "rationale": "ok"}))
    assert v["confidence"] == 100.0


class ScriptedTransport:
    """Returns scripted responses in order, then repeats the last one."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    def complete(self, *, model, system, prompt, max_tokens):
        self.calls += 1
        text = self.responses.pop(0) if self.responses else '{"defect_found": false}'
        return {"text": text, "tokens_in": 100, "tokens_out": 50, "latency_ms": 10}


@pytest.fixture()
def env(tmp_path, fixture_repo):
    import subprocess

    cfg = Config(
        seed=7, generator_model="m", verifier_model="m", spend_cap_usd=5.0,
        data_dir="data", events_dir="events", reports_dir="reports",
        payload_budget_chars=100000, targets=Targets(1, 1, 0.4),
        pricing={"m": ModelPrice(5.0, 25.0)}, repos=[], root=tmp_path,
    )
    dest = tmp_path / "data" / "repos" / "fx"
    dest.parent.mkdir(parents=True)
    subprocess.run(["git", "clone", "-q", str(fixture_repo), str(dest)], check=True)
    conn = dbmod.connect(cfg.db_path)
    conn.execute("INSERT INTO repos (name, url, validated) VALUES ('fx','local',1)")
    conn.commit()
    generate.ensure_pool(cfg, conn, quota_per_repo=10, progress=lambda *a: None)
    generate.assign_pool(cfg, conn, want={"CLEAN": 2, "CANARY_CARRIER": 1})
    generate.generate_clean(cfg, conn, n=2, progress=lambda *a: None)
    return cfg, conn


NEG = json.dumps({"defect_found": False, "confidence": 90, "locations": [],
                  "class_guess": None, "severity": None, "rationale": "fine"})


def test_run_reviews_happy_and_persisted(env):
    cfg, conn = env
    t = ScriptedTransport([NEG, NEG])
    s = run_reviews(cfg, conn, "r1", transport=t, progress=lambda *a: None)
    assert s["reviewed"] == 2 and s["abstained"] == 0
    rows = conn.execute("SELECT * FROM verdicts WHERE run_id='r1'").fetchall()
    assert len(rows) == 2
    assert all(json.loads(r["verdict_json"])["defect_found"] is False for r in rows)


def test_reask_then_abstain(env):
    cfg, conn = env
    # first item: garbage twice -> abstained; second: garbage then valid -> ok
    t = ScriptedTransport(["garbage", "more garbage", "nope", NEG])
    s = run_reviews(cfg, conn, "r2", transport=t, progress=lambda *a: None)
    assert s["reviewed"] == 2
    assert s["reasked"] == 2
    assert s["abstained"] == 1
    ab = conn.execute(
        "SELECT COUNT(*) c FROM verdicts WHERE run_id='r2' AND abstained=1"
    ).fetchone()["c"]
    assert ab == 1


def test_resume_skips_done(env):
    cfg, conn = env
    t1 = ScriptedTransport([NEG, NEG])
    run_reviews(cfg, conn, "r3", transport=t1, progress=lambda *a: None)
    t2 = ScriptedTransport([])
    s2 = run_reviews(cfg, conn, "r3", transport=t2, progress=lambda *a: None)
    assert s2["reviewed"] == 0 and s2["skipped"] == 2 and t2.calls == 0


def test_cap_abort_persists_partial(env):
    """Cap trip mid-run (mechanics unit-tested in test_llm): first verdict is
    persisted, loop stops cleanly, aborted flag set."""
    from gym.llm import SpendCapExceeded

    cfg, conn = env

    class CapAfterOne:
        calls = 0

        def complete(self, **kw):
            self.calls += 1
            if self.calls > 1:
                raise SpendCapExceeded("simulated cap")
            return {"text": NEG, "tokens_in": 100, "tokens_out": 50, "latency_ms": 10}

    s = run_reviews(cfg, conn, "r4", transport=CapAfterOne(), progress=lambda *a: None)
    assert s["aborted"] is True
    n = conn.execute("SELECT COUNT(*) c FROM verdicts WHERE run_id='r4'").fetchone()["c"]
    assert n == 1  # partial state persisted cleanly


def test_cap_already_reached_blocks_everything(env):
    cfg, conn = env
    conn.execute("INSERT INTO spend_ledger (model, purpose, tokens_in, tokens_out,"
                 " cost_usd) VALUES ('m','seed',0,0,5.0)")
    conn.commit()
    t = ScriptedTransport([NEG, NEG])
    s = run_reviews(cfg, conn, "r5", transport=t, progress=lambda *a: None)
    assert s["aborted"] is True and s["reviewed"] == 0 and t.calls == 0
