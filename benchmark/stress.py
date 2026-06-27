"""Track C — long-context stress (conclusion-in-haystack).

Buries a known conclusion in synthetic sessions of growing size and grades recall + measures
cost. Reports an accuracy heatmap (size x evidence position), plus distractor-count, temporal-
update, and unanswerable variants, and emits measured cost-by-size points for cost.png.

v1 ceiling is 100K tokens. ponytail: 500K/1M rows are deferred — seeding a 1M-token session is a
~$1 Opus-scale write each; add them only when a reviewer asks for the tail of the curve.

    uv run python benchmark/stress.py
"""
from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "eval"))

import progress
import sessions
import usage
from evalkit import grade
from yoink import answerer, config
from yoink.prompts import build_recall_prompt, parse_answer

RESULTS_DIR = Path(__file__).parent / "results"
STRESS_JSON = RESULTS_DIR / "stress.json"
STRESS_PNG = Path(__file__).parent / "stress.png"

SIZES = (5_000, 25_000, 100_000)
POSITIONS = ("start", "mid", "end")
CONCL, DEAD = "connection pool exhaustion", "postgres"
Q = "What did we conclude was causing the timeouts?"


def _recall_measured(ref: dict, question: str, model: str):
    cmd = answerer._build_command(ref["session_id"], build_recall_prompt(question), model=model)
    run = usage.measure(cmd, cwd=ref["cwd"], timeout=900)
    m = usage.envelope_metrics(run.stdout) or {}
    return parse_answer(m.get("result_text") or ""), (m.get("cost_usd") or 0.0), run.latency_ms


def _cells():
    cells = []
    for s in SIZES:  # the size x position heatmap (distractors fixed at 10)
        for p in POSITIONS:
            cells.append(("grid", s, p, 10, sessions.make_haystack(
                fixture_id=f"hs-{s}-{p}", question=Q, target_tokens=s, position=p,
                distractors=10, conclusion=CONCL, deadend=DEAD)))
    for d in (0, 3):  # distractor sweep at 25K-end (10 already in the grid)
        cells.append(("distractor", 25_000, "end", d, sessions.make_haystack(
            fixture_id=f"hs-d{d}", question=Q, target_tokens=25_000, position="end",
            distractors=d, conclusion=CONCL, deadend=DEAD)))
    cells.append(("update", 25_000, "end", 10, sessions.make_haystack(  # recency at scale
        fixture_id="hs-update", question=Q, target_tokens=25_000, position="end",
        distractors=10, conclusion=CONCL, superseded="dns misconfiguration")))
    cells.append(("unanswerable", 25_000, "mid", 10, sessions.make_haystack(  # abstention at scale
        fixture_id="hs-open", question=Q, target_tokens=25_000, position="mid",
        distractors=10, conclusion=None, deadend=DEAD)))
    return cells


def _plot(grid: dict) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    mat = [[grid.get((s, p), {}).get("passed", 0) * 100 for p in POSITIONS] for s in SIZES]
    fig, ax = plt.subplots(figsize=(7, 5))
    ax.imshow(mat, cmap="RdYlGn", vmin=0, vmax=100, aspect="auto")
    ax.set_xticks(range(len(POSITIONS)), POSITIONS)
    ax.set_yticks(range(len(SIZES)), [f"{s // 1000}K" for s in SIZES])
    ax.set_xlabel("evidence position")
    ax.set_ylabel("transcript size")
    ax.set_title("yoink recall accuracy in a haystack", fontweight="bold", loc="left")
    for i, s in enumerate(SIZES):
        for j, p in enumerate(POSITIONS):
            cell = grid.get((s, p), {})
            mark = "✓" if cell.get("passed") else "✗"
            ax.text(j, i, f"{mark}\n${cell.get('cost_usd', 0):.3f}", ha="center", va="center", fontsize=10)
    fig.tight_layout()
    fig.savefig(STRESS_PNG, dpi=160, bbox_inches="tight")
    print(f"wrote {STRESS_PNG.name}")


def main(argv: list[str]) -> int:
    model = config.load_config().model
    cells = _cells()
    print(f"track C: {len(cells)} haystack cells (recall model = {model})")

    tracker = progress.Tracker(n_phases=2)
    refs = sessions.build_all([c[4] for c in cells], tracker=tracker)

    tracker.phase("stress recall (track C)", len(cells))
    results, grid = [], {}
    for kind, size, pos, dist, fx in cells:
        ans, cost, lat = _recall_measured(refs[fx.id], fx.question, model)
        passed, _ = grade(fx, ans)
        row = {"kind": kind, "size_tokens": size, "position": pos, "distractors": dist,
               "passed": passed, "cost_usd": cost, "latency_ms": lat, "abstained": ans.no_conclusion}
        results.append(row)
        if kind == "grid":
            grid[(size, pos)] = row
        tracker.step(f"{kind} {size//1000}K {pos}")
    tracker.done_phase()

    # measured cost-by-size points (mean yoink recall cost across positions) for cost.png
    cost_points = [{"size_tokens": s,
                    "yoink_cost": statistics.mean(grid[(s, p)]["cost_usd"] for p in POSITIONS)}
                   for s in SIZES]

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    STRESS_JSON.write_text(json.dumps(
        {"cells": results, "cost_points": cost_points,
         "grid_accuracy": {f"{s}-{p}": grid[(s, p)]["passed"] for s in SIZES for p in POSITIONS}}, indent=2))

    print(f"\n{'cell':<22}{'pass':>6}{'cost':>9}{'latency':>9}")
    print("-" * 46)
    for r in results:
        tag = f"{r['kind']} {r['size_tokens']//1000}K/{r['position']}/d{r['distractors']}"
        print(f"{tag:<22}{('✓' if r['passed'] else '✗'):>6}{'$'+format(r['cost_usd'],'.3f'):>9}{r['latency_ms']/1000:>8.1f}s")
    _plot(grid)
    print(f"\nwrote {STRESS_JSON}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
