"""Model client with mandatory cache and spend cap (HANDOFF §4.4, §9).

Every call is keyed by (model, prompt_hash, seed); cache hits are free and make
re-runs deterministic. All spend goes through one ledger; calls hard-stop once
cumulative spend reaches GYM_SPEND_CAP_USD.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from dataclasses import dataclass
from typing import Any, Protocol

from . import db as dbmod
from .config import Config


class SpendCapExceeded(RuntimeError):
    pass


@dataclass
class LLMResult:
    text: str
    tokens_in: int
    tokens_out: int
    latency_ms: int
    cost_usd: float
    prompt_hash: str
    from_cache: bool


class Transport(Protocol):
    def complete(self, *, model: str, system: str | None, prompt: str,
                 max_tokens: int) -> dict[str, Any]: ...


class AnthropicTransport:
    """Real API transport. Constructed lazily so tests never import network state."""

    def __init__(self) -> None:
        import anthropic

        self._client = anthropic.Anthropic()

    def complete(self, *, model, system, prompt, max_tokens):
        kwargs: dict[str, Any] = dict(
            model=model, max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        if system:
            kwargs["system"] = system
        start = time.monotonic()
        resp = self._client.messages.create(**kwargs)
        latency_ms = int((time.monotonic() - start) * 1000)
        text = "".join(b.text for b in resp.content if b.type == "text")
        return {
            "text": text,
            "tokens_in": resp.usage.input_tokens,
            "tokens_out": resp.usage.output_tokens,
            "latency_ms": latency_ms,
        }


def prompt_hash(model: str, system: str | None, prompt: str, max_tokens: int) -> str:
    canonical = json.dumps(
        {"model": model, "system": system, "prompt": prompt, "max_tokens": max_tokens},
        sort_keys=True, ensure_ascii=True,
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def estimate_cost(cfg: Config, model: str, prompt: str, system: str | None,
                  max_tokens: int) -> float:
    price = cfg.pricing[model]
    est_in = (len(prompt) + len(system or "")) / 3.6  # chars->tokens heuristic
    return est_in / 1e6 * price.input_per_mtok + max_tokens / 1e6 * price.output_per_mtok


_default_transport: Transport | None = None


def call_model(cfg: Config, conn: sqlite3.Connection, *, model: str,
               system: str | None, prompt: str, max_tokens: int, purpose: str,
               transport: Transport | None = None,
               cache_only: bool = False) -> LLMResult:
    ph = prompt_hash(model, system, prompt, max_tokens)
    key = f"{model}|{ph}|{cfg.seed}"

    row = conn.execute("SELECT * FROM llm_cache WHERE cache_key = ?", (key,)).fetchone()
    if row is not None:
        return LLMResult(
            text=row["response_text"], tokens_in=row["tokens_in"],
            tokens_out=row["tokens_out"], latency_ms=row["latency_ms"],
            cost_usd=row["cost_usd"], prompt_hash=ph, from_cache=True,
        )
    if cache_only:
        raise KeyError(f"cache_only: no cached response for {key[:48]}... ({purpose})")

    spent = dbmod.spend_total(conn)
    if spent >= cfg.spend_cap_usd:
        raise SpendCapExceeded(f"cumulative spend ${spent:.2f} >= cap ${cfg.spend_cap_usd:.2f}")
    if spent + estimate_cost(cfg, model, prompt, system, max_tokens) > cfg.spend_cap_usd:
        raise SpendCapExceeded(
            f"estimated call cost would exceed cap (${spent:.2f} spent, cap ${cfg.spend_cap_usd:.2f})"
        )

    if transport is None:
        global _default_transport
        if _default_transport is None:
            _default_transport = AnthropicTransport()
        transport = _default_transport

    out = transport.complete(model=model, system=system, prompt=prompt,
                             max_tokens=max_tokens)
    price = cfg.pricing[model]
    cost = (out["tokens_in"] / 1e6 * price.input_per_mtok
            + out["tokens_out"] / 1e6 * price.output_per_mtok)

    conn.execute(
        "INSERT INTO spend_ledger (model, purpose, tokens_in, tokens_out, cost_usd)"
        " VALUES (?,?,?,?,?)",
        (model, purpose, out["tokens_in"], out["tokens_out"], cost),
    )
    conn.execute(
        "INSERT OR REPLACE INTO llm_cache (cache_key, model, prompt_hash, seed,"
        " response_text, tokens_in, tokens_out, latency_ms, cost_usd)"
        " VALUES (?,?,?,?,?,?,?,?,?)",
        (key, model, ph, cfg.seed, out["text"], out["tokens_in"], out["tokens_out"],
         out["latency_ms"], cost),
    )
    conn.commit()
    return LLMResult(
        text=out["text"], tokens_in=out["tokens_in"], tokens_out=out["tokens_out"],
        latency_ms=out["latency_ms"], cost_usd=cost, prompt_hash=ph, from_cache=False,
    )
