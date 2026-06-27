"""Run the whole benchmark behind the live tracker, then regenerate the graphs.

    uv run python benchmark/run.py [--limit N]     # --limit caps Track A fixtures (quick smoke)

Watch progress from any other terminal at any time:

    uv run python benchmark/progress.py
"""
from __future__ import annotations

import sys

import costbench
import plot_cost
import recall
import stress


def _banner(text: str) -> None:
    print("\n" + "=" * 64 + f"\n  {text}\n" + "=" * 64)


def main(argv: list[str]) -> int:
    rc = 0
    _banner("Track A — recall accuracy")
    rc |= recall.main(argv)
    _banner("Track B — cost / latency vs baselines")
    rc |= costbench.main([])
    _banner("Track C — long-context stress")
    rc |= stress.main([])
    _banner("Graphs")
    plot_cost.main()
    print("\nbenchmark complete — results/ + accuracy.png + cost.png + stress.png updated.")
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
