"""Test helpers: synthesize Claude Code session transcripts on disk.

Grounded in the real layout: ``~/.claude/projects/<slug>/<session-id>.jsonl`` where
``slug`` is the session cwd with every ``/`` and ``.`` replaced by ``-``. Transcripts are
append-only JSONL, one object per line. Tests only need titles, cwd and user/assistant
text, so this stays deliberately light.
"""
from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path


def slug_for(cwd: str) -> str:
    """Claude Code project slug for a working directory."""
    return cwd.replace("/", "-").replace(".", "-")


def write_transcript(
    projects_root: Path,
    session_id: str,
    cwd: str,
    *,
    title: str | None = None,
    turns: Iterable[tuple[str, str]] = (),
) -> Path:
    """Write a synthetic transcript under ``projects_root`` and return its path.

    ``turns`` is an iterable of ``(role, text)`` pairs where role is ``"user"`` or
    ``"assistant"``.
    """
    directory = projects_root / slug_for(cwd)
    directory.mkdir(parents=True, exist_ok=True)
    records: list[dict] = []
    if title is not None:
        records.append({"type": "ai-title", "title": title, "sessionId": session_id})
    for role, text in turns:
        records.append(
            {
                "type": role,
                "sessionId": session_id,
                "cwd": cwd,
                "message": {"role": role, "content": [{"type": "text", "text": text}]},
            }
        )
    path = directory / f"{session_id}.jsonl"
    path.write_text("".join(json.dumps(r) + "\n" for r in records))
    return path
