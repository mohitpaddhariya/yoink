"""Discover candidate sessions under ~/.claude/projects and rank them against a hint.

Transcripts are read LIGHTLY and defensively (titles + last assistant text, bounded
head/tail) because the JSONL schema is internal and unstable — discovery degrades
rather than crashes, and answering never relies on it. Enforces the privacy bound
(default-deny cross-project) and excludes the caller's own session plus yoink's own
recall forks.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

def default_projects_root() -> Path:
    """Where Claude Code stores transcripts, honoring ``CLAUDE_CONFIG_DIR``.

    Custom config profiles (``CLAUDE_CONFIG_DIR=~/.claude-personal``) keep their
    transcripts under that dir, not ``~/.claude`` — so discovery must follow it.
    """
    config_dir = os.environ.get("CLAUDE_CONFIG_DIR") or str(Path.home() / ".claude")
    return Path(config_dir) / "projects"


# Ranking weights / thresholds — pinned so source_match labels stay deterministic.
TITLE_W = 3.0
BODY_W = 1.0
HIGH_MIN = 2.0
HIGH_MARGIN = 1.5
HEAD_BYTES = 16_384
TAIL_BYTES = 32_768

_STOPWORDS = frozenset(
    "the a an this that for about with and to of in on is it my our session claude"
    " debug debugging issue issues fix fixing bug bugs why what".split()
)

# A stable phrase from prompts.build_recall_prompt; its presence marks a yoink fork.
_FORK_MARKER = "asked ONE question by a peer tool"


@dataclass(frozen=True)
class Candidate:
    session_id: str
    target_project_cwd: str
    title: str
    mtime: float
    score: float = 0.0


@dataclass(frozen=True)
class ResolveResult:
    source_match: str  # "high" | "medium" | "low"
    candidates: list[Candidate]


def cwd_to_slug(cwd: str) -> str:
    """Claude Code project slug: every non-alphanumeric char becomes ``-``. Lossy, non-invertible.

    Claude maps ALL non-alphanumerics (``/``, ``.``, ``_``, spaces, parens, …) to ``-``; matching that
    is what lets a project at e.g. ``/Users/me/My Project`` or ``/srv/app (2)`` resolve to its real
    dir instead of a slug that preserves the space/paren and points nowhere.
    """
    return re.sub(r"[^A-Za-z0-9]", "-", cwd)


def _tokenize(text: str) -> set[str]:
    tokens = set()
    for raw in text.lower().replace("/", " ").replace("-", " ").replace("_", " ").split():
        word = "".join(ch for ch in raw if ch.isalnum())
        if len(word) > 1 and word not in _STOPWORDS:
            tokens.add(word)
    return tokens


def _message_text(record: dict) -> str:
    message = record.get("message")
    if not isinstance(message, dict):
        return ""
    content = message.get("content")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = [b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"]
        return " ".join(p for p in parts if p).strip()
    return ""


def _bounded_objs(path: Path) -> list[dict]:
    """Parse JSON objects from the head and tail of a file without loading it whole."""
    size = path.stat().st_size
    if size == 0:
        return []
    with path.open("rb") as handle:
        if size <= HEAD_BYTES + TAIL_BYTES:
            parts = [(handle.read(), False)]
        else:
            head = handle.read(HEAD_BYTES)
            handle.seek(size - TAIL_BYTES)
            parts = [(head, False), (handle.read(), True)]
    objs: list[dict] = []
    for data, is_tail in parts:
        lines = data.decode("utf-8", "replace").split("\n")
        if is_tail:
            lines = lines[1:]  # drop the partial first line of the tail chunk
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except ValueError:
                continue
            if isinstance(obj, dict):
                objs.append(obj)
    return objs


@dataclass
class _Meta:
    session_id: str
    mtime: float
    cwd: str | None
    title: str
    last_text: str
    is_fork: bool


def _read_meta(path: Path) -> _Meta | None:
    try:
        mtime = path.stat().st_mtime
        objs = _bounded_objs(path)
    except OSError:
        return None
    if not objs:
        return None
    cwd = None
    ai_title = custom_title = first_user = None
    last_text = ""
    is_fork = False
    for record in objs:
        kind = record.get("type")
        if kind in ("user", "assistant"):
            if cwd is None and isinstance(record.get("cwd"), str):
                cwd = record["cwd"]
            text = _message_text(record)
            if not text:
                continue
            if _FORK_MARKER in text:
                is_fork = True
            if kind == "assistant":
                last_text = text
            elif first_user is None:
                first_user = text
        elif kind == "ai-title":
            ai_title = record.get("aiTitle") or ai_title
        elif kind == "custom-title":
            custom_title = record.get("customTitle") or custom_title
    title = (
        custom_title
        or ai_title
        or (first_user[:80] if first_user else None)
        or (last_text[:80] if last_text else None)
        or "(untitled)"
    )
    return _Meta(path.stem, mtime, cwd, title, last_text, is_fork)


def _candidate_dirs(projects_root: Path, caller_cwd: str, cross_project: bool) -> list[Path]:
    if not projects_root.is_dir():
        return []
    if cross_project:
        return [d for d in projects_root.iterdir() if d.is_dir()]
    own = projects_root / cwd_to_slug(caller_cwd)
    return [own] if own.is_dir() else []


def _iter_session_files(dirs: list[Path]):
    for directory in dirs:
        try:
            entries = sorted(directory.iterdir())
        except OSError:
            continue
        for path in entries:
            if path.is_file() and path.suffix == ".jsonl":
                yield path


def _score(meta: _Meta, hint_tokens: set[str]) -> float:
    if not hint_tokens:
        return 0.0
    title_hits = len(hint_tokens & _tokenize(meta.title))
    body_hits = len(hint_tokens & _tokenize(meta.last_text))
    return TITLE_W * title_hits + BODY_W * body_hits


def _classify(ranked: list[Candidate], hint_tokens: set[str], top_n: int) -> ResolveResult:
    if not ranked:
        return ResolveResult("low", [])
    top = ranked[0]
    if not hint_tokens or top.score == 0.0:
        return ResolveResult("low", ranked[:top_n])
    clear = len(ranked) == 1 or (top.score - ranked[1].score) >= HIGH_MARGIN
    if top.score >= HIGH_MIN and clear:
        return ResolveResult("high", [top])
    return ResolveResult("medium", [top])


def resolve(
    peer_hint: str,
    caller_session_id: str | None,
    caller_cwd: str,
    *,
    projects_root: Path | str | None = None,
    cross_project: bool = False,
    top_n: int = 3,
) -> ResolveResult:
    """Find and rank candidate sessions for ``peer_hint``. Never raises on bad data."""
    projects_root = Path(projects_root) if projects_root is not None else default_projects_root()
    hint_tokens = _tokenize(peer_hint or "")
    dirs = _candidate_dirs(projects_root, caller_cwd, cross_project)
    candidates: list[Candidate] = []
    for path in _iter_session_files(dirs):
        meta = _read_meta(path)
        if meta is None:
            continue
        if caller_session_id and meta.session_id == caller_session_id:
            continue
        if meta.is_fork:
            continue
        cwd = meta.cwd
        if cwd is None:
            if path.parent.name == cwd_to_slug(caller_cwd):
                cwd = caller_cwd
            else:
                continue
        if not os.path.isdir(cwd):  # cwd-hijack guard: never steer the answerer into a bad dir
            continue
        candidates.append(
            Candidate(meta.session_id, cwd, meta.title, meta.mtime, _score(meta, hint_tokens))
        )
    ranked = sorted(candidates, key=lambda c: (-c.score, -c.mtime, c.session_id))
    return _classify(ranked, hint_tokens, top_n)
