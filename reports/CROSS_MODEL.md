# Cross-Model Matrix (operator-directed extension, D18)

Date: 2026-07-03 · Models: `claude-opus-4-8` (Opus), `gpt-5.4-mini-2026-03-17`
(GPT) · Same repos, same Appendix A prompt, same one-pass §6 protocol, same
seed and scoring rules (D9/D14/D15) as the pre-registered run. Ledger at
completion: $103.49 (unified internal cap $125; OpenAI-side spend ≈ $26 of it).

## MEASURED

### Detection matrix — GEN arms and the real-defect anchor (95% Wilson CIs)

| verifier ↓ / defect source → | GEN by Opus (n=265) | GEN by GPT (n=300) | SZZ real (n=150) | CLEAN FP (n=433) | MUT (n=242) | canaries |
|---|---|---|---|---|---|---|
| **Opus 4.8** | **58.9%** [52.9, 64.6] | **50.7%** [45.0, 56.3] | **26.7%** [20.2, 34.3] | 19.9% | 89.3% | 24/24 |
| **GPT-5.4-mini** | **41.1%** [35.4, 47.1] | **29.3%** [24.5, 34.7] | **31.3%** [24.5, 39.1] | 24.9% | 51.2% | **14/24** |

Misdirected-flag rates (defect found, wrong lines under the fixed ±2 rule):
Opus 8% / 5% / 31% on opus-GEN / gpt-GEN / SZZ; GPT 20% / 15% / 39%.

### Arm gap vs SZZ at matched classes (bootstrap 95% CI)

| verifier | GEN source | GEN-01 gap | GEN-02 gap |
|---|---|---|---|
| Opus | Opus-generated | **+42.1pp** [+24.8, +58.8] | **+48.2pp** [+27.6, +67.5] |
| Opus | GPT-generated | **+29.6pp** [+11.5, +46.3] | **+42.2pp** [+20.4, +62.0] |
| GPT | Opus-generated | −6.0pp [−24.0, +11.7] | +26.0pp [+4.6, +46.7] |
| GPT | GPT-generated | **−17.8pp** [−33.2, −2.3] | +30.2pp [+8.5, +50.0] |

### Generator quality under the suite gate

GPT's defects were suite-caught at ~20% of checkable attempts vs ~5% for Opus
(gen_attempts, generator-tagged); GPT still filled all six classes to 50/50.
GPT-generated items reviewed by Opus include the same §5 realism constraints
and identical injection machinery.

### Caveat specific to the GPT verifier

GPT fails the §14.1 canary gate (58%). Manual inspection of all 10 misses:
6 are correct semantic identifications with line numbers >±2 off (localization
weakness — consistent with its 2–3× misdirected rates), 4 are true misses of
blatant inversions (e.g. calling `if X:` → `if not (X):` "logically
equivalent"). The pipeline itself is validated by Opus's 24/24 on identical
items. Per §14.1's spirit, treat GPT's absolute detection levels as
conservative lower bounds; its *relative* per-source ordering is the sturdier
signal.

## INFERRED (interpretation; revises the single-model reading)

1. **The synthetic-vs-real gap survives the cross-model control — the main
   run's headline was not (mostly) self-preference.** The strong verifier
   detects the *other* model's defects at 50.7% vs 26.7% on real defects:
   +29.6/+42.2pp at matched classes, with CIs excluding zero. LLM-written
   defects are systematically easier than organically-grown ones regardless of
   who wrote them. The interim reading (that the gap "collapsed" under the
   cross verifier) conflated this with the weak verifier's floor effects and
   is superseded by the full matrix.
2. **Same-model familiarity is modest at best, and reversed for GPT.** Opus:
   own-defects 58.9% vs other's 50.7% (+8pp, CIs overlap). GPT: own-defects
   29.3% vs other's 41.1% (−12pp) — it is *worst* on its own defects
   (GEN-01 gap −17.8pp, CI excluding zero). If anything the data suggest
   same-model *blind spots*, not same-model advantage. Practical consequence:
   using a different model as reviewer than as author costs little and may
   help; but neither configuration closes the gap to real defects.
3. **The real-defect anchor barely moves across verifiers** (26.7% vs 31.3%,
   overlapping CIs) while synthetic arms swing 30–40 points. Real-bug
   detection looks like the hard, stable quantity; synthetic-arm performance
   is verifier-idiosyncratic. Benchmarks without a real-defect arm measure
   the wrong thing.
4. **Verifier strength shows up most on mutations and canaries** (89% vs 51%;
   24/24 vs 14/24), least on real defects. Scaling verifier capability (mini →
   frontier) bought ~0 points on SZZ in this pair — consistent with real-defect
   verification being bottlenecked by something other than the capability
   these models differ in (plausibly: context beyond the diff).
5. GPT's higher misdirected rates mean part of its deficit is localization,
   not detection; even crediting all misdirected flags as detections, its
   profile stays flatter and lower than Opus on synthetic arms.

## Reproduction

Verdict runs: `main` (Opus over original items, pre-registered — untouched),
`xm-opus` (Opus over GPT-generated items), `xm-gpt54mini` (GPT over all 1,414
items). All calls cached by `(model, prompt_hash, seed)`; events:
`events/run_xm-opus.jsonl`, `events/run_xm-gpt54mini.jsonl`.
Pricing (checked 2026-07-03): [gpt-5.4-mini $0.75/$4.50 per MTok](https://pricepertoken.com/pricing-page/model/openai-gpt-5.4-mini)
([OpenRouter](https://openrouter.ai/openai/gpt-5.4-mini), [OpenAI pricing](https://developers.openai.com/api/docs/pricing)).
