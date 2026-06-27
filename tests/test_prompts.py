from prompts import build_recall_prompt, parse_answer


def test_prompt_includes_question_and_recall_only_instruction():
    prompt = build_recall_prompt("  what broke auth?  ")
    assert "what broke auth?" in prompt
    assert "do not re-investigate" in prompt.lower()


def test_parse_clean_json():
    result = parse_answer(
        '{"answer": "token refresh", "answer_confidence": "high",'
        ' "ruled_out": ["cache"], "cited_turn": "t3", "no_conclusion": false}'
    )
    assert result.answer == "token refresh"
    assert result.answer_confidence == "high"
    assert result.ruled_out == ["cache"]
    assert result.cited_turn == "t3"
    assert result.no_conclusion is False


def test_parse_json_wrapped_in_prose_and_fences():
    raw = 'Sure!\n```json\n{"answer": "it is X", "answer_confidence": "medium"}\n```\nhope that helps'
    result = parse_answer(raw)
    assert result.answer == "it is X"
    assert result.answer_confidence == "medium"
    assert result.cited_turn is None


def test_parse_python_dict_single_quotes():
    result = parse_answer("{'answer': 'it is Y', 'answer_confidence': 'high'}")
    assert result.answer == "it is Y"
    assert result.answer_confidence == "high"


def test_parse_no_json_falls_back_to_low_confidence():
    result = parse_answer("I think it was probably the cache layer.")
    assert result.answer.startswith("I think")
    assert result.answer_confidence == "low"
    assert result.no_conclusion is False


def test_parse_confidence_synonym_and_case():
    assert parse_answer('{"answer": "x", "answer_confidence": "Likely"}').answer_confidence == "medium"
    assert parse_answer('{"answer": "x", "answer_confidence": "very-sure"}').answer_confidence == "low"


def test_parse_ruled_out_non_list_coerced():
    result = parse_answer('{"answer": "x", "ruled_out": "cache"}')
    assert result.ruled_out == ["cache"]


def test_parse_no_conclusion_implies_none_confidence():
    result = parse_answer('{"answer": "still open", "answer_confidence": "high", "no_conclusion": true}')
    assert result.no_conclusion is True
    assert result.answer_confidence == "none"


def test_parse_none_confidence_implies_no_conclusion():
    result = parse_answer('{"answer": "x", "answer_confidence": "none"}')
    assert result.no_conclusion is True


def test_parse_blank_answer_forces_no_conclusion():
    result = parse_answer('{"answer": "   ", "answer_confidence": "high"}')
    assert result.answer == ""
    assert result.no_conclusion is True
    assert result.answer_confidence == "none"


def test_parse_empty_reply():
    result = parse_answer("")
    assert result.answer == ""
    assert result.answer_confidence == "none"
    assert result.no_conclusion is True
