"""Load dead-end fixtures, build eval prompts, and grade model answers.

The dead-end suite is yoink's make-or-break gate: can the recall prompt pull the
*current ratified* conclusion out of a messy transcript without surfacing abandoned
dead ends? Grading here is deterministic and offline; the real model call lives in
``run_eval.py`` so the unit suite stays fast.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from yoink.prompts import RecallAnswer, build_recall_prompt

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@dataclass
class Fixture:
    id: str
    question: str
    turns: list[tuple[str, str]]
    expect: dict
    category: str | None = None  # one of the 7 benchmark categories; None for legacy fixtures
    session_hint: str | None = None  # fuzzy hint for the session_resolution category


_LIST_EXPECT_KEYS = ("conclusion_contains", "conclusion_excludes", "ruled_out_contains", "answer_confidence_in")


def _coerce_expect(expect: dict) -> dict:
    # A bare string where a list is expected ("bloat" vs ["bloat"]) would iterate char-by-char
    # in grade() and silently always-fail — coerce it to a one-element list at the boundary.
    for key in _LIST_EXPECT_KEYS:
        if isinstance(expect.get(key), str):
            expect[key] = [expect[key]]
    return expect


def load_fixtures(directory: Path = FIXTURES_DIR) -> list[Fixture]:
    """Load every ``*.json`` fixture from ``directory``, sorted by filename."""
    fixtures = []
    for path in sorted(directory.glob("*.json")):
        data = json.loads(path.read_text())
        fixtures.append(
            Fixture(
                id=data.get("id", path.stem),
                question=data["question"],
                turns=[tuple(turn) for turn in data["turns"]],
                expect=_coerce_expect(data.get("expect", {})),
                category=data.get("category"),
                session_hint=data.get("session_hint"),
            )
        )
    return fixtures


def build_eval_prompt(fixture: Fixture) -> str:
    """Inline the synthetic transcript as context, then ask the recall question.

    In production the transcript is the resumed session's own context (via
    ``--resume``); here we inline it so the eval exercises the prompt's dead-end
    discrimination without needing a real session on disk.
    """
    transcript = "\n".join(f"[{role}] {text}" for role, text in fixture.turns)
    return (
        "Below is a transcript of an earlier debugging session you ran. Treat it as"
        " your own prior context.\n\n<transcript>\n"
        + transcript
        + "\n</transcript>\n\n"
        + build_recall_prompt(fixture.question)
    )


_RECOGNIZED_EXPECT_KEYS = frozenset(
    {"no_conclusion", "conclusion_contains", "conclusion_excludes", "ruled_out_contains", "answer_confidence_in"}
)


def grade(fixture: Fixture, result: RecallAnswer) -> tuple[bool, list[str]]:
    """Grade a parsed answer against the fixture's expectations.

    Returns ``(passed, reasons)`` where ``reasons`` lists every failed expectation. A
    fixture with no recognized expectation keys fails loudly — silence must never grade
    green, or a typo'd/empty expectation would assert nothing.
    """
    expect = fixture.expect
    if not _RECOGNIZED_EXPECT_KEYS & set(expect):
        return (False, ["fixture has no recognized expectations"])

    answer = result.answer.lower()
    reasons: list[str] = []

    # The anti-leak set always applies — even on the no_conclusion path, a result must
    # never surface a curated forbidden conclusion.
    for keyword in expect.get("conclusion_excludes", []):
        if keyword.lower() in answer:
            reasons.append(f"answer should not contain: {keyword!r}")

    if "no_conclusion" in expect:
        if bool(expect["no_conclusion"]) != result.no_conclusion:
            reasons.append(f"expected no_conclusion={bool(expect['no_conclusion'])}, got {result.no_conclusion}")
        if expect["no_conclusion"]:
            # Safe-failure gate: must be flagged none-confidence (never an invented
            # confident conclusion).
            if result.answer_confidence != "none":
                reasons.append("no_conclusion result must have answer_confidence 'none'")
            return (not reasons, reasons)

    for keyword in expect.get("conclusion_contains", []):
        if keyword.lower() not in answer:
            reasons.append(f"answer missing conclusion keyword: {keyword!r}")

    ruled_blob = " ".join(result.ruled_out).lower()
    for keyword in expect.get("ruled_out_contains", []):
        if keyword.lower() not in ruled_blob:
            reasons.append(f"ruled_out missing: {keyword!r}")

    allowed = expect.get("answer_confidence_in")
    if allowed and result.answer_confidence not in allowed:
        reasons.append(f"answer_confidence {result.answer_confidence!r} not in {allowed}")
    return (not reasons, reasons)
