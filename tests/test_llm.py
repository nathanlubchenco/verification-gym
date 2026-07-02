"""LLM client: caching, spend ledger, hard cap. Uses a fake transport (no API)."""

import pytest

from gym import db as dbmod
from gym.config import Config, ModelPrice, Targets
from gym.llm import SpendCapExceeded, call_model


class FakeTransport:
    def __init__(self):
        self.calls = 0

    def complete(self, *, model, system, prompt, max_tokens):
        self.calls += 1
        return {"text": '{"ok": true}', "tokens_in": 1000, "tokens_out": 500,
                "latency_ms": 100}


@pytest.fixture()
def cfg(tmp_path):
    return Config(
        seed=42, generator_model="m", verifier_model="m", spend_cap_usd=1.0,
        data_dir=tmp_path / "data", events_dir=tmp_path / "events",
        reports_dir=tmp_path / "reports", payload_budget_chars=100000,
        targets=Targets(50, 30, 0.4),
        pricing={"m": ModelPrice(input_per_mtok=5.0, output_per_mtok=25.0)},
        repos=[], root=tmp_path,
    )


@pytest.fixture()
def conn(cfg):
    return dbmod.connect(cfg.db_path)


def test_pricing_math_and_ledger(cfg, conn):
    t = FakeTransport()
    r = call_model(cfg, conn, model="m", system=None, prompt="hello",
                   max_tokens=100, purpose="test", transport=t)
    # 1000 in @ $5/M + 500 out @ $25/M
    assert r.cost_usd == pytest.approx(0.005 + 0.0125)
    assert dbmod.spend_total(conn) == pytest.approx(r.cost_usd)
    assert not r.from_cache


def test_cache_hit_skips_transport_and_spend(cfg, conn):
    t = FakeTransport()
    r1 = call_model(cfg, conn, model="m", system="s", prompt="p",
                    max_tokens=100, purpose="test", transport=t)
    r2 = call_model(cfg, conn, model="m", system="s", prompt="p",
                    max_tokens=100, purpose="test", transport=t)
    assert t.calls == 1
    assert r2.from_cache and not r1.from_cache
    assert r2.text == r1.text
    assert r2.prompt_hash == r1.prompt_hash
    assert dbmod.spend_total(conn) == pytest.approx(r1.cost_usd)  # no double spend


def test_different_prompt_different_hash(cfg, conn):
    t = FakeTransport()
    r1 = call_model(cfg, conn, model="m", system=None, prompt="a",
                    max_tokens=100, purpose="t", transport=t)
    r2 = call_model(cfg, conn, model="m", system=None, prompt="b",
                    max_tokens=100, purpose="t", transport=t)
    assert r1.prompt_hash != r2.prompt_hash
    assert t.calls == 2


def test_hard_cap_blocks_before_call(cfg, conn):
    conn.execute(
        "INSERT INTO spend_ledger (model, purpose, tokens_in, tokens_out, cost_usd)"
        " VALUES ('m', 'seed', 0, 0, 1.0)"
    )
    conn.commit()
    t = FakeTransport()
    with pytest.raises(SpendCapExceeded):
        call_model(cfg, conn, model="m", system=None, prompt="p",
                   max_tokens=100, purpose="test", transport=t)
    assert t.calls == 0
