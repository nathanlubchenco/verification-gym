"""`gym review`: run the verifier over review items (HANDOFF §6).

Blind: randomized order (run seed), identical Appendix A prompt, no metadata.
Malformed JSON -> one re-ask with a format reminder -> abstention.
Resumable: existing (item, run) verdicts are skipped; SpendCapExceeded stops
cleanly with partial state persisted.
"""

from __future__ import annotations

import json
import random
import sqlite3
from typing import Any

from .config import Config
from .llm import (BatchRequest, SpendCapExceeded, Transport, call_model,
                  call_model_batch)
from .payload import load_payload, render_prompt

REVIEW_MAX_TOKENS = 1500
REMINDER = (
    "\n\nREMINDER: Your previous response was not a single valid JSON object. "
    "Respond with ONLY a JSON object exactly matching the schema in the "
    "instructions above. No prose, no code fences."
)

_SEVERITIES = {"low", "med", "high", None}


def _extract_json(text: str) -> dict | None:
    s = text.strip()
    if s.startswith("```"):
        s = s.strip("`")
        if s.lower().startswith("json"):
            s = s[4:]
    start = s.find("{")
    if start < 0:
        return None
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(s)):
        ch = s[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    obj = json.loads(s[start:i + 1])
                except json.JSONDecodeError:
                    return None
                return obj if isinstance(obj, dict) else None
    return None


def parse_verdict(text: str) -> dict[str, Any] | None:
    """Validate + normalize a §6 verdict; None if malformed in any way."""
    obj = _extract_json(text)
    if obj is None:
        return None
    if not isinstance(obj.get("defect_found"), bool):
        return None
    conf = obj.get("confidence")
    if not isinstance(conf, (int, float)) or isinstance(conf, bool):
        return None
    conf = max(0.0, min(100.0, float(conf)))
    locs_in = obj.get("locations")
    if not isinstance(locs_in, list):
        return None
    locs = []
    for l in locs_in:
        if not isinstance(l, dict):
            return None
        f, s, e = l.get("file"), l.get("start_line"), l.get("end_line")
        if not isinstance(f, str):
            return None
        if not isinstance(s, int) or not isinstance(e, int) \
                or isinstance(s, bool) or isinstance(e, bool):
            return None
        locs.append({"file": f, "start_line": s, "end_line": e})
    class_guess = obj.get("class_guess")
    if class_guess is not None and not isinstance(class_guess, str):
        return None
    severity = obj.get("severity")
    if severity not in _SEVERITIES:
        return None
    rationale = obj.get("rationale")
    if not isinstance(rationale, str):
        return None
    return {
        "defect_found": obj["defect_found"], "confidence": conf,
        "locations": locs, "class_guess": class_guess,
        "severity": severity, "rationale": rationale,
    }


def run_reviews(cfg: Config, conn: sqlite3.Connection, run_id: str, *,
                transport: Transport | None = None,
                item_ids: list[str] | None = None,
                cache_only: bool = False,
                progress=print) -> dict[str, Any]:
    rows = conn.execute("SELECT * FROM review_items ORDER BY item_id").fetchall()
    if item_ids is not None:
        wanted = set(item_ids)
        rows = [r for r in rows if r["item_id"] in wanted]
    rows = list(rows)
    random.Random(f"{cfg.seed}:review-order:{run_id}").shuffle(rows)

    done = {r["item_id"] for r in conn.execute(
        "SELECT item_id FROM verdicts WHERE run_id=?", (run_id,))}
    summary = {"reviewed": 0, "abstained": 0, "reasked": 0, "skipped": len(done),
               "cost_usd": 0.0, "aborted": False}

    for idx, row in enumerate(rows):
        if row["item_id"] in done:
            continue
        prompt = render_prompt(load_payload(cfg.root / row["payload_path"]))
        try:
            r = call_model(cfg, conn, model=cfg.verifier_model, system=None,
                           prompt=prompt, max_tokens=REVIEW_MAX_TOKENS,
                           purpose="review", transport=transport,
                           cache_only=cache_only)
            verdict = parse_verdict(r.text)
            tokens_in, tokens_out = r.tokens_in, r.tokens_out
            latency, cost, raw, ph = r.latency_ms, r.cost_usd, r.text, r.prompt_hash
            if verdict is None:
                summary["reasked"] += 1
                r2 = call_model(cfg, conn, model=cfg.verifier_model, system=None,
                                prompt=prompt + REMINDER,
                                max_tokens=REVIEW_MAX_TOKENS, purpose="review-reask",
                                transport=transport, cache_only=cache_only)
                verdict = parse_verdict(r2.text)
                tokens_in += r2.tokens_in
                tokens_out += r2.tokens_out
                latency += r2.latency_ms
                cost += r2.cost_usd
                raw = r2.text
        except SpendCapExceeded as exc:
            progress(f"HARD STOP: {exc}")
            summary["aborted"] = True
            break

        abstained = verdict is None
        conn.execute(
            "INSERT OR REPLACE INTO verdicts (item_id, run_id, raw_response,"
            " verdict_json, abstained, tokens_in, tokens_out, latency_ms,"
            " cost_usd, prompt_hash) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (row["item_id"], run_id, raw,
             None if abstained else json.dumps(verdict, sort_keys=True),
             int(abstained), tokens_in, tokens_out, latency, cost, ph),
        )
        conn.commit()
        summary["reviewed"] += 1
        summary["abstained"] += int(abstained)
        summary["cost_usd"] += cost
        if (idx + 1) % 25 == 0:
            progress(f"  reviewed {summary['reviewed']} items"
                     f" (${summary['cost_usd']:.2f} this session)")
    return summary


