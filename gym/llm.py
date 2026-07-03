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


BATCH_DISCOUNT = 0.5  # Message Batches API: 50% of standard token prices (D17)


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
        import anthropic

        kwargs: dict[str, Any] = dict(
            model=model, max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        if system:
            kwargs["system"] = system
        start = time.monotonic()
        try:
            resp = self._client.messages.create(**kwargs)
        except anthropic.BadRequestError as exc:
            if "credit balance" in str(exc).lower():
                # account-level billing stop: abort cleanly like a cap hit;
                # everything resumes once the operator adds credits
                raise SpendCapExceeded(f"account credit exhausted: {exc}") from exc
            raise
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
    # 2.5 chars/token: conservative for code-heavy prompts (measured 2.68 mean
    # across validated repos, Phase 0) so the pre-call cap guard over-estimates.
    est_in = (len(prompt) + len(system or "")) / 2.5
    return est_in / 1e6 * price.input_per_mtok + max_tokens / 1e6 * price.output_per_mtok


class OpenAITransport:
    """OpenAI chat-completions transport for cross-model runs. gpt-5.x models
    spend completion tokens on internal reasoning, so callers' max_tokens is
    treated as a floor and given headroom (D18)."""

    REASONING_HEADROOM = 2500

    def __init__(self) -> None:
        from openai import OpenAI

        self._client = OpenAI()

    def complete(self, *, model, system, prompt, max_tokens):
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        start = time.monotonic()
        resp = self._client.chat.completions.create(
            model=model, messages=messages,
            max_completion_tokens=max_tokens + self.REASONING_HEADROOM,
        )
        latency_ms = int((time.monotonic() - start) * 1000)
        return {
            "text": resp.choices[0].message.content or "",
            "tokens_in": resp.usage.prompt_tokens,
            "tokens_out": resp.usage.completion_tokens,
            "latency_ms": latency_ms,
        }


_default_transports: dict[str, Transport] = {}


def transport_for(model: str) -> Transport:
    kind = "openai" if model.startswith(("gpt-", "o1", "o3", "o4")) else "anthropic"
    if kind not in _default_transports:
        _default_transports[kind] = (OpenAITransport() if kind == "openai"
                                     else AnthropicTransport())
    return _default_transports[kind]


_default_transport: Transport | None = None


@dataclass
class BatchRequest:
    custom_id: str
    model: str
    system: str | None
    prompt: str
    max_tokens: int
    purpose: str


class BatchTransport(Protocol):
    def run_batch(self, requests: list[BatchRequest], progress) -> list[tuple]:
        """Yields (custom_id, ok, text, tokens_in, tokens_out)."""
        ...


class AnthropicBatchTransport:
    POLL_S = 30

    def __init__(self) -> None:
        import anthropic

        self._client = anthropic.Anthropic()

    def run_batch(self, requests, progress):
        out = []
        CHUNK = 1000
        for i in range(0, len(requests), CHUNK):
            chunk = requests[i:i + CHUNK]
            payload = []
            for r in chunk:
                params = {"model": r.model, "max_tokens": r.max_tokens,
                          "messages": [{"role": "user", "content": r.prompt}]}
                if r.system:
                    params["system"] = r.system
                payload.append({"custom_id": r.custom_id, "params": params})
            batch = self._client.messages.batches.create(requests=payload)
            progress(f"  batch {batch.id}: {len(chunk)} requests submitted")
            while True:
                b = self._client.messages.batches.retrieve(batch.id)
                if b.processing_status == "ended":
                    break
                progress(f"  batch {batch.id}: {b.request_counts.processing} processing")
                time.sleep(self.POLL_S)
            for result in self._client.messages.batches.results(batch.id):
                if result.result.type == "succeeded":
                    msg = result.result.message
                    text = "".join(bk.text for bk in msg.content if bk.type == "text")
                    out.append((result.custom_id, True, text,
                                msg.usage.input_tokens, msg.usage.output_tokens))
                else:
                    out.append((result.custom_id, False, result.result.type, 0, 0))
        return out


def call_model_batch(cfg: Config, conn: sqlite3.Connection,
                     requests: list[BatchRequest], *,
                     transport: BatchTransport | None = None,
                     progress=print) -> dict[str, LLMResult]:
    """Batched calls at BATCH_DISCOUNT pricing. Cache/ledger semantics match
    call_model; latency_ms is 0 (not meaningful under batching, D17). Failed
    requests are simply absent from the result (caller resumes later)."""
    results: dict[str, LLMResult] = {}
    pending: list[BatchRequest] = []
    hashes: dict[str, str] = {}
    for r in requests:
        ph = prompt_hash(r.model, r.system, r.prompt, r.max_tokens)
        hashes[r.custom_id] = ph
        row = conn.execute("SELECT * FROM llm_cache WHERE cache_key=?",
                           (f"{r.model}|{ph}|{cfg.seed}",)).fetchone()
        if row is not None:
            results[r.custom_id] = LLMResult(
                text=row["response_text"], tokens_in=row["tokens_in"],
                tokens_out=row["tokens_out"], latency_ms=row["latency_ms"],
                cost_usd=row["cost_usd"], prompt_hash=ph, from_cache=True)
        else:
            pending.append(r)
    if not pending:
        return results

    spent = dbmod.spend_total(conn)
    est = sum(estimate_cost(cfg, r.model, r.prompt, r.system, r.max_tokens)
              for r in pending) * BATCH_DISCOUNT
    if spent >= cfg.spend_cap_usd:
        raise SpendCapExceeded(f"spend ${spent:.2f} >= cap ${cfg.spend_cap_usd:.2f}")
    if spent + est > cfg.spend_cap_usd:
        raise SpendCapExceeded(
            f"batch estimate ${est:.2f} would exceed cap"
            f" (${spent:.2f} spent, cap ${cfg.spend_cap_usd:.2f})")

    transport = transport or AnthropicBatchTransport()
    by_id = {r.custom_id: r for r in pending}
    for cid, ok, text, tin, tout in transport.run_batch(pending, progress):
        if not ok:
            progress(f"  batch item {cid} failed: {text}")
            continue
        r = by_id[cid]
        price = cfg.pricing[r.model]
        cost = (tin / 1e6 * price.input_per_mtok
                + tout / 1e6 * price.output_per_mtok) * BATCH_DISCOUNT
        ph = hashes[cid]
        conn.execute(
            "INSERT INTO spend_ledger (model, purpose, tokens_in, tokens_out,"
            " cost_usd) VALUES (?,?,?,?,?)", (r.model, r.purpose, tin, tout, cost))
        conn.execute(
            "INSERT OR REPLACE INTO llm_cache (cache_key, model, prompt_hash, seed,"
            " response_text, tokens_in, tokens_out, latency_ms, cost_usd)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            (f"{r.model}|{ph}|{cfg.seed}", r.model, ph, cfg.seed, text,
             tin, tout, 0, cost))
        conn.commit()
        results[cid] = LLMResult(text=text, tokens_in=tin, tokens_out=tout,
                                 latency_ms=0, cost_usd=cost, prompt_hash=ph,
                                 from_cache=False)
    return results


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
        transport = transport_for(model)

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
