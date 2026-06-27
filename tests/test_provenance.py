import pytest

import yoink.provenance as provenance
from yoink.prompts import RecallAnswer
from yoink.resolver import Candidate

NOW = 1_000_000.0


def _cand(title="auth-debugging", cwd="/Users/x/payments", mtime=NOW - 240, session_id="s1"):
    return Candidate(session_id, cwd, title, mtime, 5.0)


def _ans(answer="it is token refresh", conf="medium", ruled_out=("cache",), cited="t3", no_conclusion=False):
    return RecallAnswer(
        answer=answer, answer_confidence=conf, ruled_out=list(ruled_out),
        cited_turn=cited, no_conclusion=no_conclusion,
    )


def test_compact_oneliner_high_match():
    out = provenance.format_provenance(_cand(), "high", _ans(conf="medium"), now=NOW)
    assert out.splitlines()[0] == (
        "From auth-debugging · payments · 4m ago · source match: high · answer confidence: medium"
    )
    assert "Answer: it is token refresh" in out
    assert "Ruled out: cache" in out


def test_medium_appends_confirm_note():
    out = provenance.format_provenance(_cand(), "medium", _ans(), now=NOW)
    assert "confirm this is the right session" in out
    assert "Answer:" in out


def test_high_match_omits_confirm_note():
    out = provenance.format_provenance(_cand(), "high", _ans(), now=NOW)
    assert "confirm this is the right session" not in out


def test_ruled_out_empty_omits_line():
    out = provenance.format_provenance(_cand(), "high", _ans(ruled_out=()), now=NOW)
    assert "Ruled out:" not in out


def test_long_ruled_out_truncated():
    out = provenance.format_provenance(_cand(), "high", _ans(ruled_out=tuple(f"x{i}" for i in range(6))), now=NOW)
    assert "(+3 more)" in out


def test_no_conclusion_safe_shape():
    out = provenance.format_provenance(_cand(), "high", _ans(no_conclusion=True, ruled_out=("cache", "db")), now=NOW)
    assert "didn't reach a clear conclusion" in out
    assert "What it did contain:" in out
    assert "- cache" in out
    assert "Answer:" not in out
    assert "answer confidence: none" in out


def test_confidence_none_triggers_safe_shape():
    out = provenance.format_provenance(_cand(), "high", _ans(conf="none", no_conclusion=False), now=NOW)
    assert "didn't reach a clear conclusion" in out


def test_empty_answer_triggers_safe_shape():
    out = provenance.format_provenance(_cand(), "high", _ans(answer="", conf="high"), now=NOW)
    assert "didn't reach a clear conclusion" in out


def test_none_answer_triggers_safe_shape():
    out = provenance.format_provenance(_cand(), "high", None, now=NOW)
    assert "didn't reach a clear conclusion" in out


def test_no_conclusion_empty_ruled_out_fallback_bullet():
    out = provenance.format_provenance(_cand(), "high", _ans(no_conclusion=True, ruled_out=()), now=NOW)
    assert "(no recorded investigation details)" in out


def test_low_renders_disambiguation_list():
    cands = [_cand(title=f"t{i}", session_id=f"s{i}") for i in range(3)]
    out = provenance.format_disambiguation(cands, now=NOW)
    assert "1. t0" in out and "2. t1" in out and "3. t2" in out
    assert "Answer:" not in out


def test_disambiguation_caps_at_three():
    cands = [_cand(title=f"t{i}", session_id=f"s{i}") for i in range(5)]
    out = provenance.format_disambiguation(cands, now=NOW)
    assert "4." not in out


def test_disambiguation_empty():
    assert provenance.format_disambiguation([], now=NOW) == "No matching recorded sessions found."


def test_format_no_match():
    assert provenance.format_no_match() == "No matching recorded sessions found."


def test_format_answerer_error_is_graceful():
    out = provenance.format_answerer_error(_cand(title="auth"), "session not found")
    assert "auth" in out and "session not found" in out
    assert out.strip() and "\n" not in out.strip()


def test_missing_title_falls_back():
    out = provenance.format_provenance(_cand(title=""), "high", _ans(), now=NOW)
    assert "untitled session" in out


def test_missing_project_falls_back_to_cwd_basename():
    out = provenance.format_provenance(_cand(cwd="/Users/x/payments"), "high", _ans(), now=NOW)
    assert "· payments ·" in out


def test_missing_project_and_cwd():
    out = provenance.format_provenance(_cand(cwd=""), "high", _ans(), now=NOW)
    assert "unknown project" in out


@pytest.mark.parametrize(
    "offset,expected",
    [(0, "just now"), (5, "5s ago"), (90, "1m ago"), (7200, "2h ago"), (200000, "2d ago")],
)
def test_age_units(offset, expected):
    out = provenance.format_provenance(_cand(mtime=NOW - offset), "high", _ans(), now=NOW)
    assert expected in out.splitlines()[0]


def test_age_future_clamps_just_now():
    out = provenance.format_provenance(_cand(mtime=NOW + 100), "high", _ans(), now=NOW)
    assert "just now" in out.splitlines()[0]


def test_age_missing_unknown():
    assert provenance._format_age(None, NOW) == "unknown age"


def test_unicode_title_preserved():
    out = provenance.format_provenance(_cand(title="auth 🔐 デバッグ"), "high", _ans(), now=NOW)
    assert "auth 🔐 デバッグ" in out
