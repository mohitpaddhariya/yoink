"""yoink MCP server: one tool wiring resolver -> answerer -> provenance.

Pure orchestration glue. The tool ALWAYS returns a string and never raises to the
client; the blocking answerer runs off the event loop via ``asyncio.to_thread``. This
module holds no knowledge of JSONL, flags, prompts, or formatting — it just routes.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import shutil
import sys

from fastmcp import FastMCP

from . import answerer, config, prompts, provenance, resolver

mcp = FastMCP("yoink")


def recall(
    peer_hint: str,
    question: str,
    *,
    caller_cwd: str,
    caller_session_id: str | None,
    cross_project: bool = False,
) -> str:
    """The full resolve → answer → provenance flow. Blocking; never raises.

    Shared by the MCP tool and the ``ask.py`` CLI so both behave identically.
    """
    if not question or not question.strip():
        return 'Ask a question, e.g. "yoink what the auth session concluded about token refresh".'
    try:
        resolution = resolver.resolve(peer_hint, caller_session_id, caller_cwd, cross_project=cross_project)
        if not resolution.candidates:
            return provenance.format_no_match()
        if resolution.source_match not in ("high", "medium"):
            return provenance.format_disambiguation(resolution.candidates[:3])
        best = resolution.candidates[0]
        recall_prompt = prompts.build_recall_prompt(question)
        cfg = config.load_config()
        result = answerer.run_answerer(
            best.session_id, best.target_project_cwd, recall_prompt,
            model=cfg.model, timeout=cfg.timeout,
        )
        if not result.ok:
            message = result.error.message if result.error else "unknown error"
            excerpt = getattr(result.error, "stderr_excerpt", None)
            if excerpt:
                message = f"{message} — {excerpt}"
            return provenance.format_answerer_error(best, message)
        return provenance.format_provenance(best, resolution.source_match, result.answer)
    except Exception as exc:  # noqa: BLE001 - never raise to the caller
        return f"yoink could not complete: {exc}"


@mcp.tool()
async def ask_recorded_session(peer_hint: str, question: str) -> str:
    """Grab a focused answer from another Claude session's RECORDED work.

    Use this when the user wants what a *different or earlier* Claude session already
    figured out, instead of redoing it — e.g. "yoink what the auth session concluded
    about token refresh", "ask the other Claude what it found about the slow query",
    "what did the session debugging checkout decide?".

    It reads the peer's recorded transcript read-only (resumed in a forked, tool-disabled
    process) — it never interrupts a live session, and answers reflect the peer's last
    saved turn. It searches across all of your recorded sessions and ranks them by topic.

    Args:
        peer_hint: a natural description of the target session ("the auth debugging one").
        question: what to ask that session.

    Returns a focused answer with provenance, a short disambiguation list, or a no-match
    message.
    """
    try:
        caller_cwd = os.getcwd()
    except OSError:
        caller_cwd = ""
    # Claude Code exports CLAUDE_CODE_SESSION_ID (not CLAUDE_SESSION_ID); needed so the
    # resolver excludes the caller's own live session from being returned as a "peer".
    caller_session_id = os.environ.get("CLAUDE_CODE_SESSION_ID") or os.environ.get("CLAUDE_SESSION_ID")
    return await asyncio.to_thread(
        recall,
        peer_hint,
        question,
        caller_cwd=caller_cwd,
        caller_session_id=caller_session_id,
        # An MCP server can't know which repo the asking session is in, so search across
        # all the user's own sessions (single-user localhost; per-repo scoping returns with sharing).
        cross_project=True,
    )


def run_health() -> int:
    """0 healthy / 1 unhealthy. The recall-only smoke gate; does not call sys.exit."""
    if shutil.which("claude") is None:
        print("FAIL: claude CLI not found on PATH")
        return 1
    result = answerer.smoke_check()
    print(("OK: " if result.ok else "FAIL: ") + result.detail)
    return 0 if result.ok else 1


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="yoink", description="yoink MCP server")
    parser.add_argument("--health", action="store_true", help="run the recall-only smoke gate and exit")
    args = parser.parse_args(argv)
    if args.health:
        sys.exit(run_health())
    mcp.run()


if __name__ == "__main__":
    main()
