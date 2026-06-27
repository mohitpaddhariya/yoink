"""First-time yoink setup: config, MCP registration, CLAUDE.md auto-use rule, health check.

  uv run python install.py                 # interactive (prompts for the recall model)
  uv run python install.py --model claude-haiku-4-5 --scope user --yes
  uv run python install.py --no-mcp --no-claude-md   # config only

Steps (each can be skipped):
  1. write the recall model to the config file (config.py)
  2. register the yoink MCP server (claude mcp add)
  3. patch your CLAUDE.md so Claude reaches for yoink instead of native transcript search
  4. run the recall-only health check
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

from . import config

REPO = Path(__file__).resolve().parents[2]

BEGIN = "<!-- yoink:begin (managed by yoink install) -->"
END = "<!-- yoink:end -->"
RULE = f"""{BEGIN}
## Recalling other Claude sessions — use yoink

When the user asks what a **different or earlier Claude session** concluded, decided, or found —
or whenever answering would otherwise mean searching or reading another session's transcript —
use the `ask_recorded_session` (yoink) MCP tool **instead of a native search or grepping
transcripts yourself**. It resumes the peer session read-only and returns its conclusion with
provenance, far more cheaply than loading a transcript into context. If you suspect the answer
lives in another session, prefer yoink.
{END}"""


def patch_claude_md(path: Path) -> str:
    """Insert/refresh the yoink rule block in ``path`` idempotently. Returns the action."""
    text = path.read_text() if path.exists() else ""
    if BEGIN in text and END in text:
        pre, rest = text.split(BEGIN, 1)
        _, post = rest.split(END, 1)
        new = f"{pre.rstrip()}\n\n{RULE}\n{post.lstrip(chr(10))}"
        action = "updated"
    else:
        prefix = f"{text.rstrip()}\n\n" if text.strip() else ""
        new = f"{prefix}{RULE}\n"
        action = "created" if not text.strip() else "appended"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(new)
    return action


def default_claude_md() -> Path:
    base = os.environ.get("CLAUDE_CONFIG_DIR")
    return (Path(base) if base else (Path.home() / ".claude")) / "CLAUDE.md"


def _run(cmd: list[str]) -> tuple[int, str]:
    proc = subprocess.run(cmd, capture_output=True, text=True)
    out = (proc.stdout or proc.stderr).strip().splitlines()
    return proc.returncode, (out[-1] if out else "")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="yoink-install", description="Set up the yoink MCP server.")
    parser.add_argument("--model", default=None, help="recall model (default: prompt / claude-haiku-4-5)")
    parser.add_argument("--scope", choices=["user", "local"], default="user", help="claude mcp add scope")
    parser.add_argument("--claude-md", default=None, help="CLAUDE.md to patch (default: your global one)")
    parser.add_argument("--no-mcp", action="store_true", help="skip claude mcp add")
    parser.add_argument("--no-claude-md", action="store_true", help="skip the CLAUDE.md auto-use rule")
    parser.add_argument("--yes", action="store_true", help="non-interactive; accept defaults")
    args = parser.parse_args(argv)

    model = args.model
    if model is None and sys.stdin.isatty() and not args.yes:
        prompt = f"Recall model [{config.DEFAULT_MODEL}] (haiku=cheapest · claude-sonnet-4-6 · claude-opus-4-8=richest): "
        model = input(prompt).strip() or config.DEFAULT_MODEL
    model = model or config.DEFAULT_MODEL

    path = config.save_config(model=model)
    print(f"✓ config written: {path}  (model={model})")

    if not args.no_mcp:
        cmd = ["claude", "mcp", "add", "--scope", args.scope, "yoink", "--",
               "uv", "run", "--directory", str(REPO), "yoink"]
        code, line = _run(cmd)
        print(("✓ " if code == 0 else "✗ ") + f"claude mcp add ({args.scope}): {line}")

    if not args.no_claude_md:
        target = Path(args.claude_md).expanduser() if args.claude_md else default_claude_md()
        action = patch_claude_md(target)
        print(f"✓ CLAUDE.md {action}: {target}")

    code, line = _run(["uv", "run", "--directory", str(REPO), "yoink", "--health"])
    print(("✓ " if code == 0 else "✗ ") + f"health: {line}")
    print("\nDone. Start a new Claude session and ask, e.g., \"what did the auth session conclude?\"")
    return 0


if __name__ == "__main__":
    sys.exit(main())
