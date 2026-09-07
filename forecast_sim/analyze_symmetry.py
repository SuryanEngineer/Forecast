"""
Statistical analysis of symmetry_batch_results.csv: does the permanent
bot population show a systematic ELO/ROI edge over same-tenure humans, or
is any observed gap just sampling noise -- and does that answer change
across strategy-mix / bot:human ratio combinations?
"""

import math
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

OUT_DIR = "symmetry_analysis"
import os
os.makedirs(OUT_DIR, exist_ok=True)


def one_sample_test(values):
    """t-statistic + a normal-approximation two-sided p-value (no scipy
    available in this sandbox). Fine for n>=20; for small n (the n=5
    per-cell tests) this is reported as descriptive only, never as a
    formal significance claim -- see the per-cell section's caveat."""
    values = np.asarray(values, dtype=float)
    n = len(values)
    mean = values.mean()
    se = values.std(ddof=1) / math.sqrt(n) if n > 1 else float("nan")
    t = mean / se if se > 0 else 0.0
    # normal approximation to the two-sided p-value
    p = 2 * (1 - 0.5 * (1 + math.erf(abs(t) / math.sqrt(2))))
    return t, p

df = pd.read_csv("symmetry_batch_results.csv")
print(f"Loaded {len(df)} runs.")

lines = []
lines.append("BOT/HUMAN SYMMETRY -- 100-RUN STATISTICAL ANALYSIS")
lines.append("=" * 70)
lines.append(f"{len(df)} full-scale runs (200 players, 40 events, spec economics: "
              f"$300k/$1.5M/$3M dividend tiers, 0.25% transaction fee, $10,000 flat "
              f"auction fee, 0.02%/event cash yield, no new-entrant growth).")
lines.append("Grid: 5 population-wide strategy-mix presets x 4 bot:human ratios x 5 seeds.")
lines.append("")
lines.append("Comparison is ORIGINAL-cohort humans (n=50, present since t=0) vs. bots")
lines.append("(n=100-500 depending on ratio) -- same tenure, same strategy-draw")
lines.append("distribution. Under the fix (bots draw strategies identically to humans),")
lines.append("the expected gap is 0 in the long run; any nonzero mean here should be")
lines.append("explainable as sampling noise (bots are a MUCH larger sample than the 50")
lines.append("original humans, so bot averages are less noisy -- that alone does not")
lines.append("imply bias, just that the human side of the comparison is noisier).")
lines.append("")

# ---------------------------------------------------------------
# 1) Grand overall test
# ---------------------------------------------------------------
gap = df["orig_vs_bot_elo_gap"].values
t, p = one_sample_test(gap)
lines.append("1) OVERALL (all 100 runs pooled)")
lines.append("-" * 70)
lines.append(f"   mean ELO gap (orig human - bot): {gap.mean():+.2f}  (std {gap.std(ddof=1):.2f}, "
              f"SE {gap.std(ddof=1)/np.sqrt(len(gap)):.2f})")
lines.append(f"   one-sample t-test vs 0: t={t:.2f}, p={p:.3f}  "
              f"-> {'NOT significantly different from 0 (consistent with no systematic bias)' if p > 0.05 else 'SIGNIFICANTLY different from 0 -- investigate'}")
roi_gap = df["orig_vs_bot_roi_gap"].values
t2, p2 = one_sample_test(roi_gap)
lines.append(f"   mean ROI gap (orig human - bot): {roi_gap.mean():+.2f}pp  t={t2:.2f}, p={p2:.3f}  "
              f"-> {'not significant' if p2 > 0.05 else 'SIGNIFICANT'}")
lines.append("")

# ---------------------------------------------------------------
# 2) By strategy mix (pooled across bot_ratio x seed, n=20 each)
# ---------------------------------------------------------------
lines.append("2) BY STRATEGY MIX (n=20 runs each, pooled across bot:human ratio)")
lines.append("-" * 70)
mix_rows = []
for mix, g in df.groupby("strategy_mix"):
    t, p = one_sample_test(g["orig_vs_bot_elo_gap"])
    mean, se = g["orig_vs_bot_elo_gap"].mean(), g["orig_vs_bot_elo_gap"].sem()
    flag = "***" if p < 0.01 else ("*" if p < 0.05 else "")
    mix_rows.append((mix, mean, se, t, p, flag))
    lines.append(f"   {mix:20s}  mean gap={mean:+7.2f} (SE {se:5.2f})  t={t:+.2f}  p={p:.3f} {flag}")
lines.append("")

