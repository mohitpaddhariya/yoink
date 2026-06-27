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
# v2 scoring is additive (notes' formula): title-token hits dominate, then project (cwd) hits, an
# exact-phrase bonus, a bonus for RARE hint tokens (discriminative across the candidate set), and a
# light body-token signal. Rare/phrase/project bonuses only *add*, so the simple title cases still rank.
TITLE_W = 4.0
FIRSTUSER_W = 2.0  # the first user turn is the topic anchor — weight it above generic body text
BODY_W = 1.0
PROJECT_W = 3.0
RARE_W = 4.0  # distinctive tokens disambiguate same-domain sessions (7 "redis" sessions in the pool)
PHRASE_W = 3.0
HIGH_MIN = 4.0
HIGH_MARGIN = 4.0
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
    explain: str = ""  # why it matched the hint (title/project/phrase/rare-token), for --explain-source


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
    body: str  # all user+assistant text seen in the bounded read (v2: more signal than last_text)
    first_user: str  # the first user turn — the topic anchor, weighted above generic body
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
    body_parts: list[str] = []
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
            body_parts.append(text)
            if first_user is None and kind == "user":
                first_user = text
        elif kind == "ai-title":
            ai_title = record.get("aiTitle") or ai_title
        elif kind == "custom-title":
            custom_title = record.get("customTitle") or custom_title
    body = " ".join(body_parts)
    title = (
        custom_title
        or ai_title
        or (first_user[:80] if first_user else None)
        or (body[:80] if body else None)
        or "(untitled)"
    )
    return _Meta(path.stem, mtime, cwd, title, body, first_user or "", is_fork)


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


def _project_tokens(cwd: str | None) -> set[str]:
    return _tokenize(cwd or "")


def _normalize_phrase(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", (text or "").lower())).strip()


def _score(meta: _Meta, hint_tokens: set[str], hint_phrase: str, rare_hint: set[str]) -> tuple[float, str]:
    """Additive v2 score + a short human explanation of why it matched."""
    if not hint_tokens:
        return 0.0, ""
    title_t, first_t = _tokenize(meta.title), _tokenize(meta.first_user)
    body_t, proj_t = _tokenize(meta.body), _project_tokens(meta.cwd)
    title_hits, first_hits = hint_tokens & title_t, hint_tokens & first_t
    body_hits, proj_hits = hint_tokens & body_t, hint_tokens & proj_t
    rare_hits = rare_hint & (title_t | first_t | body_t | proj_t)
    score = (TITLE_W * len(title_hits) + FIRSTUSER_W * len(first_hits) + BODY_W * len(body_hits)
             + PROJECT_W * len(proj_hits) + RARE_W * len(rare_hits))
    phrase_hit = bool(hint_phrase) and (hint_phrase in _normalize_phrase(meta.title)
                                        or hint_phrase in _normalize_phrase(meta.first_user))
    if phrase_hit:
        score += PHRASE_W
    why = []
    if title_hits:
        why.append(f"title matched {sorted(title_hits)}")
    if phrase_hit:
        why.append(f'phrase "{hint_phrase}" present')
    if proj_hits:
        why.append(f"project matched {sorted(proj_hits)}")
    if rare_hits:
        why.append(f"distinctive term {sorted(rare_hits)}")
    if (first_hits or body_hits) and not title_hits:
        why.append(f"opening turn mentioned {sorted(first_hits or body_hits)}")
    return score, "; ".join(why)


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
    hint_phrase = _normalize_phrase(peer_hint or "")
    hint_phrase = hint_phrase if len(hint_phrase.split()) >= 2 else ""  # phrase bonus needs a multi-word hint
    dirs = _candidate_dirs(projects_root, caller_cwd, cross_project)

    valid: list[tuple[_Meta, str]] = []  # pass 1: collect the resolvable candidates
    for path in _iter_session_files(dirs):
        meta = _read_meta(path)
        if meta is None or meta.is_fork:
            continue
        if caller_session_id and meta.session_id == caller_session_id:
            continue
        cwd = meta.cwd
        if cwd is None:
            cwd = caller_cwd if path.parent.name == cwd_to_slug(caller_cwd) else None
        if cwd is None or not os.path.isdir(cwd):  # cwd-hijack guard: never steer into a bad dir
            continue
        valid.append((meta, cwd))

    # rare-token weighting: a hint token is discriminative if it appears in FEW candidate sessions
    df: dict[str, int] = {}
    for meta, _cwd in valid:
        for token in _tokenize(meta.title) | _tokenize(meta.body) | _project_tokens(meta.cwd):
            df[token] = df.get(token, 0) + 1
    rare_threshold = max(1, len(valid) // 5)
    rare_hint = {t for t in hint_tokens if 0 < df.get(t, 0) <= rare_threshold}

    candidates: list[Candidate] = []  # pass 2: score with title/project/phrase/rare bonuses
    for meta, cwd in valid:
        score, why = _score(meta, hint_tokens, hint_phrase, rare_hint)
        candidates.append(Candidate(meta.session_id, cwd, meta.title, meta.mtime, score, why))
    ranked = sorted(candidates, key=lambda c: (-c.score, -c.mtime, c.session_id))
    return _classify(ranked, hint_tokens, top_n)
