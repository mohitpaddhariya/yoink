"""Track B — cost / latency vs the baselines a user would actually reach for.

Over a fixed set of real sessions spanning sizes (a few dead-end fixtures + synthetic
haystacks at 5K/25K/100K tokens), measure four ways to answer the same question:

    grep            — rg over the session .jsonl: ~free, instant, but can't tell decided from ruled-out
    full-transcript — dump the whole transcript into Opus ("read it yourself"): the expensive upper bound
    native resume   — `claude -p --resume <id> <q>` on Opus, tools on: "just resume it myself"
    yoink           — Haiku + the recall prompt, tools off: the proposed system

Every claude call reports its own `total_cost_usd`/usage, so costs are measured, not modelled.
Writes results/cost.json and prints the STRATEGY §1.B public table.

    uv run python benchmark/costbench.py
"""
from __future__ import annotations

import json
import shutil
import statistics
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "eval"))

import progress
import sessions
import usage
from evalkit import load_fixtures
from yoink import answerer, config
from yoink.prompts import build_recall_prompt, parse_answer

RESULTS_DIR = Path(__file__).parent / "results"
COST_JSON = RESULTS_DIR / "cost.json"
OPUS = "opus"  # alias → current Opus; the "read it yourself in your live session" model
HAYSTACK_SIZES = (5_000, 25_000, 100_000)
GREP = "rg" if shutil.which("rg") else "grep"  # ripgrep if installed, else POSIX grep


def _transcript_text(fx) -> str:
    return "\n".join(f"[{role}] {text}" for role, text in fx.turns)


def _question_keywords(question: str) -> list[str]:
    stop = {"what", "did", "we", "the", "was", "causing", "conclude", "concluded", "a", "to", "of", "for", "on", "is"}
    words = [w.strip("?.,").lower() for w in question.split()]
    return [w for w in words if len(w) > 3 and w not in stop][:6]


def _graded(fx, result_text: str) -> tuple[bool, bool, str]:
    """Decouple accuracy from dead-end leak so prose baselines are graded FAIRLY.

    Accuracy = does the answer contain the conclusion (or abstain when it should)? Leak = does it
    also surface a ruled-out term? grade()'s combined check fails any answer that *mentions* a dead
    end — fine for yoink (its answer field is clean; ruled-out goes in a separate list) but unfair to
    a prose dump that correctly says "X, having ruled out Y". Keeping them separate is the honest cut.
    """
    ans = parse_answer(result_text or "")
    text = ans.answer.lower()
    if fx.expect.get("no_conclusion"):
        accuracy = ans.no_conclusion
    else:
        contains = fx.expect.get("conclusion_contains", [])
        accuracy = bool(contains) and all(k.lower() in text for k in contains)
    leak = any(k.lower() in text for k in fx.expect.get("conclusion_excludes", []))
    return bool(accuracy), leak, ans.answer


def _row(method, *, accuracy, leak, latency_ms, in_tok, out_tok, cost, live_ctx, overflow, has_ex, answer="") -> dict:
    return {"method": method, "accuracy": accuracy, "dead_end_leak": leak, "has_excludes": has_ex,
            "latency_ms": latency_ms, "input_tokens": in_tok, "output_tokens": out_tok,
            "cost_usd": cost or 0.0, "live_context_tokens": live_ctx, "overflow": overflow,
            "answer": answer[:200]}


def bl_grep(fx, ref) -> dict:
    path = sessions._transcript_path(ref["session_id"])
    kws = _question_keywords(fx.question) or [fx.question[:20]]
    pattern_args = [arg for k in kws for arg in ("-e", k)]  # -e kw1 -e kw2 ... (OR over fixed strings)
    base = [GREP, "-i", "-F"] + (["--no-filename"] if GREP == "rg" else [])  # grep on one file prints none
    run = usage.measure([*base, *pattern_args, str(path)])
    matches = run.stdout.lower()
    gold = all(k.lower() in matches for k in fx.expect.get("conclusion_contains", [])) if fx.expect.get("conclusion_contains") else False
    leak = any(k.lower() in matches for k in fx.expect.get("conclusion_excludes", []))
    return _row("grep", accuracy=gold, leak=leak, latency_ms=run.latency_ms, in_tok=0, out_tok=0,
                cost=0.0, live_ctx=usage.count_tokens(run.stdout), overflow=False,
                has_ex=bool(fx.expect.get("conclusion_excludes")))


def bl_full_transcript(fx, ref) -> dict:
    text = _transcript_text(fx)
    prompt = (f"<transcript>\n{text}\n</transcript>\n\n"
              f"Based only on the transcript above, answer concisely: {fx.question}")
    run = usage.measure(["claude", "-p", "--model", OPUS, "--permission-mode", "plan",
                         "--output-format", "json", "--tools", ""], input=prompt, timeout=900)
    m = usage.envelope_metrics(run.stdout) or {}
    passed, leak, answer = _graded(fx, m.get("result_text"))
    tokens = usage.count_tokens(text)
    return _row("full-transcript", accuracy=passed, leak=leak, latency_ms=run.latency_ms,
                in_tok=m.get("input_tokens", 0), out_tok=m.get("output_tokens", 0), cost=m.get("cost_usd"),
                live_ctx=tokens, overflow=tokens > usage.CONTEXT_WINDOW,
                has_ex=bool(fx.expect.get("conclusion_excludes")), answer=answer)


