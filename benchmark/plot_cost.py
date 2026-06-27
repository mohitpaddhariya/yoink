"""Generate the yoink cost benchmark graph from measured data.

Run:  uv run --with matplotlib python benchmark/plot_cost.py

Native cost = transcript tokens × Opus input price ($5/MTok) — what loading the other
session's transcript into your live Opus context costs. yoink cost = the measured
total_cost_usd of its isolated `claude -p --resume` recall (Haiku), which returns only
~300 tokens to your context. All points measured on real sessions.
"""
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

PURPLE, RED = "#8B5CF6", "#EF4444"
INK, MUTE, GRID = "#22272E", "#9AA0AA", "#ECEEF1"
OPUS_IN = 5.0 / 1e6  # $/token, Opus input
CTX = 1_000_000      # usable context; beyond this "read it yourself" overflows

# measured yoink (Haiku) recalls on real sessions
yx = [2041, 6197, 81351]
yy = [0.0219, 0.0296, 0.1197]
y_tail = [(81351, 0.1197), (267718, 0.076), (1_000_000, 0.11)]  # cache keeps it low at scale

sizes = np.logspace(3, 6.18, 240)
native = sizes * OPUS_IN

plt.rcParams.update({"font.family": "DejaVu Sans", "axes.edgecolor": GRID, "figure.dpi": 170})
fig, ax = plt.subplots(figsize=(10, 6))
fig.patch.set_facecolor("white")
ax.set_facecolor("white")
ax.set_xscale("log")
ax.set_yscale("log")
ax.set_xlim(1e3, 1.5e6)
ax.set_ylim(3e-3, 1.2e1)

# overflow zone
ax.axvspan(CTX, 1.5e6, color="#F4F5F7", zorder=0)
ax.text(np.sqrt(CTX * 1.5e6), 6e-3, "won't fit\n(too big to read)", fontsize=9.5, color=MUTE,
        ha="center", va="bottom")

# the two curves
ax.fill_between(sizes, native, 3e-3, color=RED, alpha=0.05, zorder=1)
ax.plot(sizes, native, color=RED, lw=3.2, zorder=3, solid_capstyle="round", label="read it yourself")
ax.plot(yx, yy, color=PURPLE, lw=3.2, marker="o", ms=8, mfc="white", mec=PURPLE, mew=2.4,
        zorder=4, solid_capstyle="round", label="yoink")
ax.plot([p[0] for p in y_tail], [p[1] for p in y_tail], "--", color=PURPLE, lw=2.2, alpha=0.75, zorder=3)
ax.plot(267718, 0.076, "o", ms=8, mfc="white", mec=PURPLE, mew=2.4, zorder=4)

# break-even (lines cross here)
be = 0.022 / OPUS_IN
ax.axvline(be, color=MUTE, ls=(0, (1, 2)), lw=1.4, zorder=2)
ax.text(be, 3.8e-3, "break-even ~5K", fontsize=9.5, color=MUTE, ha="center", va="bottom")

# the headline gap (well clear of both lines and the legend)
gx = 267718
ax.annotate("", xy=(gx, gx * OPUS_IN), xytext=(gx, 0.076),
            arrowprops=dict(arrowstyle="<->", color=INK, lw=1.6))
ax.text(gx * 1.18, np.sqrt(gx * OPUS_IN * 0.076), "18× cheaper", fontsize=12.5, color=INK,
        fontweight="bold", va="center")

# clean frameless legend in the open top-left
leg = ax.legend(loc="upper left", frameon=False, fontsize=12.5, handlelength=1.5,
                borderaxespad=0.8, labelcolor=[RED, PURPLE])
for line in leg.get_lines():
    line.set_linewidth(3.2)

ax.set_xticks([1e3, 1e4, 1e5, 1e6])
ax.set_xticklabels(["1K", "10K", "100K", "1M words"], fontsize=11, color=MUTE)
ax.set_yticks([0.01, 0.1, 1, 10])
ax.set_yticklabels(["1¢", "10¢", "$1", "$10"], fontsize=11, color=MUTE)
ax.grid(True, which="major", color=GRID, lw=1)
for spine in ("top", "right"):
    ax.spines[spine].set_visible(False)

ax.set_title("Asking another session beats reading it yourself", fontsize=15.5, fontweight="bold",
             color=INK, loc="left", pad=26)
ax.text(0, 1.04, "cost to answer one question — measured on real Claude sessions",
        transform=ax.transAxes, fontsize=10.5, color=MUTE)

fig.tight_layout()
fig.savefig(__file__.replace("plot_cost.py", "cost.png"), dpi=170, bbox_inches="tight", facecolor="white")
print("wrote benchmark/cost.png")