def run_reviews_batch(cfg: Config, conn: sqlite3.Connection, run_id: str, *,
                      batch_transport=None, progress=print) -> dict[str, Any]:
    """Batched variant of run_reviews (D17): same prompts/protocol at 50%
    token pricing. Two batch passes: reviews, then re-asks for malformed."""
    rows = conn.execute("SELECT * FROM review_items ORDER BY item_id").fetchall()
    done = {r["item_id"] for r in conn.execute(
        "SELECT item_id FROM verdicts WHERE run_id=?", (run_id,))}
    rows = [r for r in rows if r["item_id"] not in done]
    rows = list(rows)
    random.Random(f"{cfg.seed}:review-order:{run_id}").shuffle(rows)
    summary = {"reviewed": 0, "abstained": 0, "reasked": 0, "skipped": len(done),
               "cost_usd": 0.0, "aborted": False}
    if not rows:
        return summary

    prompts = {r["item_id"]: render_prompt(load_payload(cfg.root / r["payload_path"]))
               for r in rows}
    reqs = [BatchRequest(custom_id=r["item_id"], model=cfg.verifier_model,
                         system=None, prompt=prompts[r["item_id"]],
                         max_tokens=REVIEW_MAX_TOKENS, purpose="review")
            for r in rows]
    try:
        first = call_model_batch(cfg, conn, reqs, transport=batch_transport,
                                 progress=progress)
    except SpendCapExceeded as exc:
        progress(f"HARD STOP: {exc}")
        summary["aborted"] = True
        return summary

    reask_reqs = []
    partial: dict[str, tuple] = {}
    for item_id, r in first.items():
        verdict = parse_verdict(r.text)
        if verdict is None:
            summary["reasked"] += 1
            reask_reqs.append(BatchRequest(
                custom_id=item_id, model=cfg.verifier_model, system=None,
                prompt=prompts[item_id] + REMINDER,
                max_tokens=REVIEW_MAX_TOKENS, purpose="review-reask"))
            partial[item_id] = (r.tokens_in, r.tokens_out, r.cost_usd)
            continue
        _persist_verdict(conn, item_id, run_id, r.text, verdict, False,
                         r.tokens_in, r.tokens_out, 0, r.cost_usd, r.prompt_hash)
        summary["reviewed"] += 1
        summary["cost_usd"] += r.cost_usd

    if reask_reqs:
        try:
            second = call_model_batch(cfg, conn, reask_reqs,
                                      transport=batch_transport, progress=progress)
        except SpendCapExceeded as exc:
            progress(f"HARD STOP during re-asks: {exc}")
            summary["aborted"] = True
            return summary
        for req in reask_reqs:
            item_id = req.custom_id
            r2 = second.get(item_id)
            if r2 is None:
                continue  # batch item failed; stays pending for a resume
            t_in, t_out, cost = partial[item_id]
            verdict = parse_verdict(r2.text)
            abstained = verdict is None
            _persist_verdict(conn, item_id, run_id, r2.text, verdict, abstained,
                             t_in + r2.tokens_in, t_out + r2.tokens_out, 0,
                             cost + r2.cost_usd, r2.prompt_hash)
            summary["reviewed"] += 1
            summary["abstained"] += int(abstained)
            summary["cost_usd"] += cost + r2.cost_usd
    return summary


def _persist_verdict(conn, item_id, run_id, raw, verdict, abstained,
                     tokens_in, tokens_out, latency_ms, cost, prompt_hash):
    conn.execute(
        "INSERT OR REPLACE INTO verdicts (item_id, run_id, raw_response,"
        " verdict_json, abstained, tokens_in, tokens_out, latency_ms,"
        " cost_usd, prompt_hash) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (item_id, run_id, raw,
         None if verdict is None else json.dumps(verdict, sort_keys=True),
         int(abstained), tokens_in, tokens_out, latency_ms, cost, prompt_hash),
    )
    conn.commit()
