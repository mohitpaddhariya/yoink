"""Offline coverage for the benchmark's pure logic (no `claude` calls).

The measurement/recall paths are exercised live by each module's `--selftest`; these lock the
parsing, progress math, and haystack-shaping that the harnesses depend on.
"""
from types import SimpleNamespace

import costbench
import progress
import sessions
import usage
from usage import Run


def test_envelope_metrics_parses_and_tolerates_garbage():
    m = usage.envelope_metrics('{"total_cost_usd":0.02,"usage":{"input_tokens":10,"output_tokens":5},"result":"hi"}')
    assert m["cost_usd"] == 0.02 and m["input_tokens"] == 10 and m["result_text"] == "hi"
    assert usage.envelope_metrics("not json") is None
    assert usage.envelope_metrics("[1,2,3]") is None  # valid json, wrong shape


def test_count_tokens():
    assert usage.count_tokens("") == 1
    assert usage.count_tokens("a" * 400) == 100


def test_progress_math():
    assert progress._bar(0, 10).count("#") == 0
    assert progress._bar(5, 10).count("#") == 12
    assert progress._eta_seconds(5, 10, 10.0) == 10.0
    assert progress._eta_seconds(0, 10, 5) is None
    line = progress.render_line("Track A", 5, 10, 10.0, "fix")
    assert "5/10" in line and " 50%" in line and "fix" in line


def test_turns_hash_is_stable_and_sensitive():
    turns = [("user", "a"), ("user", "b")]
    assert sessions._turns_hash(turns) == sessions._turns_hash([("user", "a"), ("user", "b")])
    assert sessions._turns_hash(turns) != sessions._turns_hash([("user", "a")])


def test_user_turns_filters_role():
    assert sessions._user_turns([("user", "a"), ("assistant", "b"), ("user", "c")]) == ["a", "c"]


def test_make_haystack_variants():
    normal = sessions.make_haystack(fixture_id="h", question="q?", target_tokens=2000,
                                    conclusion="connection pool", deadend="dns")
    assert normal.turns[0][0] == "user" and len(normal.turns[0][1]) > 4000  # ~target chars of haystack
    assert normal.expect["conclusion_contains"] == ["connection pool"]
    assert normal.expect["conclusion_excludes"] == ["dns"] and normal.expect["no_conclusion"] is False

    unanswerable = sessions.make_haystack(fixture_id="u", question="q?", target_tokens=500, conclusion=None, deadend="dns")
    assert unanswerable.expect["no_conclusion"] is True and "FINAL CONCLUSION" not in unanswerable.turns[0][1]

    update = sessions.make_haystack(fixture_id="p", question="q?", target_tokens=500,
                                    conclusion="connection pool", superseded="redis")
    assert update.expect["conclusion_excludes"] == ["redis"]  # the superseded option is what must not win


# --- regressions locking the code-review honesty fixes (Track B fairness) ---

def test_costbench_model_row_flags_errored_call():
    fx = SimpleNamespace(expect={"conclusion_contains": ["x"]}, question="q?")
    row = costbench._model_row("yoink", Run("", "boom", 1, 10.0), fx, live_ctx=lambda m: m["output_tokens"])
    assert row["errored"] is True and row["cost_usd"] == 0.0  # a failed call is not a $0 data point


def test_costbench_graded_decouples_accuracy_from_leak():
    fx = SimpleNamespace(expect={"conclusion_contains": ["connection pool"], "conclusion_excludes": ["postgres"]},
                         question="q?")
    # a correct prose answer that names the ruled-out path: still ACCURATE, leak just flags the mention
    acc, leak, _ = costbench._graded(fx, "The cause is connection pool exhaustion; postgres was ruled out.")
    assert acc is True and leak is True


def test_costbench_aggregate_drops_errored_and_counts_cache_tokens():
    good = costbench._row("yoink", accuracy=True, in_tok=10, out_tok=5, cache_tok=1000, cost=0.02, live_ctx=5)
    agg = costbench._aggregate([good, costbench._row("yoink", errored=True)])
    assert agg["yoink"]["n"] == 1  # the errored row is excluded
    assert agg["yoink"]["mean_tokens"] == 1015  # input + output + cache-resident transcript
