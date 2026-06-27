import json
import subprocess

import pytest

import answerer
from answerer import ErrorKind, _build_command, run_answerer, smoke_check
from prompts import RecallAnswer


class FakeProc:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


@pytest.fixture
def run_stub(monkeypatch):
    captured = {}

    def install(*, returncode=0, stdout="", stderr="", raises=None):
        def _run(cmd, **kwargs):
            captured["cmd"] = cmd
            captured["kwargs"] = kwargs
            if raises is not None:
                raise raises
            return FakeProc(returncode, stdout, stderr)

        monkeypatch.setattr(answerer.subprocess, "run", _run)
        return captured

    return install


def _envelope(result="ANSWER TEXT", session_id="forked-123", **extra):
    env = {"type": "result", "subtype": "success", "is_error": False,
           "result": result, "session_id": session_id}
    env.update(extra)
    return json.dumps(env)


def _stream(tools=None, result="OK"):
    lines = []
    system = {"type": "system"}
    if tools is not None:
        system["tools"] = tools
    lines.append(json.dumps(system))
    lines.append(json.dumps({"type": "result", "result": result}))
    return "\n".join(lines) + "\n"


# ---- _build_command -------------------------------------------------------

def test_build_command_flag_order_and_prompt_last():
    cmd = _build_command("sid123", "MY PROMPT")
    assert cmd[:2] == ["claude", "-p"]
    assert cmd[cmd.index("--resume") + 1] == "sid123"
    tools_i = cmd.index("--tools")
    assert cmd[tools_i + 1] == ""  # empty-string token
    assert cmd[tools_i + 2] == "--disallowedTools"  # terminates greedy --tools
    assert "--fork-session" in cmd and "--strict-mcp-config" in cmd
    assert cmd[cmd.index("--permission-mode") + 1] == "plan"
    assert cmd[cmd.index("--output-format") + 1] == "json"
    assert cmd[-1] == "MY PROMPT"  # prompt is the final positional


def test_build_command_omits_resume_without_session():
    assert "--resume" not in _build_command(None, "p")


def test_build_command_disallows_mcp_tools():
    cmd = _build_command("s", "p")
    assert cmd[cmd.index("--disallowedTools") + 1] == "mcp__*"
    assert "--strict-mcp-config" in cmd


def test_build_command_model_optional():
    assert "--model" not in _build_command("s", "p")
    cmd = _build_command("s", "p", model="claude-haiku-4-5")
    assert cmd[cmd.index("--model") + 1] == "claude-haiku-4-5"


# ---- run_answerer ---------------------------------------------------------

def test_run_happy_path_returns_parsed_answer(run_stub, tmp_path):
    run_stub(stdout=_envelope(result='{"answer": "it is X", "answer_confidence": "high"}'))
    res = run_answerer("s", str(tmp_path), "prompt")
    assert res.ok
    assert res.answer.answer == "it is X"
    assert res.forked_session_id == "forked-123"
    assert res.error is None


def test_run_subprocess_cwd_is_target_project_cwd(run_stub, tmp_path):
    captured = run_stub(stdout=_envelope())
    run_answerer("s", str(tmp_path), "prompt")
    assert captured["kwargs"]["cwd"] == str(tmp_path)


def test_run_cwd_not_found_never_invokes_subprocess(run_stub, tmp_path):
    captured = run_stub(stdout=_envelope())
    res = run_answerer("s", str(tmp_path / "nope"), "prompt")
    assert res.error.kind is ErrorKind.CWD_NOT_FOUND
    assert captured == {}  # subprocess never called


def test_run_binary_not_found(run_stub, tmp_path):
    run_stub(raises=FileNotFoundError("claude"))
    res = run_answerer("s", str(tmp_path), "prompt")
    assert res.error.kind is ErrorKind.BINARY_NOT_FOUND


def test_run_timeout(run_stub, tmp_path):
    run_stub(raises=subprocess.TimeoutExpired(cmd=["claude"], timeout=1))
    res = run_answerer("s", str(tmp_path), "prompt", timeout=1)
    assert res.error.kind is ErrorKind.TIMEOUT


def test_run_nonzero_exit_captures_stderr(run_stub, tmp_path):
    run_stub(returncode=1, stderr="boom happened")
    res = run_answerer("s", str(tmp_path), "prompt")
    assert res.error.kind is ErrorKind.NONZERO_EXIT
    assert res.error.returncode == 1
    assert "boom" in res.error.stderr_excerpt


