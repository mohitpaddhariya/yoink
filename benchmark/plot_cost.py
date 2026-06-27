"""Generate the yoink cost benchmark graph from measured data.

Run:  uv run --with matplotlib python benchmark/plot_cost.py
Native cost = transcript tokens * Opus input price ($5/MTok) — what loading the other
session's transcript into your live Opus context costs. yoink cost = measured
total_cost_usd of the isolated `claude -p --resume` recall (Haiku), which returns only
~300 tokens to your context. All points measured on real sessions.
"""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

OPUS_IN = 5.0 / 1e6  # $/token, Opus input

# (session size in tokens, measured yoink cost $) — Haiku recall on real sessions
yoink = [(1845, 0.0214), (2041, 0.0219), (6197, 0.0296), (81351, 0.1197)]
yoink_cached = (267718, 0.076)   # a 268K-token session, warm cache (default model)
yx = [p[0] for p in yoink]; yy = [p[1] for p in yoink]

sizes = np.logspace(3, 6.2, 200)          # 1K .. ~1.5M tokens
native = sizes * OPUS_IN

CTX = 1_000_000  # the asking session's usable context (Opus 1M); beyond this native overflows

fig, ax = plt.subplots(figsize=(9, 5.6))
ax.plot(sizes, native, color="#d11", lw=2.4, label="Native — load transcript into your Opus session  ($5/MTok)")
ax.plot(yx, yy, "o-", color="#1a8f3c", lw=2.4, ms=7, label="yoink — isolated recall (Haiku), returns ~300 tokens")
# dashed projection of yoink staying low for larger sessions + the measured cached point
ax.plot([yx[-1], yoink_cached[0]], [yy[-1], yoink_cached[1]], "--", color="#1a8f3c", lw=1.6)
ax.plot(*yoink_cached, "*", color="#1a8f3c", ms=15)
ax.annotate("268K-token session,\nwarm cache: $0.076", yoink_cached, textcoords="offset points",
            xytext=(-12, -38), fontsize=8, color="#1a8f3c", ha="center")

ax.axvspan(CTX, sizes[-1], color="#999", alpha=0.18)
ax.text(CTX*1.05, 0.0025, "native impossible\n(context overflow)", fontsize=8, color="#555", va="bottom")

# break-even marker
be = 0.022 / OPUS_IN
ax.axvline(be, color="#888", ls=":", lw=1)
ax.annotate("break-even\n~5K tokens", (be, 0.0016), fontsize=8, color="#555", ha="center")

# widening-gap callout at 81K
ax.annotate("3.4× cheaper", (81351, 0.40), (81351, 0.40), fontsize=9, color="#d11", ha="center")

ax.set_xscale("log"); ax.set_yscale("log")
ax.set_xlabel("Session size (tokens)")
ax.set_ylabel("Cost per recall (USD)")
ax.set_title("Cost to answer “what did the other session conclude?”  —  native vs yoink")
ax.grid(True, which="both", alpha=0.25)
ax.legend(loc="upper left", fontsize=8.5, framealpha=0.95)
ax.set_xlim(1e3, 1.5e6); ax.set_ylim(1e-3, 1e1)
fig.text(0.5, -0.02, "Measured on real Claude sessions. Native = transcript tokens × Opus input price; "
         "yoink = measured total_cost_usd of the forked --resume recall.", ha="center", fontsize=7.5, color="#666")
fig.tight_layout()
fig.savefig("/Users/you/yoink/benchmark/cost.png", dpi=140, bbox_inches="tight")
print("wrote benchmark/cost.png")
