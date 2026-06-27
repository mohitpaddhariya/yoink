"""CLI to test yoink without an MCP client: resolve a peer session and recall an answer.

Usage:
    uv run python ask.py [--cwd DIR] [--all] "<peer hint>" "<question>"

Examples:
    uv run python ask.py --all "staging selfhost" "what is the deployment status?"
    uv run python ask.py --cwd ~/work/api "auth api endpoint" "which endpoint did you find?"

``--all`` searches across every project; otherwise only ``--cwd``'s project is scanned
(the same default-deny privacy bound the MCP tool uses).
"""
from __future__ import annotations

import argparse
import os
import sys

from . import server


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="yoink-ask", description="Ask another Claude session's recorded work.")
    parser.add_argument("hint", help="natural description of the target session, e.g. 'the auth debugging one'")
    parser.add_argument("question", help="what to ask that session")
    parser.add_argument("--cwd", default=None, help="caller project dir (default: current directory)")
    parser.add_argument("--all", action="store_true", help="search across all projects (default: only --cwd's project)")
    args = parser.parse_args(argv)

    caller_cwd = os.path.abspath(os.path.expanduser(args.cwd)) if args.cwd else os.getcwd()
    print(
        server.recall(
            args.hint,
            args.question,
            caller_cwd=caller_cwd,
            caller_session_id=os.environ.get("CLAUDE_SESSION_ID"),
            cross_project=args.all,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