def test_run_session_not_found_classified(run_stub, tmp_path):
    run_stub(returncode=1, stderr="No conversation found with session ID: abc")
    res = run_answerer("s", str(tmp_path), "prompt")
    assert res.error.kind is ErrorKind.SESSION_NOT_FOUND


def test_run_empty_stdout(run_stub, tmp_path):
    run_stub(returncode=0, stdout="   ")
    res = run_answerer("s", str(tmp_path), "prompt")
    assert res.error.kind is ErrorKind.EMPTY_OUTPUT


def test_run_malformed_json(run_stub, tmp_path):
    run_stub(returncode=0, stdout="not json {")
    res = run_answerer("s", str(tmp_path), "prompt")
    assert res.error.kind is ErrorKind.MALFORMED_JSON


def test_run_is_error_envelope(run_stub, tmp_path):
    run_stub(stdout=json.dumps({"is_error": True, "subtype": "error_during_execution", "result": None}))
    res = run_answerer("s", str(tmp_path), "prompt")
    assert res.error.kind is ErrorKind.MISSING_RESULT


def test_run_missing_result_field(run_stub, tmp_path):
    run_stub(stdout=json.dumps({"type": "result", "subtype": "success"}))
    res = run_answerer("s", str(tmp_path), "prompt")
    assert res.error.kind is ErrorKind.MISSING_RESULT


def test_run_answer_parse_failure_preserves_result_text(run_stub, tmp_path):
    run_stub(stdout=_envelope(result="raw text"))

    def boom(_):
        raise ValueError("nope")

    res = run_answerer("s", str(tmp_path), "prompt", parse_answer=boom)
    assert res.error.kind is ErrorKind.ANSWER_PARSE_FAILED
    assert res.result_text == "raw text"


def test_run_parse_answer_receives_exact_result_string(run_stub, tmp_path):
    run_stub(stdout=_envelope(result="EXACT RESULT"))
    seen = {}

    def spy(text):
        seen["text"] = text
        return RecallAnswer(answer=text, answer_confidence="low")

    run_answerer("s", str(tmp_path), "prompt", parse_answer=spy)
    assert seen["text"] == "EXACT RESULT"


# ---- smoke_check ----------------------------------------------------------

def test_smoke_success_tools_empty_and_ok(run_stub):
    run_stub(returncode=0, stdout=_stream(tools=[], result="OK"))
    res = smoke_check()
    assert res.ok and res.returned_ok and res.tools_empty


def test_smoke_detects_tools_present(run_stub):
    run_stub(returncode=0, stdout=_stream(tools=["Bash", "Read"], result="OK"))
    res = smoke_check()
    assert res.tools_empty is False
    assert res.ok is False


def test_smoke_result_not_ok(run_stub):
    run_stub(returncode=0, stdout=_stream(tools=[], result="OK, I will help with that"))
    res = smoke_check()
    assert res.returned_ok is False
    assert res.ok is False


def test_smoke_null_result_does_not_crash(run_stub):
    run_stub(returncode=0, stdout=_stream(tools=[], result=None))  # error subtype -> null result
    res = smoke_check()
    assert res.returned_ok is False
    assert res.ok is False


def test_smoke_nonzero_exit_names_flag(run_stub):
    run_stub(returncode=2, stderr="error: unknown option '--strict-mcp-config'")
    res = smoke_check()
    assert res.ok is False
    assert "--strict-mcp-config" in res.detail


def test_smoke_builds_resume_command_when_session_given(run_stub, tmp_path):
    captured = run_stub(returncode=0, stdout=_stream(tools=[], result="OK"))
    smoke_check(session_id="sess-x", target_project_cwd=str(tmp_path))
    cmd = captured["cmd"]
    assert cmd[cmd.index("--resume") + 1] == "sess-x"
    assert cmd[cmd.index("--output-format") + 1] == "stream-json"
    assert "--verbose" in cmd


def test_smoke_omits_resume_when_no_session(run_stub):
    captured = run_stub(returncode=0, stdout=_stream(tools=[], result="OK"))
    res = smoke_check(session_id=None)
    assert "--resume" not in captured["cmd"]
    assert "reduced check" in res.detail
