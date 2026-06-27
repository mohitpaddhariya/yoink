"""Offline coverage for the benchmark's pure logic (no `claude` calls).

The measurement/recall paths are exercised live by each module's `--selftest`; these lock the
parsing, progress math, and haystack-shaping that the harnesses depend on.
"""
from types import SimpleNamespace

import progress
import sessions
import usage


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
