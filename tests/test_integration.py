"""Live end-to-end gate: the full pipeline against a real resumable session.

This is the canonical proof that yoink recalls the *ratified* conclusion (not an
abandoned dead end) through the production ``--resume`` mechanism. It builds a real,
messy two-turn session with the live ``claude`` CLI, then drives the real answerer and
the real broker tool against it.

Gated: skipped unless ``YOINK_INTEGRATION=1`` and the ``claude`` CLI is on PATH, so the
default ``uv run pytest`` stays offline and deterministic.
"""
import json
import os
import shutil
import subprocess

import pytest
from fastmcp import Client

import yoink.server as broker
import yoink.prompts as prompts
from yoink.answerer import run_answerer
from yoink.resolver import Candidate, ResolveResult

pytestmark = [
    pytest.mark.eval,
    pytest.mark.skipif(
        os.environ.get("YOINK_INTEGRATION") != "1" or shutil.which("claude") is None,
        reason="set YOINK_INTEGRATION=1 with the claude CLI on PATH to run live integration",
    ),
]


def _turn(prompt: str, cwd: str, *, resume: str | None = None) -> dict:
    cmd = ["claude", "-p"]
    if resume:
        cmd += ["--resume", resume]
    cmd += ["--output-format", "json", "--tools", ""]  # prompt via stdin (avoids greedy --tools)
    proc = subprocess.run(cmd, input=prompt, cwd=cwd, capture_output=True, text=True, timeout=180)
    proc.check_returncode()
    return json.loads(proc.stdout)


def _make_messy_session(project: str) -> str:
    """A real session that guesses the cache, rules it out, then ratifies token refresh."""
    first = _turn(
        "We are debugging: auth requests fail intermittently about an hour after deploy. "
        "My first hypothesis is the cache holding a stale entry. Reply in one short sentence.",
        project,
    )
    sid = first["session_id"]
    _turn(
        "Update: ruled out the cache (its TTL is 30s, far under an hour). The real cause is the "
        "token refresh path reusing an access token that is already expired at the 1h mark. "
        "Reply in one short sentence.",
        project,
        resume=sid,
    )
    return sid


def test_run_answerer_recalls_ratified_conclusion(tmp_path):
    project = tmp_path / "proj"
    project.mkdir()
    sid = _make_messy_session(str(project))

    recall = prompts.build_recall_prompt("What did you conclude was causing the auth failures?")
    result = run_answerer(sid, str(project), recall)

    assert result.ok, result.error
    answer = result.answer
    assert "token refresh" in answer.answer.lower()  # the ratified conclusion survives
    # The dead end is recorded as ruled-out (it may also be *named* as ruled-out in the
    # answer prose — "not the cache" — which is correct, not a leak).
    assert "cache" in " ".join(answer.ruled_out).lower()


async def test_broker_tool_end_to_end(tmp_path, monkeypatch):
    project = tmp_path / "proj2"
    project.mkdir()
    sid = _make_messy_session(str(project))

    # Headless `claude -p` sessions aren't written under ~/.claude/projects, so the real
    # resolver (which scans that dir for interactive peer sessions) can't discover them.
    # Inject the candidate and exercise the rest: broker -> real answerer -> real
    # provenance against the live session. Resolver discovery is covered by its own unit tests.
    candidate = Candidate(sid, str(project), "auth-debugging", 1000.0, 5.0)
    monkeypatch.setattr(broker.resolver, "resolve", lambda *a, **k: ResolveResult("high", [candidate]))

    async with Client(broker.mcp) as client:
        res = await client.call_tool(
            "ask_recorded_session",
            {"peer_hint": "auth", "question": "What did you conclude was causing the auth failures?"},
        )
    out = res.data if getattr(res, "data", None) is not None else res.content[0].text
    assert "token refresh" in out.lower()
