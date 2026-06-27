import json

from evalkit import Fixture, build_eval_prompt, grade, load_fixtures
from prompts import AnswerResult


def _fixture(**overrides) -> Fixture:
    base = dict(
        id="x",
        scenario="s",
        question="q?",
        turns=[("user", "u"), ("assistant", "a")],
        expect={},
    )
    base.update(overrides)
    return Fixture(**base)


def test_load_fixtures_from_dir(tmp_path):
    (tmp_path / "a.json").write_text(
        json.dumps(
            {
                "id": "a",
                "question": "what?",
                "turns": [["user", "hi"], ["assistant", "bye"]],
                "expect": {"conclusion_contains": ["bye"]},
            }
        )
    )
    fixtures = load_fixtures(tmp_path)
    assert len(fixtures) == 1
    assert fixtures[0].id == "a"
    assert fixtures[0].turns == [("user", "hi"), ("assistant", "bye")]


def test_real_fixtures_load_and_are_well_formed():
    fixtures = load_fixtures()
    assert fixtures, "expected at least one committed fixture"
    for fixture in fixtures:
        assert fixture.question
        assert fixture.turns


def test_build_eval_prompt_has_transcript_and_question():
    prompt = build_eval_prompt(
        _fixture(question="why fail?", turns=[("user", "x"), ("assistant", "y")])
    )
    assert "<transcript>" in prompt
    assert "why fail?" in prompt
    assert "[assistant] y" in prompt


def test_grade_pass():
    fixture = _fixture(
        expect={
            "conclusion_contains": ["token refresh"],
            "ruled_out_contains": ["cache"],
            "answer_confidence_in": ["high"],
        }
    )
    result = AnswerResult(
        answer="it is token refresh", answer_confidence="high", ruled_out=["cache"]
    )
    passed, reasons = grade(fixture, result)
    assert passed
    assert reasons == []


def test_grade_missing_conclusion():
    fixture = _fixture(expect={"conclusion_contains": ["token refresh"]})
    passed, reasons = grade(fixture, AnswerResult(answer="it is the cache"))
    assert not passed
    assert any("conclusion" in reason for reason in reasons)


def test_grade_ruled_out_leaked_into_answer():
    fixture = _fixture(
        expect={"conclusion_contains": ["token refresh"], "ruled_out_contains": ["cache"]}
    )
    result = AnswerResult(
        answer="token refresh, though maybe cache", answer_confidence="high", ruled_out=["cache"]
    )
    passed, reasons = grade(fixture, result)
    assert not passed
    assert any("leaked" in reason for reason in reasons)


def test_grade_no_conclusion_expected():
    fixture = _fixture(expect={"no_conclusion": True})
    assert grade(fixture, AnswerResult(answer="still open", no_conclusion=True))[0]
    assert not grade(fixture, AnswerResult(answer="it is X", no_conclusion=False))[0]
