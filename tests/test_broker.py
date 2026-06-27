from types import SimpleNamespace

import pytest
from fastmcp import Client

import broker
from prompts import RecallAnswer
from resolver import Candidate, ResolveResult


def _cand(session_id="s1", cwd="/p/payments", title="auth-debugging", mtime=1000.0):
    return Candidate(session_id, cwd, title, mtime, 5.0)


def _raise(*_a, **_k):
    raise AssertionError("must not be called")


def _boom_runtime(*_a, **_k):
    raise RuntimeError("kaboom")


async def _call(peer_hint="auth", question="what?"):
    async with Client(broker.mcp) as client:
        res = await client.call_tool("ask_recorded_session", {"peer_hint": peer_hint, "question": question})
    return res.data if getattr(res, "data", None) is not None else res.content[0].text


async def test_tool_is_registered_and_described():
    async with Client(broker.mcp) as client:
        tools = await client.list_tools()
    tool = next(t for t in tools if t.name == "ask_recorded_session")
    assert tool.description and "recorded" in tool.description.lower()
    props = tool.inputSchema["properties"]
    assert "peer_hint" in props and "question" in props


async def test_high_match_calls_answerer_and_returns_formatted(monkeypatch):
    monkeypatch.setattr(broker.resolver, "resolve", lambda *a, **k: ResolveResult("high", [_cand()]))
    monkeypatch.setattr(broker.prompts, "build_recall_prompt", lambda q: "BUILT:" + q)
    calls = {}

    def fake_run(session_id, cwd, recall_prompt):
        calls["args"] = (session_id, cwd, recall_prompt)
        return SimpleNamespace(ok=True, answer=SimpleNamespace(), error=None)

    monkeypatch.setattr(broker.answerer, "run_answerer", fake_run)
    got = {}

    def fake_fmt(candidate, source_match, answer, **k):
        got["sm"] = source_match
        return "FORMATTED"

    monkeypatch.setattr(broker.provenance, "format_provenance", fake_fmt)
    out = await _call(question="why?")
    assert out == "FORMATTED"
    assert calls["args"] == ("s1", "/p/payments", "BUILT:why?")
    assert got["sm"] == "high"


async def test_medium_match_passes_medium_to_formatter(monkeypatch):
    monkeypatch.setattr(broker.resolver, "resolve", lambda *a, **k: ResolveResult("medium", [_cand()]))
    monkeypatch.setattr(broker.prompts, "build_recall_prompt", lambda q: q)
    monkeypatch.setattr(broker.answerer, "run_answerer",
                        lambda *a, **k: SimpleNamespace(ok=True, answer=SimpleNamespace(), error=None))
    got = {}

    def fake_fmt(c, sm, a, **k):
        got["sm"] = sm
        return "X"

    monkeypatch.setattr(broker.provenance, "format_provenance", fake_fmt)
    await _call()
    assert got["sm"] == "medium"


async def test_low_match_disambiguates_without_calling_answerer(monkeypatch):
    cands = [_cand("a"), _cand("b"), _cand("c")]
    monkeypatch.setattr(broker.resolver, "resolve", lambda *a, **k: ResolveResult("low", cands))
    monkeypatch.setattr(broker.answerer, "run_answerer", _raise)
    seen = {}

    def fake_dis(c, **k):
        seen["n"] = len(c)
        return "DISAMBIG"

    monkeypatch.setattr(broker.provenance, "format_disambiguation", fake_dis)
    out = await _call()
    assert out == "DISAMBIG"
    assert seen["n"] <= 3


async def test_no_candidates_returns_no_match(monkeypatch):
    monkeypatch.setattr(broker.resolver, "resolve", lambda *a, **k: ResolveResult("low", []))
    monkeypatch.setattr(broker.answerer, "run_answerer", _raise)
    monkeypatch.setattr(broker.provenance, "format_no_match", lambda: "NOMATCH")
    assert await _call() == "NOMATCH"


