"""Pure formatting of yoink's final user-facing output.

No I/O, no subprocess, no clock except an injectable ``now``. Consumes the frozen
dataclasses (``Candidate``, ``RecallAnswer``) directly — no dict adaptation. Compact by
default, both confidences shown, a safe-failure shape when there is no clear conclusion,
and the source_match surfaces (``medium`` confirm-note, ``low`` disambiguation).
"""
from __future__ import annotations

import os
import time

from prompts import RecallAnswer
from resolver import Candidate

_NO_MATCH = "No matching recorded sessions found."


def _title(candidate: Candidate) -> str:
    return candidate.title or "untitled session"


def _project(candidate: Candidate) -> str:
    cwd = candidate.target_project_cwd
    if not cwd:
        return "unknown project"
    return os.path.basename(cwd.rstrip("/")) or "unknown project"


def _format_age(mtime: float | None, now: float) -> str:
    if mtime is None:
        return "unknown age"
    delta = max(0.0, now - mtime)
    if delta < 1:
        return "just now"
    if delta < 60:
        return f"{int(delta)}s ago"
    if delta < 3600:
        return f"{int(delta // 60)}m ago"
    if delta < 86400:
        return f"{int(delta // 3600)}h ago"
    return f"{int(delta // 86400)}d ago"


def _oneliner(candidate: Candidate, source_match: str, confidence: str, now: float) -> str:
    return (
        f"From {_title(candidate)} · {_project(candidate)} · {_format_age(candidate.mtime, now)}"
        f" · source match: {source_match.lower()} · answer confidence: {confidence.lower()}"
    )


def _summarize(items: list[str], limit: int = 3) -> str:
    text = ", ".join(items[:limit])
    if len(items) > limit:
        text += f" (+{len(items) - limit} more)"
    return text


def _is_safe_shape(answer: RecallAnswer | None) -> bool:
    return (
        answer is None
        or answer.no_conclusion
        or answer.answer_confidence.lower() == "none"
        or not answer.answer.strip()
    )


def _no_conclusion_shape(candidate: Candidate, source_match: str, answer: RecallAnswer | None, now: float) -> str:
    ruled = answer.ruled_out if answer else []
    lines = [
        "I found the likely session, but it didn't reach a clear conclusion.",
        "What it did contain:",
    ]
    lines += [f"- {item}" for item in ruled] if ruled else ["- (no recorded investigation details)"]
    lines.append("Source: " + _oneliner(candidate, source_match, "none", now))
    return "\n".join(lines)


def format_provenance(
    candidate: Candidate,
    source_match: str,
    answer: RecallAnswer | None,
    *,
    now: float | None = None,
) -> str:
    """Compact one-liner + answer (or the safe no-conclusion shape). Never includes Details."""
    now = time.time() if now is None else now
    if _is_safe_shape(answer):
        return _no_conclusion_shape(candidate, source_match, answer, now)
    lines = [
        _oneliner(candidate, source_match, answer.answer_confidence, now),
        f"Answer: {answer.answer.strip()}",
    ]
    if answer.ruled_out:
        lines.append(f"Ruled out: {_summarize(answer.ruled_out)}")
    if source_match.lower() == "medium":
        lines += [
            "",
            "Note: medium source match — confirm this is the right session before any"
            " irreversible or code-changing action.",
        ]
    return "\n".join(lines)


def format_disambiguation(candidates: list[Candidate], *, now: float | None = None) -> str:
    now = time.time() if now is None else now
    if not candidates:
        return _NO_MATCH
    lines = ["Which session do you mean?"]
    for index, candidate in enumerate(candidates[:3], 1):
        lines.append(f"{index}. {_title(candidate)} · {_project(candidate)} · {_format_age(candidate.mtime, now)}")
    lines.append("Reply with the number, or rephrase the hint.")
    return "\n".join(lines)


def format_no_match() -> str:
    return _NO_MATCH


def format_answerer_error(candidate: Candidate, message: str) -> str:
    return f"Couldn't recall from {_title(candidate)}: {message}"
