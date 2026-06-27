"""Spawn the verified ``claude -p --resume`` subprocess and decode its JSON envelope.

This module owns ONLY the outer, stable interface: build the command, run it from the
target project's cwd, decode the envelope, and delegate inner answer parsing to
``prompts.parse_answer``. It never reads the JSONL transcript and never re-derives the
answer contract. Operational failures are *returned* as a typed ``AnswererError``, never
raised.

The flag order is load-bearing and empirically verified: ``--tools ""`` is greedy, so it
must be terminated by ``--disallowedTools`` and never sit last before the positional
prompt — otherwise it swallows the prompt. ``--fork-session`` leaves the original session
untouched; ``--permission-mode plan`` + ``--tools ""`` make recall-only enforceable.
"""
from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from enum import Enum

from prompts import RecallAnswer
from prompts import parse_answer as _default_parse

DEFAULT_TIMEOUT = 120.0
SMOKE_TIMEOUT = 60.0
SMOKE_PROMPT = "Return only: OK"
STDERR_EXCERPT_CHARS = 500
SESSION_NOT_FOUND_SIGNATURES = (
    "no conversation found",
    "no session",
    "session not found",
    "could not find",
    "no such session",
)


class ErrorKind(str, Enum):
    BINARY_NOT_FOUND = "binary_not_found"
    TIMEOUT = "timeout"
    NONZERO_EXIT = "nonzero_exit"
    EMPTY_OUTPUT = "empty_output"
    MALFORMED_JSON = "malformed_json"
    MISSING_RESULT = "missing_result"
    SESSION_NOT_FOUND = "session_not_found"
    ANSWER_PARSE_FAILED = "answer_parse_failed"
    CWD_NOT_FOUND = "cwd_not_found"


@dataclass(frozen=True)
class AnswererError:
    kind: ErrorKind
    message: str
    returncode: int | None = None
    stderr_excerpt: str | None = None


@dataclass(frozen=True)
class AnswererResult:
    ok: bool
    result_text: str | None
    answer: RecallAnswer | None
    error: AnswererError | None
    forked_session_id: str | None


@dataclass(frozen=True)
class SmokeResult:
    ok: bool
    returned_ok: bool
    tools_empty: bool
    detail: str
    error: AnswererError | None = None


def _excerpt(text: str | None) -> str:
    return (text or "").strip()[-STDERR_EXCERPT_CHARS:]


def _matches_session_signature(text: str) -> bool:
    low = (text or "").lower()
    return any(sig in low for sig in SESSION_NOT_FOUND_SIGNATURES)


def _fail(kind, message, *, returncode=None, stderr_excerpt=None) -> AnswererResult:
    return AnswererResult(False, None, None, AnswererError(kind, message, returncode, stderr_excerpt), None)


def _build_command(
    session_id: str | None,
    recall_prompt: str,
    *,
    claude_bin: str = "claude",
    output_format: str = "json",
    verbose: bool = False,
) -> list[str]:
    cmd = [claude_bin, "-p"]
    if session_id:
        cmd += ["--resume", session_id]
    cmd += ["--fork-session", "--permission-mode", "plan", "--output-format", output_format]
    if verbose:
        cmd.append("--verbose")
    # --tools is greedy: the "" then --disallowedTools terminates it; the recall prompt
    # is ALWAYS the final positional argument.
    cmd += ["--tools", "", "--disallowedTools", "mcp__*", "--strict-mcp-config", recall_prompt]
    return cmd


