"""Regenerate benchmark/cost.png from MEASURED data (results/cost.json + results/stress.json).

Run after costbench.py and stress.py (or via run.py). Every point is a real measured
`total_cost_usd`: yoink's Haiku recall vs dumping the whole transcript into Opus ("read it
yourself"). The red line is the Opus input price — what those transcript tokens cost just to
sit in your live context — and the measured full-transcript points should track it.

    uv run --with matplotlib python benchmark/plot_cost.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

RESULTS = Path(__file__).parent / "results"
OUT = Path(__file__).parent / "cost.png"
PURPLE, RED, INK, MUTE, GRID = "#8B5CF6", "#EF4444", "#22272E", "#9AA0AA", "#ECEEF1"
OPUS_IN = 5.0 / 1e6  # $/token, Opus input — the cost of N transcript tokens in your live context


def _load() -> tuple[list, list]:
    cost = json.loads((RESULTS / "cost.json").read_text())
    yoink = [(p["size_tokens"], p["yoink_cost"]) for p in cost["points"] if p.get("yoink_cost") is not None]
    full = [(p["size_tokens"], p["full_transcript_cost"]) for p in cost["points"] if p.get("full_transcript_cost") is not None]
    try:  # stress adds measured yoink points at the larger sizes
        stress = json.loads((RESULTS / "stress.json").read_text())
        yoink += [(p["size_tokens"], p["yoink_cost"]) for p in stress.get("cost_points", []) if p.get("yoink_cost") is not None]
    except (OSError, ValueError):
        pass
    return sorted(set(yoink)), sorted(set(full))


def main() -> int:
    if not (RESULTS / "cost.json").exists():
        print("no results/cost.json — run `python benchmark/costbench.py` first", file=sys.stderr)
        return 1
    yoink, full = _load()
    if not yoink or not full:
        print("not enough measured points to plot", file=sys.stderr)
        return 1

    yx, yy = zip(*yoink)
    fx, fy = zip(*full)
    lo, hi = min(yx + fx), max(yx + fx)

    plt.rcParams.update({"font.family": "DejaVu Sans", "axes.edgecolor": GRID, "figure.dpi": 170})
    fig, ax = plt.subplots(figsize=(10, 6))
    fig.patch.set_facecolor("white")
    ax.set_facecolor("white")
    ax.set_xscale("log")
    ax.set_yscale("log")

    # faint reference: the bare token price of the transcript sitting in your Opus context
    sizes = np.logspace(np.log10(lo * 0.7), np.log10(hi * 1.5), 200)
    ax.plot(sizes, sizes * OPUS_IN, color=MUTE, lw=1.4, ls=(0, (1, 3)), alpha=0.7,
            zorder=1, label="just the tokens in context")
    # measured: the two real ways to answer the question
    ax.plot(fx, fy, color=RED, lw=3.0, marker="o", ms=8, mfc="white", mec=RED, mew=2.4,
            zorder=4, solid_capstyle="round", label="read it yourself (Opus)")
    ax.plot(yx, yy, color=PURPLE, lw=3.0, marker="o", ms=8, mfc="white", mec=PURPLE, mew=2.4,
            zorder=5, solid_capstyle="round", label="yoink (Haiku recall)")

    # headline gap at the largest measured size
    big = max(full, key=lambda p: p[0])
    y_at_big = min((p for p in yoink if p[0] >= big[0] * 0.5), key=lambda p: abs(p[0] - big[0]), default=yoink[-1])
    factor = big[1] / y_at_big[1] if y_at_big[1] else 0
    if factor >= 2:
        ax.annotate("", xy=(big[0], big[1]), xytext=(big[0], y_at_big[1]),
                    arrowprops=dict(arrowstyle="<->", color=INK, lw=1.6))
        ax.text(big[0] * 1.15, (big[1] * y_at_big[1]) ** 0.5, f"{factor:.1f}× cheaper",
                fontsize=12.5, color=INK, fontweight="bold", va="center")

    leg = ax.legend(loc="upper left", frameon=False, fontsize=11.5, handlelength=1.6, borderaxespad=0.8)
    for line in leg.get_lines():
        line.set_linewidth(3.0)

    ax.xaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v/1000:.0f}K" if v < 1e6 else f"{v/1e6:.0f}M"))
    ax.yaxis.set_major_formatter(plt.FuncFormatter(
        lambda v, _: (f"{v*100:.0f}¢" if v < 1 else f"${v:.0f}")))
    ax.grid(True, which="major", color=GRID, lw=1)
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)
    ax.set_title("Asking another session beats reading it yourself", fontsize=15.5, fontweight="bold",
                 color=INK, loc="left", pad=26)
    ax.text(0, 1.04, "cost to answer one question — measured on real Claude sessions",
            transform=ax.transAxes, fontsize=10.5, color=MUTE)

    fig.tight_layout()
    fig.savefig(OUT, dpi=170, bbox_inches="tight", facecolor="white")
    print("wrote benchmark/cost.png")
    return 0


if __name__ == "__main__":
    sys.exit(main())
