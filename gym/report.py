"""`gym report`: REPORT.md + static matplotlib charts (HANDOFF §4.6, §7).

Output is deterministic given identical scores input (sorted iteration, fixed
float formats); the single "Generated:" timestamp line is excluded from the
`gym reproduce` byte comparison (§14.4).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from .config import Config  # noqa: E402


def _fmt_rate(rate, ci) -> str:
    if rate is None:
        return "—"
    return f"{100 * rate:.1f}% [{100 * ci[0]:.1f}, {100 * ci[1]:.1f}]"


def _charts(scores: dict, charts_dir: Path) -> list[str]:
    charts_dir.mkdir(parents=True, exist_ok=True)
    made = []

    pca = scores["per_class_arm"]
    if pca:
        keys = sorted(pca)
        rates = [pca[k]["rate"] or 0 for k in keys]
        los = [max(0, (pca[k]["rate"] or 0) - pca[k]["ci95"][0]) for k in keys]
        his = [max(0, pca[k]["ci95"][1] - (pca[k]["rate"] or 0)) for k in keys]
        fig, ax = plt.subplots(figsize=(max(6, 0.7 * len(keys)), 4))
        ax.bar(range(len(keys)), rates, yerr=[los, his], capsize=3, color="#4878a8")
        ax.set_xticks(range(len(keys)))
        ax.set_xticklabels(keys, rotation=45, ha="right", fontsize=8)
        ax.set_ylabel("detection rate")
        ax.set_ylim(0, 1)
        ax.set_title("Per-class detection with 95% Wilson CI")
        fig.tight_layout()
        fig.savefig(charts_dir / "per_class_detection.png", dpi=120)
        plt.close(fig)
        made.append("per_class_detection.png")

    pa = scores["per_arm"]
    if pa:
        keys = sorted(pa)
        fig, ax = plt.subplots(figsize=(5, 3.5))
        rates = [pa[k]["rate"] or 0 for k in keys]
        los = [max(0, (pa[k]["rate"] or 0) - pa[k]["ci95"][0]) for k in keys]
        his = [max(0, pa[k]["ci95"][1] - (pa[k]["rate"] or 0)) for k in keys]
        ax.bar(keys, rates, yerr=[los, his], capsize=4, color="#a85448")
        ax.set_ylabel("detection rate")
        ax.set_ylim(0, 1)
        ax.set_title("Arm comparison (pooled)")
        fig.tight_layout()
        fig.savefig(charts_dir / "arm_comparison.png", dpi=120)
        plt.close(fig)
        made.append("arm_comparison.png")

    bins = scores["calibration_bins"]
    if bins:
        fig, ax = plt.subplots(figsize=(4.5, 4.5))
        ax.plot([0, 1], [0, 1], "--", color="gray", lw=1)
        ax.plot([b["mean_p"] for b in bins], [b["frac_defective"] for b in bins],
                "o-", color="#488a54")
        ax.set_xlabel("mean predicted p(defective)")
        ax.set_ylabel("observed fraction defective")
        brier = scores["brier"]
        ax.set_title(f"Reliability (Brier={brier:.3f})" if brier is not None
                     else "Reliability")
        fig.tight_layout()
        fig.savefig(charts_dir / "calibration.png", dpi=120)
        plt.close(fig)
        made.append("calibration.png")

    cost = {k: v for k, v in scores["cost_per_review"].items() if v}
    if cost:
        keys = sorted(cost)
        fig, ax = plt.subplots(figsize=(max(6, 0.6 * len(keys)), 3.5))
        ax.bar(range(len(keys)), [cost[k]["mean_cost_usd"] for k in keys],
               color="#7a5aa0")
        ax.set_ylabel("mean cost / review (USD)")
        ax.set_xticks(range(len(keys)))
        ax.set_xticklabels(keys, rotation=45, ha="right", fontsize=8)
        ax.set_title("Cost per review by class")
        fig.tight_layout()
        fig.savefig(charts_dir / "cost_per_review.png", dpi=120)
        plt.close(fig)
        made.append("cost_per_review.png")
    return made


def render_report(cfg: Config, run_id: str, scores: dict, spend_usd: float,
                  charts: list[str], generated_at: str) -> str:
    L: list[str] = []
    L.append("# Verification Gym REPORT")
    L.append("")
    L.append(f"Generated: {generated_at}")
    L.append("")
    L.append(f"run_id: `{run_id}` · seed: {cfg.seed} · verifier: `{cfg.verifier_model}`"
             f" · generator: `{cfg.generator_model}` · cumulative spend: ${spend_usd:.2f}")
    L.append("")
    L.append("## MEASURED (computed numbers; §7 pre-specified)")
    L.append("")
    L.append(f"Review items scored (canaries excluded per D14): {scores['n_items']}")
    L.append("")
    L.append("### Primary 1 — per-class detection rate (95% Wilson CI)")
    L.append("")
    L.append("| arm/class | n | detected | missed | misdirected | abstained | detection rate |")
    L.append("|---|---|---|---|---|---|---|")
    for key, c in scores["per_class_arm"].items():
        flag = " **LOW-POWER**" if c["low_power"] else ""
        L.append(f"| {key} | {c['n']} | {c['detected']} | {c['missed']} |"
                 f" {c['misdirected_flag']} | {c['abstained']} |"
                 f" {_fmt_rate(c['rate'], c['ci95'])}{flag} |")
    L.append("")
    L.append("Pooled per arm:")
    L.append("")
    L.append("| arm | n | detection rate |")
    L.append("|---|---|---|")
    for arm, c in sorted(scores["per_arm"].items()):
        L.append(f"| {arm} | {c['n']} | {_fmt_rate(c['rate'], c['ci95'])} |")
    L.append("")
    fp = scores["false_positive"]
    L.append("### Primary 2 — false-positive rate on CLEAN")
    L.append("")
    L.append(f"n_clean={fp['n_clean']}, FP={fp['fp']}, rate="
             f"{_fmt_rate(fp['rate'], fp['ci95'])}")
    L.append("")
    L.append("### Primary 3 — arm gap at matched class: detection(GEN) − detection(SZZ)")
    L.append("")
    if scores["arm_gap_gen_minus_szz"]:
        L.append("| class | n_gen | n_szz | Δ | bootstrap 95% CI |")
        L.append("|---|---|---|---|---|")
        for klass, g in sorted(scores["arm_gap_gen_minus_szz"].items()):
            L.append(f"| {klass} | {g['n_gen']} | {g['n_szz']} |"
                     f" {100 * g['delta']:+.1f}pp |"
                     f" [{100 * g['ci95'][0]:+.1f}, {100 * g['ci95'][1]:+.1f}] |")
    else:
        L.append("No class has n≥15 in both GEN and SZZ arms; gap not computable"
                 " for this run.")
    L.append("")
    L.append("### Secondary")
    L.append("")
    L.append("| class | AUROC (vs CLEAN; D15) |")
    L.append("|---|---|")
    for klass, a in sorted(scores["auroc_per_class"].items()):
        L.append(f"| {klass} | {a:.3f} |" if a is not None else f"| {klass} | — |")
    L.append("")
    lp = scores["localization_precision"]
    L.append(f"- Localization precision (detected / defect_found=true on defective):"
             f" {lp:.3f}" if lp is not None else
             "- Localization precision: — (no flags on defective items)")
    mr = scores["misdirected_flag_rate"]
    L.append(f"- Misdirected-flag rate (defective items): "
             f"{mr:.3f}" if mr is not None else "- Misdirected-flag rate: —")
    br = scores["brier"]
    L.append(f"- Brier score: {br:.4f}" if br is not None else "- Brier score: —")
    ab = scores["abstention"]
    L.append(f"- Abstentions: {ab['n']}"
             + (f" ({100 * ab['rate']:.1f}%)" if ab["rate"] is not None else ""))
    L.append("")
    L.append("Cost per review (mean):")
    L.append("")
    L.append("| class | n | tokens_in | tokens_out | latency_ms | USD |")
    L.append("|---|---|---|---|---|---|")
    for klass, c in sorted(scores["cost_per_review"].items()):
        if c is None:
            continue
        L.append(f"| {klass} | {c['n']} | {c['mean_tokens_in']:.0f} |"
                 f" {c['mean_tokens_out']:.0f} | {c['mean_latency_ms']:.0f} |"
                 f" {c['mean_cost_usd']:.4f} |")
    L.append("")
    cg = scores["canary_gate"]
    L.append("### Pipeline self-audit — canary gate (§14.1; excluded from metrics above)")
    L.append("")
    rate_s = f"{100 * cg['rate']:.1f}%" if cg["rate"] is not None else "—"
    L.append(f"canaries={cg['n']}, detected={cg['detected']}, rate={rate_s},"
             f" gate(≥90%): {'PASS' if cg['pass'] else 'FAIL'}")
    L.append("")
    if charts:
        L.append("### Charts")
        L.append("")
        for c in charts:
            L.append(f"![{c}](charts/{c})")
        L.append("")
    L.append("## INFERRED (interpretation; not computed)")
    L.append("")
    L.append(scores.get("_inferred", "_Interpretation is written at Phase 5;"
                                     " nothing inferred for this run._"))
    L.append("")
    return "\n".join(L)


def load_inferred(cfg: Config) -> str | None:
    """Interpretation text lives in a committed file so `gym reproduce`
    regenerates REPORT.md byte-identically (it is authored input, not output)."""
    p = cfg.root / cfg.reports_dir / "INFERRED.md"
    return p.read_text().strip() if p.exists() else None


def write_report(cfg: Config, conn, run_id: str, scores: dict,
                 out_dir: Path | None = None) -> Path:
    from . import db as dbmod

    out_dir = out_dir or (cfg.root / cfg.reports_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    charts = _charts(scores, out_dir / "charts")
    spend = dbmod.spend_total(conn)
    text = render_report(cfg, run_id, scores, spend, charts,
                         generated_at=datetime.now(timezone.utc).isoformat())
    path = out_dir / "REPORT.md"
    path.write_text(text)
    (out_dir / f"scores_{run_id}.json").write_text(
        json.dumps(scores, sort_keys=True, indent=1))
    return path
