"""Measure one `claude -p` call and read its cost/token/latency.

The `--output-format json` envelope already carries `total_cost_usd` and a `usage` block
(`input_tokens`, `output_tokens`, `cache_*`) — the production answerer just discards them.
This module is the thin parser the benchmark uses instead, plus a wall-clock timer and the
token heuristic that sizes transcripts and prices the "read it yourself" baseline.
"""
from __future__ import annotations

import json
import subprocess
import time
from dataclasses import dataclass

CONTEXT_WINDOW = 1_000_000  # tokens; beyond this the read-it-yourself baseline overflows


@dataclass(frozen=True)
class Run:
    stdout: str
    stderr: str
    returncode: int
    latency_ms: float


def measure(cmd: list[str], *, input: str | None = None, cwd: str | None = None, timeout: float = 300) -> Run:
    """Run a command, wall-clock it. stdin is DEVNULL unless `input` is given."""
    t0 = time.monotonic()
    proc = subprocess.run(
        cmd,
        input=input,
        cwd=cwd,
        stdin=None if input is not None else subprocess.DEVNULL,
        capture_output=True,
        text=True,
        errors="replace",
        timeout=timeout,
    )
    return Run(proc.stdout, proc.stderr, proc.returncode, (time.monotonic() - t0) * 1000)


def envelope_metrics(stdout: str) -> dict | None:
    """Pull cost/tokens/result out of a `claude -p --output-format json` envelope."""
    try:
        env = json.loads(stdout)
    except (ValueError, TypeError):
        return None
    if not isinstance(env, dict):
        return None
    usage = env.get("usage") or {}
    return {
        "cost_usd": env.get("total_cost_usd"),
        "input_tokens": usage.get("input_tokens", 0) or 0,
        "output_tokens": usage.get("output_tokens", 0) or 0,
        "cache_read_tokens": usage.get("cache_read_input_tokens", 0) or 0,
        "cache_creation_tokens": usage.get("cache_creation_input_tokens", 0) or 0,
        "result_text": env.get("result"),
        "is_error": bool(env.get("is_error")),
        "session_id": env.get("session_id"),
    }


def count_tokens(text: str) -> int:
    # ponytail: ~4 chars/token is close enough to size transcripts; swap for tiktoken only
    # if a graphed point visibly disagrees with a measured total_cost_usd.
    return max(1, len(text) // 4)


def _selftest() -> None:
    m = envelope_metrics('{"total_cost_usd": 0.02, "usage": {"input_tokens": 10, "output_tokens": 5}, "result": "hi"}')
    assert m["cost_usd"] == 0.02 and m["input_tokens"] == 10 and m["result_text"] == "hi"
    assert envelope_metrics("not json") is None
    assert envelope_metrics("[1,2,3]") is None  # valid json, wrong shape
    assert count_tokens("") == 1 and count_tokens("a" * 400) == 100
    print("usage.py selftest ok")


if __name__ == "__main__":
    _selftest()
