"""Track B — cost / latency vs the baselines a user would actually reach for.

Over a fixed set of real sessions spanning sizes (a few dead-end fixtures + synthetic
haystacks at 5K/25K/100K tokens), measure four ways to answer the same question:

    grep            — rg/grep over the session .jsonl: ~free, instant, but matches words
    full-transcript — dump the whole transcript into Opus ("read it yourself")
    native resume   — `claude -p --resume <id> <q>` on Opus: "just resume it myself"
    yoink           — Haiku + the recall prompt: the proposed system

Every `claude` call reports its own `total_cost_usd`/usage, so costs are measured, not modelled.
Fairness notes (hard-won from review): native-resume forks so it never pollutes the shared session
yoink also reads; "live-context" is the transcript you'd carry (input) for resume-style methods vs
the answer (output) for yoink; token counts include cache-resident transcript tokens; and a failed
claude call is flagged `errored` and dropped from the aggregates rather than logged as a $0 row.

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
HAYSTACK_Q = "What did we conclude was causing the auth failures?"  # matches make_haystack's default topic
GREP = "rg" if shutil.which("rg") else "grep"  # ripgrep if installed, else POSIX grep


def _transcript_text(fx) -> str:
    return "\n".join(f"[{role}] {text}" for role, text in fx.turns)


def _question_keywords(question: str) -> list[str]:
    stop = {"what", "did", "we", "the", "was", "causing", "conclude", "concluded", "a", "to", "of", "for", "on", "is"}
    words = [w.strip("?.,").lower() for w in question.split()]
    return [w for w in words if len(w) > 3 and w not in stop][:6]


def _graded(fx, result_text: str) -> tuple[bool, bool, str]:
    """Accuracy = does the answer contain the conclusion (or abstain when it should)?
    Leak = does the answer text also surface a ruled-out term? (Track-A-only signal; cross-method it
    favours yoink's structured output, so it is reported per-method but NOT as a head-to-head column.)
    """
    ans = parse_answer(result_text or "")
    text = ans.answer.lower()
    if fx.expect.get("no_conclusion"):
        accuracy = ans.no_conclusion
    else:
        contains = fx.expect.get("conclusion_contains", [])
        accuracy = bool(contains) and all(k.lower() in text for k in contains)
    leak = any(k.lower() in text for k in fx.expect.get("conclusion_excludes", []))
    return bool(accuracy), leak, ans


def _row(method, *, accuracy=False, leak=False, latency_ms=0.0, in_tok=0, out_tok=0, cache_tok=0,
         cost=0.0, live_ctx=0, overflow=False, has_ex=False, answer="", errored=False,
         retrieval_only=False, confidence="", ruled_out=None, no_conclusion=False, raw_result="") -> dict:
    return {"method": method, "errored": errored, "accuracy": accuracy, "retrieval_only": retrieval_only,
            "dead_end_leak": leak, "has_excludes": has_ex, "latency_ms": latency_ms, "input_tokens": in_tok,
            "output_tokens": out_tok, "cache_tokens": cache_tok, "cost_usd": cost or 0.0,
            "live_context_tokens": live_ctx, "overflow": overflow,
            # audit fields (#7): the parsed answer + raw model output, so any row can be inspected
            "answer": answer[:300], "confidence": confidence, "ruled_out": ruled_out or [],
            "no_conclusion": no_conclusion, "raw_result": (raw_result or "")[:600]}


def _model_row(method, run, fx, *, live_ctx, overflow=False) -> dict:
    """Decode a claude envelope into a row. A nonzero exit / error / undecodable output is flagged
    `errored` (zeros) so it never silently becomes a $0, accuracy=False data point."""
    m = usage.envelope_metrics(run.stdout)
    if run.returncode != 0 or not m or m.get("is_error"):
        return _row(method, errored=True, latency_ms=run.latency_ms,
                    has_ex=bool(fx.expect.get("conclusion_excludes")))
    passed, leak, ans = _graded(fx, m.get("result_text"))
    return _row(method, accuracy=passed, leak=leak, latency_ms=run.latency_ms,
                in_tok=m["input_tokens"], out_tok=m["output_tokens"],
                cache_tok=m["cache_read_tokens"] + m["cache_creation_tokens"], cost=m["cost_usd"],
                live_ctx=live_ctx(m), overflow=overflow,
                has_ex=bool(fx.expect.get("conclusion_excludes")), answer=ans.answer,
                confidence=ans.answer_confidence, ruled_out=ans.ruled_out, no_conclusion=ans.no_conclusion,
                raw_result=m.get("result_text") or "")


def bl_grep(fx, ref) -> dict:
    path = sessions._transcript_path(ref["session_id"])
    kws = _question_keywords(fx.question) or [fx.question[:20]]
    pattern_args = [arg for k in kws for arg in ("-e", k)]  # -e kw1 -e kw2 ... (OR over fixed strings)
    base = [GREP, "-i", "-F"] + (["--no-filename"] if GREP == "rg" else [])  # grep on one file prints none
    run = usage.measure([*base, *pattern_args, str(path)])
    matches = run.stdout.lower()
    # NOTE: grep does not answer — this is "evidence containment": the gold keyword appears SOMEWHERE
    # in the returned match set (which you still have to read). Reported as retrieval_only, never
    # compared head-to-head with the other methods' answer accuracy.
    evidence_contains_answer = bool(fx.expect.get("conclusion_contains")) and all(
        k.lower() in matches for k in fx.expect.get("conclusion_contains", []))
    leak = any(k.lower() in matches for k in fx.expect.get("conclusion_excludes", []))
    return _row("grep", accuracy=evidence_contains_answer, leak=leak, latency_ms=run.latency_ms,
                live_ctx=usage.count_tokens(run.stdout), has_ex=bool(fx.expect.get("conclusion_excludes")),
                retrieval_only=True)


def bl_full_transcript(fx, ref) -> dict:
    # the ACTUAL built session transcript (what yoink/native resume), not just the fixture user turns:
    text = sessions.transcript_text(ref["session_id"]) or _transcript_text(fx)
    prompt = (f"<transcript>\n{text}\n</transcript>\n\n"
              f"Based only on the transcript above, answer concisely: {fx.question}")
    run = usage.measure(["claude", "-p", "--model", OPUS, "--permission-mode", "plan",
                         "--output-format", "json", "--tools", ""],
                        input=prompt, cwd=ref["cwd"], timeout=900)  # cwd isolates the throwaway session
    tokens = usage.count_tokens(text)
    # you dumped the whole transcript into your context:
    return _model_row("full-transcript", run, fx, live_ctx=lambda m: tokens,
                      overflow=tokens > usage.CONTEXT_WINDOW)


def bl_native_resume(fx, ref) -> dict:
    # --fork-session: isolate AND never mutate the shared session that yoink also reads.
    # --tools "": tool-disabled like yoink (can't re-investigate); question via stdin so greedy --tools
    # doesn't swallow it.
    run = usage.measure(["claude", "-p", "--resume", ref["session_id"], "--fork-session", "--model", OPUS,
                         "--permission-mode", "plan", "--output-format", "json", "--tools", ""],
                        input=fx.question, cwd=ref["cwd"], timeout=900)
    # resuming it yourself loads the ENTIRE transcript into your context — fresh input PLUS the
    # cache-resident transcript (most of it counts as cached, not fresh input):
    return _model_row("native-resume", run, fx,
                      live_ctx=lambda m: m["input_tokens"] + m["cache_read_tokens"] + m["cache_creation_tokens"])


def bl_yoink(fx, ref, model) -> dict:
    cmd = answerer._build_command(ref["session_id"], build_recall_prompt(fx.question), model=model)
    run = usage.measure(cmd, cwd=ref["cwd"], timeout=900)
    # yoink reads in an isolated process and hands back only the answer:
    return _model_row("yoink", run, fx, live_ctx=lambda m: m["output_tokens"])


def _session_set(fixtures):
    de = [f for f in fixtures if f.category == "dead_end_suppression"][:3]
    hay = [sessions.make_haystack(
        fixture_id=f"hay-{n}", conclusion="connection pool exhaustion", deadend="postgres",
        question=HAYSTACK_Q, target_tokens=n, position="end", distractors=10) for n in HAYSTACK_SIZES]
    return de + hay


def _aggregate(rows: list[dict]) -> dict:
    by_method = defaultdict(list)
    for r in rows:
        if r.get("errored"):
            continue  # a failed claude call must not skew cost/accuracy
        by_method[r["method"]].append(r)
    out = {}
    for method, rs in by_method.items():
        lats = sorted(r["latency_ms"] for r in rs)
        with_ex = [r for r in rs if r["has_excludes"]]
        out[method] = {
            "n": len(rs),
            "accuracy": sum(r["accuracy"] for r in rs) / len(rs),
            "retrieval_only": any(r.get("retrieval_only") for r in rs),  # grep: "accuracy" = evidence containment
            "dead_end_rate": (sum(r["dead_end_leak"] for r in with_ex) / len(with_ex)) if with_ex else None,
            "p50_latency_ms": statistics.median(lats),
            "p95_latency_ms": lats[min(len(lats) - 1, int(0.95 * len(lats)))],
            # include cache-resident transcript tokens: a resumed transcript is processed, just cached
            "mean_tokens": sum(r["input_tokens"] + r["output_tokens"] + r["cache_tokens"] for r in rs) / len(rs),
            "mean_cost_usd": sum(r["cost_usd"] for r in rs) / len(rs),
            "mean_live_context": sum(r["live_context_tokens"] for r in rs) / len(rs),
            "overflow_rate": sum(r["overflow"] for r in rs) / len(rs),
        }
    return out


_ORDER = ["grep", "full-transcript", "native-resume", "yoink"]


def _print_table(agg: dict) -> None:
    print(f"\n{'method':<16}{'acc':>7}{'p50 ms':>9}{'tok/q':>9}{'cost/q':>10}{'live-ctx':>10}{'overflow':>10}")
    print("-" * 75)
    for method in _ORDER:
        m = agg.get(method)
        if not m:
            continue
        # grep does not answer; its "accuracy" is evidence containment, marked * (not comparable)
        acc = f"{m['accuracy']*100:.0f}%" + ("*" if m.get("retrieval_only") else " ")
        print(f"{method:<16}{acc:>7}{m['p50_latency_ms']:>9.0f}"
              f"{m['mean_tokens']:>9.0f}{'$'+format(m['mean_cost_usd'],'.4f'):>10}"
              f"{m['mean_live_context']:>10.0f}{m['overflow_rate']*100:>9.0f}%")
    print("* grep returns matching lines, not an answer — 'acc' = gold keyword present in match set.")


def main(argv: list[str]) -> int:
    model = config.load_config().model
    fixtures = load_fixtures()
    sset = _session_set(fixtures)
    print(f"track B: {len(sset)} sessions x 4 baselines (yoink model = {model})")

    tracker = progress.Tracker(n_phases=2)
    refs = sessions.build_all(sset, tracker=tracker)

    tracker.phase("cost/latency (track B)", len(sset) * 4)
    rows, points = [], []
    for fx in sset:
        ref = refs[fx.id]
        size_tokens = usage.count_tokens(_transcript_text(fx))
        per = {}
        for name, fn in (("grep", bl_grep), ("full-transcript", bl_full_transcript),
                         ("native-resume", bl_native_resume), ("yoink", lambda f, r: bl_yoink(f, r, model))):
            row = fn(fx, ref)
            row["fixture_id"], row["size_tokens"] = fx.id, size_tokens
            rows.append(row)
            per[name] = row
            tracker.step(f"{fx.id}:{name}")
        # a cost point needs all three model methods to have succeeded
        if not any(per[k].get("errored") for k in ("full-transcript", "native-resume", "yoink")):
            points.append({"fixture_id": fx.id, "size_tokens": size_tokens,
                           "yoink_cost": per["yoink"]["cost_usd"],
                           "full_transcript_cost": per["full-transcript"]["cost_usd"],
                           "native_cost": per["native-resume"]["cost_usd"]})
    tracker.done_phase()

    agg = _aggregate(rows)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    COST_JSON.write_text(json.dumps({"summary": agg, "points": points, "rows": rows}, indent=2))
    _print_table(agg)
    n_err = sum(r.get("errored", False) for r in rows)
    if n_err:
        print(f"\n⚠ {n_err} errored call(s) dropped from aggregates")
    print(f"wrote {COST_JSON}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