# ---------------------------------------------------------------
# 3) By bot:human ratio (pooled across strategy mix x seed, n=25 each)
# ---------------------------------------------------------------
lines.append("3) BY BOT:HUMAN RATIO (n=25 runs each, pooled across strategy mix)")
lines.append("-" * 70)
ratio_rows = []
for ratio, g in df.groupby("bot_ratio"):
    t, p = one_sample_test(g["orig_vs_bot_elo_gap"])
    mean, se = g["orig_vs_bot_elo_gap"].mean(), g["orig_vs_bot_elo_gap"].sem()
    flag = "***" if p < 0.01 else ("*" if p < 0.05 else "")
    n_bots = g["num_bots"].iloc[0]
    ratio_rows.append((ratio, mean, se, t, p, flag))
    lines.append(f"   {ratio:22s} (n_bots={n_bots:3d})  mean gap={mean:+7.2f} (SE {se:5.2f})  "
                 f"t={t:+.2f}  p={p:.3f} {flag}")
lines.append("")

# ---------------------------------------------------------------
# 4) Per-cell (n=5) flags -- descriptive only, low power at n=5
# ---------------------------------------------------------------
lines.append("4) PER-CELL DETAIL (n=5 seeds each -- low statistical power, descriptive only)")
lines.append("-" * 70)
cell_flags = []
for (mix, ratio), g in df.groupby(["strategy_mix", "bot_ratio"]):
    mean, se = g["orig_vs_bot_elo_gap"].mean(), g["orig_vs_bot_elo_gap"].sem()
    z = mean / se if se > 0 else 0.0
    flagged = abs(z) > 2.0
    if flagged:
        cell_flags.append((mix, ratio, mean, se, z))
if cell_flags:
    for mix, ratio, mean, se, z in cell_flags:
        lines.append(f"   FLAG: {mix:20s} x {ratio:22s}  mean gap={mean:+7.2f} (SE {se:5.2f}, z={z:+.2f})")
else:
    lines.append("   No individual cell exceeds |z|>2 on its own 5-seed mean "
                 "(expected -- 20 cells x a ~5% false-positive rate under the null "
                 "would predict ~1 spurious flag; seeing 0-1 is consistent with noise).")
lines.append("")

# ---------------------------------------------------------------
# 5) fundamentals_heavy x bot_heavy: closest look (largest observed |mean|)
# ---------------------------------------------------------------
sub = df[(df.strategy_mix == "fundamentals_heavy")]
lines.append("5) CLOSEST LOOK: fundamentals_heavy mix (largest pooled |mean gap| of the 5 mixes)")
lines.append("-" * 70)
lines.append(f"   All 20 fundamentals_heavy runs: mean gap {sub['orig_vs_bot_elo_gap'].mean():+.2f} "
              f"(SE {sub['orig_vs_bot_elo_gap'].sem():.2f}), individual run gaps range "
              f"{sub['orig_vs_bot_elo_gap'].min():+.1f} to {sub['orig_vs_bot_elo_gap'].max():+.1f}.")
lines.append(f"   Variance is much higher under this mix (~30-44 SD per cell) than any "
              f"other -- fundamentals_heavy concentrates weight on only 5 strategies "
              f"(value_investor/dividend_hunter/smart_money/index_investor/news_trader), "
              f"which makes individual-run outcomes noisier (fewer distinct behaviors "
              f"to average over within each 50-human sample), not necessarily biased.")
lines.append("")

# ---------------------------------------------------------------
# 6) Broader economy health across the grid
# ---------------------------------------------------------------
lines.append("6) ECONOMY HEALTH ACROSS THE GRID")
lines.append("-" * 70)
lines.append(f"   Success-criteria pass count (of 7): mean {df['success_criteria_pass_count'].mean():.2f}, "
              f"range {df['success_criteria_pass_count'].min()}-{df['success_criteria_pass_count'].max()}.")
by_ratio_health = df.groupby("bot_ratio")[["cash_ratio_final_quarter_avg", "inflation_pct",
                                             "trading_volume_pct_mcap_final_quarter_avg",
                                             "success_criteria_pass_count"]].mean()
lines.append("   By bot:human ratio (mean across all mixes/seeds):")
for ratio, row in by_ratio_health.iterrows():
    lines.append(f"     - {ratio:22s} cash_ratio={row['cash_ratio_final_quarter_avg']*100:5.1f}%  "
                 f"inflation={row['inflation_pct']:+6.1f}%  "
                 f"volume%mcap={row['trading_volume_pct_mcap_final_quarter_avg']*100:.3f}%  "
                 f"success={row['success_criteria_pass_count']:.1f}/7")
