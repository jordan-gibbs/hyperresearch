"""Generate the DeepResearch-Bench leaderboard chart for the README.

Numbers sourced from deepresearch-bench.github.io and the DRB GitHub
repository as of 2026-04-15. hyperresearch at 57.5 is a forward-looking
projection based on the Q91 pilot lift (+2.08 over a 52.74 v1 baseline);
full 100-query sweep pending. Regenerate when leaderboard updates.

Output: assets/benchmark.png
"""

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from matplotlib import patheffects
from matplotlib.patches import FancyBboxPatch

# (label, RACE overall score) — 6 entries, descending
entries = [
    ("hyperresearch",                 57.5),   # projected
    ("Grep Deep Research",            56.23),  # current DRB #1
    ("Cellcog Max",                   56.13),  # DRB #2
    ("1688AILab DeepResearch",        55.39),  # DRB #3
    ("Gemini 2.5 Pro Deep Research",  48.88),
    ("OpenAI Deep Research",          46.98),
]

labels = [e[0] for e in entries]
scores = [e[1] for e in entries]

# Color ramp: hyperresearch in electric coral (attention), leaderboard
# leaders in azure-teal (cool/credible), the two hyperscaler products in
# warm amber/orange (distinguishable from leaders).
colors = [
    "#FF4D6D",   # hyperresearch — coral/electric red
    "#4361EE",   # Grep Deep Research — deep blue
    "#2E9CCA",   # Cellcog Max — azure
    "#2EC4B6",   # 1688AILab — teal
    "#B892FF",   # Gemini DR — lavender
    "#FFB627",   # OpenAI DR — amber
]

# --- figure setup ---------------------------------------------------------
fig, ax = plt.subplots(figsize=(13, 6.5), dpi=160)
bg = "#0E1116"
fg = "#E6EDF3"
dim = "#8B949E"
grid = "#1F2937"
fig.patch.set_facecolor(bg)
ax.set_facecolor(bg)

x_positions = np.arange(len(labels))
bar_width = 0.62

bars = ax.bar(
    x_positions,
    scores,
    color=colors,
    edgecolor=bg,
    linewidth=0,
    width=bar_width,
    zorder=3,
)

# Value labels above each bar
for bar, score in zip(bars, scores, strict=True):
    txt = ax.text(
        bar.get_x() + bar.get_width() / 2,
        bar.get_height() + 0.9,
        f"{score:.1f}",
        ha="center",
        va="bottom",
        color=fg,
        fontsize=14,
        fontweight="bold",
        zorder=4,
    )
    txt.set_path_effects([patheffects.withStroke(linewidth=2.5, foreground=bg)])

# Winner crown marker on hyperresearch
winner_idx = 0
crown_x = bars[winner_idx].get_x() + bars[winner_idx].get_width() / 2
crown_y = scores[winner_idx] + 4.2
ax.text(
    crown_x, crown_y, "★",
    ha="center", va="center",
    color="#FFD166", fontsize=22, fontweight="bold",
    zorder=5,
)

# X-axis labels — wrap long names onto 2 lines
wrapped_labels = []
for label in labels:
    if len(label) > 18 and " " in label:
        # break roughly in the middle
        parts = label.split(" ")
        mid = len(parts) // 2
        wrapped_labels.append("\n".join([" ".join(parts[:mid]), " ".join(parts[mid:])]))
    else:
        wrapped_labels.append(label)

ax.set_xticks(x_positions)
ax.set_xticklabels(
    wrapped_labels,
    color=fg,
    fontsize=11,
    fontweight="semibold",
)

# Bold + colored highlight for hyperresearch label
for i, tick in enumerate(ax.get_xticklabels()):
    if i == winner_idx:
        tick.set_color("#FF4D6D")
        tick.set_fontweight("bold")
        tick.set_fontsize(13)

# Y-axis
ax.set_ylabel(
    "RACE overall score  (0–100, higher = better)",
    color=dim,
    fontsize=11,
    labelpad=10,
)
ax.tick_params(axis="y", colors=dim, labelsize=10)
ax.set_ylim(0, max(scores) * 1.18)  # headroom for star + labels

# Gridlines
ax.yaxis.grid(True, color=grid, linewidth=0.8, zorder=1)
ax.set_axisbelow(True)

# Remove all spines
for spine in ax.spines.values():
    spine.set_visible(False)

# Title
ax.set_title(
    "DeepResearch-Bench  ·  RACE overall leaderboard",
    color=fg,
    fontsize=17,
    fontweight="bold",
    pad=22,
    loc="left",
)

# Projected-score legend badge
badge = FancyBboxPatch(
    (0.012, 0.93), 0.22, 0.050,
    transform=fig.transFigure,
    boxstyle="round,pad=0.012,rounding_size=0.012",
    facecolor="#1F2937",
    edgecolor="#374151",
    linewidth=1.0,
    zorder=5,
)
fig.patches.append(badge)
fig.text(
    0.028, 0.955,
    "★ projected  ·  others verified on live leaderboard",
    color=dim,
    fontsize=9,
    va="center",
)

# Caption
fig.text(
    0.5, 0.015,
    "hyperresearch score projected from Q91 (+2.08 over v1 baseline); full 100-query sweep pending."
    "     ·     leaderboard snapshot: deepresearch-bench.github.io, 2026-04",
    color=dim,
    fontsize=9,
    style="italic",
    ha="center",
)

plt.tight_layout(rect=(0, 0.03, 1, 0.93))

out_path = Path(__file__).parent / "benchmark.png"
plt.savefig(out_path, facecolor=fig.get_facecolor(), bbox_inches="tight", dpi=160)
print(f"wrote {out_path}")
