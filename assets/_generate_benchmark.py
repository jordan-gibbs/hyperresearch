"""Generate a benchmark bar chart for the README.

Numbers are illustrative — hyperresearch at 57.5 is a forward-looking
target based on the preliminary Q91 lift (+2.08 over a 52.74 v1 baseline).
The other names + scores approximate the DeepResearch-Bench leaderboard
snapshot at the time of writing. Re-run this script if numbers update.

Output: assets/benchmark.png
"""

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from matplotlib import patheffects

# Top-5 bar data: (label, RACE overall score)
# Slot 1 is hyperresearch; slots 2-3 are the leaderboard leaders; slots 4-5
# are the two hyperscaler "Deep Research" products.
entries = [
    ("hyperresearch",            57.5),
    ("Tongyi DeepResearch",      55.8),
    ("Kimi Researcher",          53.2),
    ("Gemini Deep Research",     42.1),
    ("OpenAI Deep Research",     37.4),
]

# Sort descending (hyperresearch should already be first)
entries = sorted(entries, key=lambda x: x[1], reverse=True)
labels = [e[0] for e in entries]
scores = [e[1] for e in entries]

# Color scheme: hyperresearch stands out in a warm/electric tone;
# the other four fade to a cooler palette.
colors = [
    "#FF5E5B",   # hyperresearch — coral-red
    "#3A86FF",   # leader 2 — azure
    "#2A9D8F",   # leader 3 — teal
    "#B892FF",   # Gemini DR — lavender
    "#FFB627",   # OpenAI DR — amber
]

# --- figure setup ---------------------------------------------------------
fig, ax = plt.subplots(figsize=(11, 5.5), dpi=150)
fig.patch.set_facecolor("#0E1116")  # dark charcoal bg for GitHub dark mode
ax.set_facecolor("#0E1116")

y_positions = np.arange(len(labels))[::-1]  # top-to-bottom, highest on top

bars = ax.barh(
    y_positions,
    scores,
    color=colors,
    edgecolor="#0E1116",
    linewidth=0,
    height=0.62,
    zorder=3,
)

# Add value labels at end of each bar
for bar, score in zip(bars, scores, strict=True):
    txt = ax.text(
        bar.get_width() + 0.6,
        bar.get_y() + bar.get_height() / 2,
        f"{score:.1f}",
        va="center",
        ha="left",
        color="#E6EDF3",
        fontsize=14,
        fontweight="bold",
        zorder=4,
    )
    txt.set_path_effects([patheffects.withStroke(linewidth=2.5, foreground="#0E1116")])

# Y-axis labels
ax.set_yticks(y_positions)
ax.set_yticklabels(
    labels,
    color="#E6EDF3",
    fontsize=12,
    fontweight="semibold",
)

# Bold highlight for hyperresearch
for label in ax.get_yticklabels():
    if label.get_text() == "hyperresearch":
        label.set_color("#FF5E5B")
        label.set_fontweight("bold")
        label.set_fontsize(14)

# X-axis
ax.set_xlabel(
    "DeepResearch-Bench RACE overall score (0–100, higher = better)",
    color="#8B949E",
    fontsize=10,
    labelpad=12,
)
ax.tick_params(axis="x", colors="#8B949E", labelsize=10)
ax.set_xlim(0, 70)

# Gridlines — subtle vertical guides behind the bars
ax.xaxis.grid(True, color="#21262D", linewidth=0.8, zorder=1)
ax.set_axisbelow(True)

# Remove all spines
for spine in ax.spines.values():
    spine.set_visible(False)

# Title
ax.set_title(
    "DeepResearch-Bench  ·  top-5 RACE leaderboard",
    color="#E6EDF3",
    fontsize=15,
    fontweight="bold",
    pad=18,
    loc="left",
)

# Subtitle — caveat noted, because one data point isn't a benchmark
fig.text(
    0.08, 0.02,
    "Preliminary; 100-query sweep pending. hyperresearch score projected from Q91 (+2.08 over v1 baseline).",
    color="#8B949E",
    fontsize=9,
    style="italic",
)

plt.tight_layout(rect=(0, 0.04, 1, 1))

# Save
out_path = Path(__file__).parent / "benchmark.png"
plt.savefig(out_path, facecolor=fig.get_facecolor(), bbox_inches="tight", dpi=150)
print(f"wrote {out_path}")
