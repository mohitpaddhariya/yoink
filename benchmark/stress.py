"""Track C — long-context stress (conclusion-in-haystack), by SIZE and DIFFICULTY.

Buries a known conclusion in synthetic sessions of growing size, stated at three difficulties, and
grades recall + measures cost. Difficulty is the honest knob (an explicit ``FINAL CONCLUSION:`` marker
is far easier than an implied, corrected conclusion — see sessions._conclusion_lines):

    easy   — explicit "FINAL CONCLUSION:" marker
    medium — natural prose, no marker
    hard   — implied across turns with a correction off a dead end

Every row stores its raw + parsed answer and grade reasons so a failure can be audited. v1 caps at
100K tokens.  uv run python benchmark/stress.py
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
STRESS_PNG = Path(__file__).parent / "figures" / "stress.png"

SIZES = (5_000, 25_000, 100_000)
DIFFICULTIES = ("easy", "medium", "hard")
CONCL, DEAD = "connection pool exhaustion", "postgres"
Q = "What did we conclude was causing the auth failures?"  # matches make_haystack's default topic


def _recall_measured(ref: dict, question: str, model: str):
    """Returns (answer, cost_usd, latency_ms, errored, raw_result)."""
    cmd = answerer._build_command(ref["session_id"], build_recall_prompt(question), model=model)
    run = usage.measure(cmd, cwd=ref["cwd"], timeout=900)
    m = usage.envelope_metrics(run.stdout)
    if run.returncode != 0 or not m or m.get("is_error"):
        return parse_answer(""), 0.0, run.latency_ms, True, ""
    raw = m.get("result_text") or ""
    return parse_answer(raw), (m.get("cost_usd") or 0.0), run.latency_ms, False, raw


def _cells():
    cells = []
    for s in SIZES:  # the size x difficulty heatmap (position end, distractors 10)
        for diff in DIFFICULTIES:
            cells.append(("grid", s, diff, sessions.make_haystack(
                fixture_id=f"hs-{s}-{diff}", question=Q, target_tokens=s, position="end",
                distractors=10, conclusion=CONCL, deadend=DEAD, difficulty=diff)))
    cells.append(("update", 25_000, "medium", sessions.make_haystack(  # recency at scale
        fixture_id="hs-update", question=Q, target_tokens=25_000, position="end",
        distractors=10, conclusion=CONCL, superseded="dns misconfiguration", difficulty="medium")))
    cells.append(("unanswerable", 25_000, "medium", sessions.make_haystack(  # abstention at scale
        fixture_id="hs-open", question=Q, target_tokens=25_000, position="mid",
        distractors=10, conclusion=None, deadend=DEAD)))
    return cells


def _plot(grid: dict) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    mat = [[grid.get((s, d), {}).get("passed", 0) * 100 for d in DIFFICULTIES] for s in SIZES]
    fig, ax = plt.subplots(figsize=(7, 5))
    ax.imshow(mat, cmap="RdYlGn", vmin=0, vmax=100, aspect="auto")
    ax.set_xticks(range(len(DIFFICULTIES)), [d + ("\n(marker)" if d == "easy" else "\n(no marker)") for d in DIFFICULTIES])
    ax.set_yticks(range(len(SIZES)), [f"{s // 1000}K" for s in SIZES])
    ax.set_xlabel("how the conclusion is stated")
    ax.set_ylabel("transcript size")
    ax.set_title("yoink recall in a haystack — by size × difficulty", fontweight="bold", loc="left")
    for i, s in enumerate(SIZES):
        for j, d in enumerate(DIFFICULTIES):
            cell = grid.get((s, d), {})
            ax.text(j, i, f"{'✓' if cell.get('passed') else '✗'}\n${cell.get('cost_usd', 0):.3f}",
                    ha="center", va="center", fontsize=10)
    fig.tight_layout()
    fig.savefig(STRESS_PNG, dpi=160, bbox_inches="tight")
    print(f"wrote {STRESS_PNG.name}")


def main(argv: list[str]) -> int:
    model = config.load_config().model
    cells = _cells()
    print(f"track C: {len(cells)} haystack cells (recall model = {model})")

    tracker = progress.Tracker(n_phases=2)
    refs = sessions.build_all([c[-1] for c in cells], tracker=tracker)

    tracker.phase("stress recall (track C)", len(cells))
    results, grid = [], {}
    for kind, size, diff, fx in cells:
        ans, cost, lat, errored, raw = _recall_measured(refs[fx.id], fx.question, model)
        passed, reasons = (False, ["errored"]) if errored else grade(fx, ans)
        row = {"kind": kind, "size_tokens": size, "difficulty": diff, "passed": passed, "errored": errored,
               "cost_usd": cost, "latency_ms": lat,
               "answer": ans.answer[:300], "confidence": ans.answer_confidence, "ruled_out": ans.ruled_out,
               "no_conclusion": ans.no_conclusion, "grade_reasons": reasons, "raw_result": raw[:600]}
        results.append(row)
        if kind == "grid":
            grid[(size, diff)] = row
        tracker.step(f"{kind} {size//1000}K {diff}")
    tracker.done_phase()

    cost_points = []  # mean yoink recall cost by size (across non-errored difficulties) for cost.png
    for s in SIZES:
        costs = [grid[(s, d)]["cost_usd"] for d in DIFFICULTIES if not grid[(s, d)]["errored"]]
        if costs:
            cost_points.append({"size_tokens": s, "yoink_cost": statistics.mean(costs)})
    by_difficulty = {d: round(sum(grid[(s, d)]["passed"] for s in SIZES) / len(SIZES), 2) for d in DIFFICULTIES}

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    STRESS_JSON.write_text(json.dumps(
        {"cells": results, "cost_points": cost_points, "accuracy_by_difficulty": by_difficulty}, indent=2))

    print(f"\n{'cell':<24}{'pass':>6}{'cost':>9}{'latency':>9}")
    print("-" * 48)
    for r in results:
        tag = f"{r['kind']} {r['size_tokens']//1000}K/{r['difficulty']}"
        mark = "—" if r["errored"] else ("✓" if r["passed"] else "✗")
        print(f"{tag:<24}{mark:>6}{'$'+format(r['cost_usd'],'.3f'):>9}{r['latency_ms']/1000:>8.1f}s")
    print(f"accuracy by difficulty (grid): {by_difficulty}")
    _plot(grid)
    print(f"\nwrote {STRESS_JSON}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
