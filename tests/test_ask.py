import yoink.cli as ask
import yoink.server as broker


def test_ask_cli_invokes_recall_and_prints(monkeypatch, capsys):
    captured = {}

    def fake_recall(hint, question, *, caller_cwd, caller_session_id, cross_project):
        captured.update(hint=hint, question=question, cwd=caller_cwd, cross=cross_project)
        return "RECALLED OUTPUT"

    monkeypatch.setattr(broker, "recall", fake_recall)
    rc = ask.main(["the auth one", "what did it conclude?", "--cwd", "/tmp/x", "--all"])

    assert rc == 0
    assert "RECALLED OUTPUT" in capsys.readouterr().out
    assert captured["hint"] == "the auth one"
    assert captured["question"] == "what did it conclude?"
    assert captured["cwd"] == "/tmp/x"
    assert captured["cross"] is True
