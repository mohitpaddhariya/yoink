"""The recall prompt sent to a resumed Claude session, and parsing of its reply.

yoink resumes another session's transcript read-only and asks it ONE question. The
prompt forces a recall-only posture and a small JSON contract so the reply can be
formatted with provenance. Parsing is lenient: a resumed model may wrap the JSON in
prose or code fences, so we try several extractions and, as a last resort, keep the
raw reply as a low-confidence answer rather than failing.
"""
from __future__ import annotations

import json
import re
from collections.abc import Iterator
from dataclasses import dataclass, field

CONFIDENCE = ("high", "medium", "low", "none")

_PROMPT = """\
You are being asked ONE question by a peer tool, about work YOU already did earlier in THIS session.

Rules:
- Answer ONLY from your existing conversation context. Do NOT re-investigate, do NOT run tools, do NOT read files.
- If the session explored dead ends ("tried X, ruled it out"), report the MOST RECENT RATIFIED conclusion, not the abandoned ones.
- List the ruled-out paths AS ruled out — neither hide them nor present them as the answer.
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


@dataclass
class AnswerResult:
    """A resumed session's answer, normalised into yoink's contract."""

    answer: str
    answer_confidence: str = "none"
    ruled_out: list[str] = field(default_factory=list)
    cited_turn: str = ""
    no_conclusion: bool = False


def build_recall_prompt(question: str) -> str:
    """The full recall-only prompt to hand a resumed session."""
    return _PROMPT % {"question": question.strip()}


def _json_candidates(text: str) -> Iterator[str]:
    text = text.strip()
    yield text
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fenced:
        yield fenced.group(1)
    start = text.find("{")
    while start != -1:
        depth = 0
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    yield text[start : i + 1]
                    break
        start = text.find("{", start + 1)


def _extract_obj(text: str) -> dict | None:
    for candidate in _json_candidates(text):
        try:
            obj = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            return obj
    return None


def parse_answer(result_text: str) -> AnswerResult:
    """Leniently parse a resumed session's reply into an :class:`AnswerResult`."""
    text = (result_text or "").strip()
    obj = _extract_obj(text)
    if obj is None:
        # Model ignored the contract — keep the reply, but don't trust it.
        return AnswerResult(answer=text, answer_confidence="low")

    ruled = obj.get("ruled_out") or []
    if not isinstance(ruled, list):
        ruled = [ruled]
    confidence = obj.get("answer_confidence")
    if confidence not in CONFIDENCE:
        confidence = "low"
    return AnswerResult(
        answer=str(obj.get("answer", "")).strip(),
        answer_confidence=confidence,
        ruled_out=[str(r) for r in ruled],
        cited_turn=str(obj.get("cited_turn", "")),
        no_conclusion=bool(obj.get("no_conclusion", False)),
    )
