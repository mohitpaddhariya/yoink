import json

from evalkit import Fixture, build_eval_prompt, grade, load_fixtures
from yoink.prompts import RecallAnswer


def _fixture(**overrides) -> Fixture:
    base = dict(
        id="x",
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
    assert len(fixtures) >= 10, "expected the full dead-end suite"
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
    result = RecallAnswer(
        answer="it is token refresh", answer_confidence="high", ruled_out=["cache"]
    )
    assert grade(fixture, result) == (True, [])


def test_grade_missing_conclusion():
    fixture = _fixture(expect={"conclusion_contains": ["token refresh"]})
    passed, reasons = grade(fixture, RecallAnswer(answer="it is the cache"))
    assert not passed
    assert any("conclusion" in reason for reason in reasons)


def test_grade_conclusion_excludes():
    fixture = _fixture(
        expect={"conclusion_contains": ["index"], "conclusion_excludes": ["file handle"]}
    )
    result = RecallAnswer(answer="add an index; also the file handle leak", answer_confidence="high")
    passed, reasons = grade(fixture, result)
    assert not passed
    assert any("should not contain" in reason for reason in reasons)


def test_grade_naming_a_ruled_out_dead_end_is_allowed():
    # An answer may correctly *name* a dead end as ruled out — must not fail grading.
    fixture = _fixture(
        expect={"conclusion_contains": ["token refresh"], "ruled_out_contains": ["cache"]}
    )
    result = RecallAnswer(
        answer="it is token refresh (the cache was ruled out)",
        answer_confidence="high",
        ruled_out=["cache"],
    )
    assert grade(fixture, result)[0]


def test_grade_no_conclusion_expected():
    fixture = _fixture(expect={"no_conclusion": True})
    assert grade(fixture, RecallAnswer(answer="still open", no_conclusion=True))[0]
    assert not grade(fixture, RecallAnswer(answer="it is X", no_conclusion=False))[0]


def test_grade_empty_expect_fails():
    # A fixture that asserts nothing must not grade green.
    passed, _ = grade(_fixture(expect={}), RecallAnswer(answer="literally anything"))
    assert not passed


def test_grade_no_conclusion_requires_none_confidence():
    # no_conclusion=true must not ride alongside an invented confident answer.
    fixture = _fixture(expect={"no_conclusion": True})
    bad = RecallAnswer(answer="definitely the metrics leak", answer_confidence="high", no_conclusion=True)
    assert not grade(fixture, bad)[0]
