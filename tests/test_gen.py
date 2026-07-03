"""GEN arm: edit parsing/validation, suite gate wiring, generation flow with a
scripted generator model (no API)."""

import json
import subprocess

import pytest

from gym.arms.gen import (_valid_python_edit, generate_gen, is_test_file,
                          parse_gen_edit, rejection_rates)


def test_parse_gen_edit():
    good = json.dumps({"file": "a.py", "old": "x = 1", "new": "x = 2", "note": "n"})
    e = parse_gen_edit(good)
    assert e["file"] == "a.py" and e["new_description"] is None
    assert parse_gen_edit("nope") is None
    assert parse_gen_edit(json.dumps({"file": "a.py", "old": "s", "new": "s"})) is None
    assert parse_gen_edit(json.dumps({"file": "", "old": "a", "new": "b"})) is None


def test_valid_python_edit_guards():
    text = "def f(x):\n    return x + 1\n"
    assert _valid_python_edit(text, "return x + 1", "return x - 1")
    assert not _valid_python_edit(text, "return x + 2", "return x - 1")  # no anchor
    assert not _valid_python_edit(text, "return x + 1", "return x +")    # syntax
    assert not _valid_python_edit("a = 1\na = 1\n", "a = 1", "a = 2")    # ambiguous


def test_is_test_file():
    assert is_test_file("tests/test_core.py")
    assert is_test_file("pkg/tests/helpers.py")
    assert is_test_file("foo_test.py")
    assert not is_test_file("src/click/core.py")


@pytest.fixture()
def env(tmp_path, fixture_repo):
    from gym import db as dbmod
    from gym import generate
    from gym.config import Config, ModelPrice, Targets

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
    conn.execute("INSERT INTO repos (name, url, validated, test_seconds)"
                 " VALUES ('fx','local',1, 1.0)")
    # no venv for fx -> baseline infeasible -> suite gate skipped (recorded)
    conn.commit()
    generate.ensure_pool(cfg, conn, quota_per_repo=10, progress=lambda *a: None)
    generate.assign_pool(cfg, conn, want={"GEN_CARRIER": 3})
    return cfg, conn


class GenTransport:
    """Scripted generator: proposes a real edit against fixture mod.py."""

    def __init__(self, responses):
        self.responses = list(responses)

    def complete(self, *, model, system, prompt, max_tokens):
        text = self.responses.pop(0) if self.responses else "{}"
        return {"text": text, "tokens_in": 500, "tokens_out": 200, "latency_ms": 5}


GOOD_EDIT = json.dumps({"file": "mod.py", "old": "    if x > hi:",
                        "new": "    if x >= hi:", "note": "boundary"})


def test_generate_gen_accepts_valid_edit(env, monkeypatch):
    cfg, conn = env
    import gym.arms.gen as genmod
    import gym.llm as llmmod

    t = GenTransport([GOOD_EDIT] * 8)
    real_call = llmmod.call_model

    def fake_call(cfg_, conn_, **kw):
        kw["transport"] = t
        return real_call(cfg_, conn_, **kw)

    monkeypatch.setattr(genmod, "call_model", fake_call)
    made = generate_gen(cfg, conn, n_per_class=1, progress=lambda *a: None)
    assert sum(made.values()) >= 1
    rec = conn.execute("SELECT * FROM defect_records WHERE arm='GEN'").fetchone()
    assert rec is not None
    prov = json.loads(rec["provenance"])
    assert prov["suite_checked"] is False  # fx has no validation venv
    rates = rejection_rates(conn)
    assert rates[rec["class"]]["accepted"] >= 1


def test_generate_gen_records_parse_failures(env, monkeypatch):
    cfg, conn = env
    import gym.arms.gen as genmod
    import gym.llm as llmmod

    t = GenTransport(["garbage"] * 30)
    real_call = llmmod.call_model

    def fake_call(cfg_, conn_, **kw):
        kw["transport"] = t
        return real_call(cfg_, conn_, **kw)

    monkeypatch.setattr(genmod, "call_model", fake_call)
    made = generate_gen(cfg, conn, n_per_class=1, progress=lambda *a: None)
    assert sum(made.values()) == 0
    n = conn.execute("SELECT COUNT(*) c FROM gen_attempts"
                     " WHERE outcome='parse_failure'").fetchone()["c"]
    assert n >= 1