def run_answerer(
    session_id: str,
    target_project_cwd: str,
    recall_prompt: str,
    *,
    timeout: float = DEFAULT_TIMEOUT,
    claude_bin: str = "claude",
    parse_answer=_default_parse,
) -> AnswererResult:
    """Run the recall subprocess and return a typed result. Never raises operationally."""
    if not os.path.isdir(target_project_cwd):
        return _fail(ErrorKind.CWD_NOT_FOUND, f"target project cwd not found: {target_project_cwd}")

    cmd = _build_command(session_id, recall_prompt, claude_bin=claude_bin)
    try:
        # stdin=DEVNULL: when the broker runs as an MCP stdio server, its stdin IS the
        # protocol channel — the resumed claude must never inherit/read it.
        proc = subprocess.run(
            cmd, cwd=target_project_cwd, stdin=subprocess.DEVNULL,
            capture_output=True, text=True, timeout=timeout,
        )
    except FileNotFoundError:
        return _fail(ErrorKind.BINARY_NOT_FOUND, f"claude binary not found: {claude_bin}")
    except subprocess.TimeoutExpired as exc:
        return _fail(ErrorKind.TIMEOUT, f"timed out after {timeout}s", stderr_excerpt=_excerpt(exc.stderr))

    if proc.returncode != 0:
        blob = (proc.stderr or "") + (proc.stdout or "")
        kind = ErrorKind.SESSION_NOT_FOUND if _matches_session_signature(blob) else ErrorKind.NONZERO_EXIT
        return _fail(kind, "claude exited nonzero", returncode=proc.returncode, stderr_excerpt=_excerpt(proc.stderr))

    if not proc.stdout.strip():
        return _fail(ErrorKind.EMPTY_OUTPUT, "claude produced no output", returncode=0, stderr_excerpt=_excerpt(proc.stderr))

    try:
        env = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return _fail(ErrorKind.MALFORMED_JSON, "could not decode claude JSON envelope", returncode=0)

    if (
        not isinstance(env, dict)
        or env.get("is_error")
        or env.get("subtype") not in (None, "success")
        or "result" not in env
        or env.get("result") is None
    ):
        raw = env if isinstance(env, dict) else None
        kind = ErrorKind.SESSION_NOT_FOUND if _matches_session_signature(json.dumps(raw)) else ErrorKind.MISSING_RESULT
        return _fail(kind, "envelope had no usable result", returncode=0)

    result_text = env["result"]
    try:
        answer = parse_answer(result_text)
    except Exception as exc:  # noqa: BLE001 - parse_answer should be total; stay defensive
        return AnswererResult(
            False, result_text, None,
            AnswererError(ErrorKind.ANSWER_PARSE_FAILED, f"parse_answer failed: {exc}"),
            env.get("session_id"),
        )
    return AnswererResult(True, result_text, answer, None, env.get("session_id"))


def smoke_check(*, session_id=None, target_project_cwd=None, claude_bin="claude", timeout=SMOKE_TIMEOUT) -> SmokeResult:
    """Hard gate for the recall-only guarantee: prove the flags work AND no tools load."""
    cmd = _build_command(session_id, SMOKE_PROMPT, claude_bin=claude_bin, output_format="stream-json", verbose=True)
    cwd = target_project_cwd if (target_project_cwd and os.path.isdir(target_project_cwd)) else None
    try:
        proc = subprocess.run(
            cmd, cwd=cwd, stdin=subprocess.DEVNULL,
            capture_output=True, text=True, timeout=timeout,
        )
    except FileNotFoundError:
        return SmokeResult(False, False, False, f"claude binary not found: {claude_bin}",
                           AnswererError(ErrorKind.BINARY_NOT_FOUND, claude_bin))
    except subprocess.TimeoutExpired:
        return SmokeResult(False, False, False, f"smoke timed out after {timeout}s",
                           AnswererError(ErrorKind.TIMEOUT, "timeout"))

    tools = None
    result_text = ""
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if obj.get("type") == "system" and "tools" in obj and tools is None:
            tools = obj.get("tools")
        elif obj.get("type") == "result":
            result_text = obj.get("result", "")

    tools_empty = tools == []
    returned_ok = result_text.strip() == "OK"
    note = "full check" if session_id else "reduced check (no session: flag acceptance + empty tools only)"
    if proc.returncode != 0:
        return SmokeResult(False, returned_ok, tools_empty,
                           f"claude exited {proc.returncode}: {_excerpt(proc.stderr)}",
                           AnswererError(ErrorKind.NONZERO_EXIT, "smoke nonzero", proc.returncode, _excerpt(proc.stderr)))
    ok = bool(returned_ok and tools_empty)
    return SmokeResult(ok, returned_ok, tools_empty, f"{note}; tools_empty={tools_empty}, returned_ok={returned_ok}", None)