async def test_unknown_source_match_treated_as_disambiguation(monkeypatch):
    monkeypatch.setattr(broker.resolver, "resolve", lambda *a, **k: ResolveResult("weird", [_cand()]))
    monkeypatch.setattr(broker.answerer, "run_answerer", _raise)
    monkeypatch.setattr(broker.provenance, "format_disambiguation", lambda c, **k: "DIS")
    assert await _call() == "DIS"


async def test_answerer_error_is_graceful(monkeypatch):
    monkeypatch.setattr(broker.resolver, "resolve", lambda *a, **k: ResolveResult("high", [_cand()]))
    monkeypatch.setattr(broker.prompts, "build_recall_prompt", lambda q: q)
    monkeypatch.setattr(broker.answerer, "run_answerer",
                        lambda *a, **k: SimpleNamespace(ok=False, error=SimpleNamespace(message="boom"), answer=None))
    monkeypatch.setattr(broker.provenance, "format_answerer_error", lambda c, msg: f"ERR:{msg}")
    assert await _call() == "ERR:boom"


async def test_resolver_exception_is_graceful(monkeypatch):
    monkeypatch.setattr(broker.resolver, "resolve", _boom_runtime)
    out = await _call()
    assert isinstance(out, str) and "could not complete" in out


async def test_empty_question_short_circuits(monkeypatch):
    monkeypatch.setattr(broker.resolver, "resolve", _raise)
    out = await _call(question="   ")
    assert "Ask a question" in out


async def test_answer_confidence_none_uses_real_provenance_safe_failure(monkeypatch):
    monkeypatch.setattr(broker.resolver, "resolve", lambda *a, **k: ResolveResult("high", [_cand()]))
    monkeypatch.setattr(broker.prompts, "build_recall_prompt", lambda q: q)
    ans = RecallAnswer(answer="", answer_confidence="none", ruled_out=["cache", "db"], no_conclusion=True)
    monkeypatch.setattr(broker.answerer, "run_answerer",
                        lambda *a, **k: SimpleNamespace(ok=True, answer=ans, error=None))
    out = await _call()  # real provenance (not patched)
    assert "didn't reach a clear conclusion" in out
    assert "cache" in out


async def test_result_is_always_string(monkeypatch):
    monkeypatch.setattr(broker.resolver, "resolve", lambda *a, **k: ResolveResult("low", [_cand()]))
    assert isinstance(await _call(), str)


def test_run_health_pass(monkeypatch):
    monkeypatch.setattr(broker.shutil, "which", lambda _: "/usr/bin/claude")
    monkeypatch.setattr(broker.answerer, "smoke_check", lambda **k: SimpleNamespace(ok=True, detail="all good"))
    assert broker.run_health() == 0


def test_run_health_fail_on_missing_cli(monkeypatch):
    monkeypatch.setattr(broker.shutil, "which", lambda _: None)
    called = {"smoke": False}
    monkeypatch.setattr(broker.answerer, "smoke_check", lambda **k: called.update(smoke=True))
    assert broker.run_health() == 1
    assert called["smoke"] is False


def test_run_health_fail_on_smoke(monkeypatch):
    monkeypatch.setattr(broker.shutil, "which", lambda _: "/usr/bin/claude")
    monkeypatch.setattr(broker.answerer, "smoke_check", lambda **k: SimpleNamespace(ok=False, detail="tools present"))
    assert broker.run_health() == 1


def test_main_no_args_runs_mcp_stdio(monkeypatch):
    ran = {"n": 0}
    monkeypatch.setattr(broker.mcp, "run", lambda *a, **k: ran.update(n=ran["n"] + 1))
    broker.main([])
    assert ran["n"] == 1


def test_main_health_exits_with_health_code(monkeypatch):
    monkeypatch.setattr(broker, "run_health", lambda: 1)
    ran = {"n": 0}
    monkeypatch.setattr(broker.mcp, "run", lambda *a, **k: ran.update(n=1))
    with pytest.raises(SystemExit) as exc:
        broker.main(["--health"])
    assert exc.value.code == 1
    assert ran["n"] == 0