def bl_native_resume(fx, ref) -> dict:
    run = usage.measure(["claude", "-p", "--resume", ref["session_id"], "--model", OPUS,
                         "--permission-mode", "plan", "--output-format", "json", fx.question],
                        cwd=ref["cwd"], timeout=900)
    m = usage.envelope_metrics(run.stdout) or {}
    passed, leak, answer = _graded(fx, m.get("result_text"))
    return _row("native-resume", accuracy=passed, leak=leak, latency_ms=run.latency_ms,
                in_tok=m.get("input_tokens", 0), out_tok=m.get("output_tokens", 0), cost=m.get("cost_usd"),
                live_ctx=m.get("output_tokens", 0), overflow=False,
                has_ex=bool(fx.expect.get("conclusion_excludes")), answer=answer)


def bl_yoink(fx, ref, model) -> dict:
    cmd = answerer._build_command(ref["session_id"], build_recall_prompt(fx.question), model=model)
    run = usage.measure(cmd, cwd=ref["cwd"], timeout=900)
    m = usage.envelope_metrics(run.stdout) or {}
    passed, leak, answer = _graded(fx, m.get("result_text"))
    return _row("yoink", accuracy=passed, leak=leak, latency_ms=run.latency_ms,
                in_tok=m.get("input_tokens", 0), out_tok=m.get("output_tokens", 0), cost=m.get("cost_usd"),
                live_ctx=m.get("output_tokens", 0), overflow=False,
                has_ex=bool(fx.expect.get("conclusion_excludes")), answer=answer)


def _session_set(fixtures):
    de = [f for f in fixtures if f.category == "dead_end_suppression"][:3]
    hay = [sessions.make_haystack(
        fixture_id=f"hay-{n}", conclusion="connection pool exhaustion", deadend="postgres",
        question="What did we conclude was causing the timeouts?",
        target_tokens=n, position="end", distractors=10) for n in HAYSTACK_SIZES]
    return de + hay


def _aggregate(rows: list[dict]) -> dict:
    by_method = defaultdict(list)
    for r in rows:
        by_method[r["method"]].append(r)
    out = {}
    for method, rs in by_method.items():
        lats = sorted(r["latency_ms"] for r in rs)
        with_ex = [r for r in rs if r["has_excludes"]]
        out[method] = {
            "n": len(rs),
            "accuracy": sum(r["accuracy"] for r in rs) / len(rs),
            "dead_end_rate": (sum(r["dead_end_leak"] for r in with_ex) / len(with_ex)) if with_ex else None,
            "p50_latency_ms": statistics.median(lats),
            "p95_latency_ms": lats[min(len(lats) - 1, int(0.95 * len(lats)))],
            "mean_tokens": sum(r["input_tokens"] + r["output_tokens"] for r in rs) / len(rs),
            "mean_cost_usd": sum(r["cost_usd"] for r in rs) / len(rs),
            "mean_live_context": sum(r["live_context_tokens"] for r in rs) / len(rs),
            "overflow_rate": sum(r["overflow"] for r in rs) / len(rs),
        }
    return out


# Ordered for the public table; cost.png reads the per-session points below.
_ORDER = ["grep", "full-transcript", "native-resume", "yoink"]


def _print_table(agg: dict) -> None:
    print(f"\n{'method':<16}{'acc':>6}{'dead-end':>10}{'p50 ms':>9}{'tok/q':>9}{'cost/q':>10}{'live-ctx':>10}{'overflow':>10}")
    print("-" * 84)
    for method in _ORDER:
        m = agg.get(method)
        if not m:
            continue
        de = "—" if m["dead_end_rate"] is None else f"{m['dead_end_rate']*100:.0f}%"
        print(f"{method:<16}{m['accuracy']*100:>5.0f}%{de:>10}{m['p50_latency_ms']:>9.0f}"
              f"{m['mean_tokens']:>9.0f}{'$'+format(m['mean_cost_usd'],'.4f'):>10}"
              f"{m['mean_live_context']:>10.0f}{m['overflow_rate']*100:>9.0f}%")


def main(argv: list[str]) -> int:
    model = config.load_config().model
    fixtures = load_fixtures()
    sset = _session_set(fixtures)
    print(f"track B: {len(sset)} sessions x 4 baselines (yoink model = {model})")

    tracker = progress.Tracker(n_phases=2)
    refs = sessions.build_all(sset, tracker=tracker)

    tracker.phase("cost/latency (track B)", len(sset) * 4)
    rows = []
    points = []  # per-session cost points for cost.png
    for fx in sset:
        ref = refs[fx.id]
        per = {}
        for name, fn in (("grep", bl_grep), ("full-transcript", bl_full_transcript),
                         ("native-resume", bl_native_resume), ("yoink", lambda f, r: bl_yoink(f, r, model))):
            row = fn(fx, ref)
            row["fixture_id"] = fx.id
            row["size_tokens"] = usage.count_tokens(_transcript_text(fx))
            rows.append(row)
            per[name] = row
            tracker.step(f"{fx.id}:{name}")
        points.append({"fixture_id": fx.id, "size_tokens": per["yoink"]["size_tokens"],
                       "yoink_cost": per["yoink"]["cost_usd"],
                       "full_transcript_cost": per["full-transcript"]["cost_usd"],
                       "native_cost": per["native-resume"]["cost_usd"]})
    tracker.done_phase()

    agg = _aggregate(rows)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    COST_JSON.write_text(json.dumps({"summary": agg, "points": points, "rows": rows}, indent=2))
    _print_table(agg)
    print(f"\nwrote {COST_JSON}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
