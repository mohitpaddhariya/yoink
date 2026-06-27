"""Track A — recall accuracy (the product path).

For each fixture: build a REAL session (sessions.build_session), run the production recall
(`run_answerer`, Haiku) and grade with eval/evalkit.grade. Reports per-category accuracy, the
dead-end error rate (a `conclusion_excludes` keyword leaking into the answer), and abstention
F1. The `session_resolution` category instead checks `resolver.resolve` ranks the right session
among all the others. Writes results/recall.json + accuracy.png.

    uv run python benchmark/recall.py [--limit N]
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "eval"))  # evalkit lives in eval/

import progress
import sessions
from evalkit import grade, load_fixtures
from yoink import config, resolver
from yoink.answerer import run_answerer
from yoink.prompts import build_recall_prompt

RESULTS_DIR = Path(__file__).parent / "results"
RECALL_JSON = RESULTS_DIR / "recall.json"
ACCURACY_PNG = Path(__file__).parent / "figures" / "accuracy.png"
RESOLUTION = "session_resolution"


def _recall_one(fx, ref: dict, model: str) -> dict:
    res = run_answerer(ref["session_id"], ref["cwd"], build_recall_prompt(fx.question), model=model)
    should_abstain = bool(fx.expect.get("no_conclusion"))
    excludes = [k.lower() for k in fx.expect.get("conclusion_excludes", [])]
    if not res.ok:
        kind = res.error.kind.value if res.error else "unknown"
        # has_excludes=False: an answerer error is not evidence of dead-end suppression, so it must
        # not enter the dead_end_rate denominator as a free "clean" sample.
        return {"id": fx.id, "category": fx.category, "passed": False, "reasons": [f"answerer error: {kind}"],
                "has_excludes": False, "dead_end_leak": False,
                "should_abstain": should_abstain, "did_abstain": False, "answer": "", "ruled_out": []}
    ans = res.answer
    passed, reasons = grade(fx, ans)
    leak = any(k in ans.answer.lower() for k in excludes)
    return {"id": fx.id, "category": fx.category, "passed": passed, "reasons": reasons,
            "has_excludes": bool(excludes), "dead_end_leak": leak,
            "should_abstain": should_abstain, "did_abstain": ans.no_conclusion,
            "confidence": ans.answer_confidence, "answer": ans.answer, "ruled_out": ans.ruled_out}


def _resolve_one(fx, ref: dict) -> dict:
    rr = resolver.resolve(fx.session_hint or fx.question, caller_session_id=None,
                          caller_cwd=str(sessions.BENCH_CWD), cross_project=False)
    top = rr.candidates[0] if rr.candidates else None
    ok = bool(top and top.session_id == ref["session_id"] and rr.source_match in ("high", "medium"))
    return {"id": fx.id, "category": RESOLUTION, "passed": ok,
            "reasons": [] if ok else [f"resolved to {top.session_id if top else None} @ {rr.source_match}"],
            "has_excludes": False, "dead_end_leak": False, "should_abstain": False, "did_abstain": False,
            "source_match": rr.source_match, "resolved_top": top.session_id if top else None}


def _aggregate(results: list[dict]) -> dict:
    by_cat: dict[str, list] = defaultdict(list)
    for r in results:
        by_cat[r["category"] or "uncategorized"].append(r)
    cats = {}
    for cat, rs in sorted(by_cat.items()):
        with_ex = [r for r in rs if r["has_excludes"]]
        cats[cat] = {
            "n": len(rs),
            "accuracy": sum(r["passed"] for r in rs) / len(rs),
            "dead_end_leaks": sum(r["dead_end_leak"] for r in rs),
            "dead_end_rate": (sum(r["dead_end_leak"] for r in with_ex) / len(with_ex)) if with_ex else None,
        }
    n = len(results)
    with_ex = [r for r in results if r["has_excludes"]]
    tp = sum(r["should_abstain"] and r["did_abstain"] for r in results)
    fp = sum(not r["should_abstain"] and r["did_abstain"] for r in results)
    fn = sum(r["should_abstain"] and not r["did_abstain"] for r in results)
    prec = tp / (tp + fp) if (tp + fp) else 1.0
    rec = tp / (tp + fn) if (tp + fn) else 1.0
    f1 = 2 * prec * rec / (prec + rec) if (prec + rec) else 0.0
    return {
        "categories": cats,
        "overall": {
            "n": n,
            "accuracy": sum(r["passed"] for r in results) / n,
            "dead_end_rate": (sum(r["dead_end_leak"] for r in with_ex) / len(with_ex)) if with_ex else None,
        },
        "abstention": {"precision": prec, "recall": rec, "f1": f1, "tp": tp, "fp": fp, "fn": fn},
    }


def _print_table(report: dict) -> None:
    print(f"\n{'category':<24}{'n':>4}{'acc':>7}{'dead-end':>10}")
    print("-" * 45)
    for cat, m in report["categories"].items():
        de = "—" if m["dead_end_rate"] is None else f"{m['dead_end_rate']*100:.0f}%"
        print(f"{cat:<24}{m['n']:>4}{m['accuracy']*100:>6.0f}%{de:>10}")
    print("-" * 45)
    o = report["overall"]
    de = "—" if o["dead_end_rate"] is None else f"{o['dead_end_rate']*100:.0f}%"
    print(f"{'OVERALL':<24}{o['n']:>4}{o['accuracy']*100:>6.0f}%{de:>10}")
    a = report["abstention"]
    print(f"abstention F1 {a['f1']:.2f} (P={a['precision']:.2f} R={a['recall']:.2f}, "
          f"tp={a['tp']} fp={a['fp']} fn={a['fn']})")


def _plot(report: dict) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    cats = report["categories"]
    labels = [c.replace("_", "\n") for c in cats]
    accs = [cats[c]["accuracy"] * 100 for c in cats]
    fig, ax = plt.subplots(figsize=(11, 5))
    bars = ax.bar(labels, accs, color="#8B5CF6")
    ax.axhline(90, color="#9AA0AA", ls="--", lw=1.2, label="90% target")
    ax.set_ylim(0, 100)
    ax.set_ylabel("recall accuracy (%)")
    ax.set_title("yoink recall accuracy by task category", fontweight="bold", loc="left")
    for bar, acc in zip(bars, accs):
        ax.text(bar.get_x() + bar.get_width() / 2, acc + 1.5, f"{acc:.0f}", ha="center", fontsize=9)
    ax.legend(frameon=False)
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)
    fig.tight_layout()
    fig.savefig(ACCURACY_PNG, dpi=160, bbox_inches="tight")
    print(f"wrote {ACCURACY_PNG.name}")


def main(argv: list[str]) -> int:
    limit = None
    if "--limit" in argv:
        limit = int(argv[argv.index("--limit") + 1])
    model = config.load_config().model
    fixtures = load_fixtures()
    if limit:
        fixtures = fixtures[:limit]
    if not fixtures:
        print("no fixtures found")
        return 1
    print(f"track A: {len(fixtures)} fixtures, recall model = {model}")

    tracker = progress.Tracker(n_phases=2)
    refs = sessions.build_all(fixtures, tracker=tracker)

    tracker.phase("recall (track A)", len(fixtures))
    results = []

    # Resolution FIRST, before any recall fork .jsonl is written into the slug dir: a fork copies its
    # parent's title/body but has a newer mtime, so an in-flight one (marker not yet flushed) could
    # out-rank the real target. Running resolution before recall makes it deterministic.
    for fx in (f for f in fixtures if f.category == RESOLUTION):
        results.append(_resolve_one(fx, refs[fx.id]))
        tracker.step(fx.id)

    def work(fx):
        r = _recall_one(fx, refs[fx.id], model)
        tracker.step(fx.id)
        return r

    with ThreadPoolExecutor(max_workers=8) as pool:
        results.extend(pool.map(work, (f for f in fixtures if f.category != RESOLUTION)))
    tracker.done_phase()

    report = _aggregate(results)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    RECALL_JSON.write_text(json.dumps({"report": report, "fixtures": results}, indent=2))
    _print_table(report)
    _plot(report)
    print(f"\nwrote {RECALL_JSON}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