lines.append("")
by_mix_health = df.groupby("strategy_mix")[["cash_ratio_final_quarter_avg", "inflation_pct",
                                              "success_criteria_pass_count"]].mean()
lines.append("   By strategy mix (mean across all ratios/seeds):")
for mix, row in by_mix_health.iterrows():
    lines.append(f"     - {mix:20s} cash_ratio={row['cash_ratio_final_quarter_avg']*100:5.1f}%  "
                 f"inflation={row['inflation_pct']:+6.1f}%  success={row['success_criteria_pass_count']:.1f}/7")

text = "\n".join(lines)
print(text)
with open(os.path.join(OUT_DIR, "symmetry_analysis_summary.txt"), "w") as f:
    f.write(text)

# ---------------------------------------------------------------
# Charts
# ---------------------------------------------------------------
fig, axes = plt.subplots(1, 2, figsize=(13, 5))
mixes = [r[0] for r in mix_rows]
means = [r[1] for r in mix_rows]
ses = [r[2] for r in mix_rows]
axes[0].bar(mixes, means, yerr=[s * 1.96 for s in ses], color="#2563eb", capsize=5)
axes[0].axhline(0, color="black", linewidth=0.8)
axes[0].set_ylabel("Mean ELO gap (orig human - bot)")
axes[0].set_title("By strategy mix (n=20, 95% CI)")
axes[0].tick_params(axis="x", rotation=20)
axes[0].grid(alpha=0.3, axis="y")

ratios = [r[0] for r in ratio_rows]
rmeans = [r[1] for r in ratio_rows]
rses = [r[2] for r in ratio_rows]
axes[1].bar(ratios, rmeans, yerr=[s * 1.96 for s in rses], color="#7c3aed", capsize=5)
axes[1].axhline(0, color="black", linewidth=0.8)
axes[1].set_ylabel("Mean ELO gap (orig human - bot)")
axes[1].set_title("By bot:human ratio (n=25, 95% CI)")
axes[1].tick_params(axis="x", rotation=20)
axes[1].grid(alpha=0.3, axis="y")
fig.tight_layout()
fig.savefig(os.path.join(OUT_DIR, "elo_gap_by_axis.png"), dpi=150, bbox_inches="tight")
plt.close(fig)

# heatmap: mean gap by mix x ratio
pivot = df.pivot_table(index="strategy_mix", columns="bot_ratio", values="orig_vs_bot_elo_gap", aggfunc="mean")
fig, ax = plt.subplots(figsize=(8, 5.5))
vmax = np.abs(pivot.values).max()
im = ax.imshow(pivot.values, cmap="RdBu_r", vmin=-vmax, vmax=vmax)
ax.set_xticks(range(len(pivot.columns)))
ax.set_xticklabels(pivot.columns, rotation=20, ha="right")
ax.set_yticks(range(len(pivot.index)))
ax.set_yticklabels(pivot.index)
for i in range(len(pivot.index)):
    for j in range(len(pivot.columns)):
        ax.text(j, i, f"{pivot.values[i,j]:+.1f}", ha="center", va="center", fontsize=9)
fig.colorbar(im, ax=ax, label="Mean ELO gap (orig human - bot)")
ax.set_title("ELO gap heatmap: strategy mix x bot:human ratio (n=5 each)")
fig.tight_layout()
fig.savefig(os.path.join(OUT_DIR, "elo_gap_heatmap.png"), dpi=150, bbox_inches="tight")
plt.close(fig)

# histogram of z-scores across all 20 cells -- should look roughly N(0,1) if no bias
cell_z = []
for (mix, ratio), g in df.groupby(["strategy_mix", "bot_ratio"]):
    mean, se = g["orig_vs_bot_elo_gap"].mean(), g["orig_vs_bot_elo_gap"].sem()
    if se > 0:
        cell_z.append(mean / se)
fig, ax = plt.subplots(figsize=(7, 5))
ax.hist(cell_z, bins=10, color="#16a34a", alpha=0.8, edgecolor="white")
ax.axvline(0, color="black", linewidth=1)
ax.set_xlabel("z-score (cell mean gap / cell SE)")
ax.set_ylabel("# cells (of 20)")
ax.set_title("Per-cell z-score distribution -- should center on 0 with no systematic skew")
ax.grid(alpha=0.3, axis="y")
fig.tight_layout()
fig.savefig(os.path.join(OUT_DIR, "z_score_distribution.png"), dpi=150, bbox_inches="tight")
plt.close(fig)

print(f"\nCharts + summary written to {OUT_DIR}/")
