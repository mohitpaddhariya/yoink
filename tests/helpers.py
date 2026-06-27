"""Test helpers: synthesize Claude Code session transcripts on disk.

Grounded in the real layout (verified against ~/.claude/projects): transcripts live at
``<projects_root>/<slug>/<session-id>.jsonl`` where ``slug`` is the cwd with every ``/``
and ``.`` replaced by ``-``, append-only JSONL. Titles are *separate* records: type
``ai-title`` (field ``aiTitle``) and ``custom-title`` (field ``customTitle``), appended
over time so the latest wins. Kept light: tests need cwd, titles and user/assistant text.
"""
from __future__ import annotations

import json
import os
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
    turns: Iterable[tuple[str, str]] = (),
    titles: Iterable[tuple[str, str]] = (),
    mtime: float | None = None,
) -> Path:
    """Write a synthetic transcript and return its path.

    ``turns``: ``(role, text)`` pairs (role ``"user"``/``"assistant"``), written first.
    ``titles``: ``(kind, text)`` pairs (kind ``"ai"``/``"custom"``), appended after the
    turns in order — later entries are "fresher", mirroring real transcripts.
    ``mtime``: if given, stamp the file mtime for deterministic recency ranking.
    """
    directory = projects_root / slug_for(cwd)
    directory.mkdir(parents=True, exist_ok=True)
    records: list[dict] = []
    for role, text in turns:
        records.append(
            {
                "type": role,
                "sessionId": session_id,
                "cwd": cwd,
                "message": {"role": role, "content": [{"type": "text", "text": text}]},
            }
        )
    for kind, text in titles:
        if kind == "custom":
            records.append({"type": "custom-title", "customTitle": text, "sessionId": session_id})
        else:
            records.append({"type": "ai-title", "aiTitle": text, "sessionId": session_id})
    path = directory / f"{session_id}.jsonl"
    path.write_text("".join(json.dumps(r) + "\n" for r in records))
    if mtime is not None:
        os.utime(path, (mtime, mtime))
    return path
