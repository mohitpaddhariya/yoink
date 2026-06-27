"""The recall prompt sent to a resumed Claude session, and parsing of its reply.

yoink resumes another session's transcript read-only and asks it ONE question. The
prompt forces a recall-only posture and a small JSON contract so the reply can be
formatted with provenance. Parsing is lenient and *total* (never raises): a resumed
model may wrap the JSON in prose or fences, use Python-style quotes, or ignore the
contract entirely; we extract what we can and otherwise keep the raw reply as a
low-confidence answer.
"""
from __future__ import annotations

import ast
import json
from collections.abc import Iterator
from dataclasses import dataclass, field

CONFIDENCE_LEVELS: tuple[str, ...] = ("high", "medium", "low", "none")

_SYNONYMS = {
    "confident": "high", "certain": "high", "sure": "high",
    "likely": "medium", "probable": "medium",
    "possible": "low", "tentative": "low", "unsure": "low", "uncertain": "low",
    "unknown": "none", "unclear": "none",
}

_PROMPT = """\
You are being asked ONE question by a peer tool, about work YOU already did earlier in THIS session.

Rules:
- Answer ONLY from your existing conversation context. Do NOT re-investigate, do NOT run tools, do NOT read files.
- If the session explored dead ends ("tried X, ruled it out"), report the MOST RECENT RATIFIED conclusion, not the abandoned ones.
- List the ruled-out paths AS ruled out -- neither hide them nor present them as the answer.
- If the session never reached a firm conclusion, set no_conclusion=true and do NOT invent one.

Reply with ONLY a JSON object of this shape, nothing else:
{
  "answer": "the current conclusion, or a short summary of what is still open",
  "answer_confidence": "high | medium | low | none",
  "ruled_out": ["dead end", "..."],
  "cited_turn": "a timestamp or short quote marking where the conclusion was settled",
  "no_conclusion": false
}

Question: %(question)s
"""


@dataclass(frozen=True)
class RecallAnswer:
    """A resumed session's answer, normalised into yoink's contract.

    Invariants (always hold after :func:`parse_answer`): ``no_conclusion`` iff
    ``answer_confidence == "none"``; a blank answer forces both.
    """

    answer: str
    answer_confidence: str = "none"
    ruled_out: list[str] = field(default_factory=list)
    cited_turn: str | None = None
    no_conclusion: bool = False


def build_recall_prompt(question: str) -> str:
    """The full recall-only prompt to hand a resumed session."""
    return _PROMPT % {"question": question.strip()}


def _normalize_confidence(value: object) -> str:
    text = str(value).strip().lower()
    if text in CONFIDENCE_LEVELS:
        return text
    return _SYNONYMS.get(text, "low")


_CONTRACT_KEYS = ("answer", "answer_confidence", "no_conclusion", "ruled_out")


def _json_candidates(text: str) -> Iterator[str]:
    yield text
    start = text.find("{")
    while start != -1:
        depth = 0
        in_string = False
        escaped = False
        for i in range(start, len(text)):
            ch = text[i]
            if in_string:
                if escaped:
                    escaped = False
                elif ch == "\\":
                    escaped = True
                elif ch == '"':
                    in_string = False
            elif ch == '"':
                in_string = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    yield text[start : i + 1]
                    break
        start = text.find("{", start + 1)


def _extract_obj(text: str) -> dict | None:
    # Prefer a dict that looks like our contract over a leading JSON-shaped aside.
    fallback = None
    for candidate in _json_candidates(text):
        for loader in (json.loads, ast.literal_eval):
            try:
                obj = loader(candidate)
            except (ValueError, SyntaxError):
                continue
            if isinstance(obj, dict):
                if any(key in obj for key in _CONTRACT_KEYS):
                    return obj
                if fallback is None:
                    fallback = obj
    return fallback


def _reconcile(
    answer: str,
    confidence: str,
    ruled_out: list[str],
    cited_turn: str | None,
    no_conclusion: bool,
) -> RecallAnswer:
    answer = answer.strip()
    confidence = _normalize_confidence(confidence)
    if not answer:
        no_conclusion = True
    if no_conclusion:
        confidence = "none"
    elif confidence == "none":
        no_conclusion = True
    return RecallAnswer(answer, confidence, ruled_out, cited_turn or None, no_conclusion)


def _as_bool(value: object) -> bool:
    # A model may send the JSON string "false" — bool("false") is True, so coerce strings.
    if isinstance(value, str):
        return value.strip().lower() in ("true", "yes", "1")
    return bool(value)


def parse_answer(result_text: str) -> RecallAnswer:
    """Leniently and totally parse a resumed session's reply (never raises)."""
    text = (result_text or "").strip()
    obj = _extract_obj(text)
    if obj is None:
        # Model ignored the contract -- keep the reply, but don't trust it.
        return _reconcile(text, "low", [], None, False)

    ruled = obj.get("ruled_out") or []
    if not isinstance(ruled, list):
        ruled = [ruled]
    raw_answer = obj.get("answer")
    cited = obj.get("cited_turn")
    return _reconcile(
        "" if raw_answer is None else str(raw_answer),  # explicit null -> "", not "None"
        obj.get("answer_confidence") or "none",
        [str(r) for r in ruled],
        str(cited) if cited else None,
        _as_bool(obj.get("no_conclusion", False)),
    )
