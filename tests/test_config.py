import json

import yoink.config as config


def test_defaults_when_no_file_or_env(monkeypatch, tmp_path):
    monkeypatch.setenv("YOINK_CONFIG", str(tmp_path / "missing.json"))
    monkeypatch.delenv("YOINK_MODEL", raising=False)
    monkeypatch.delenv("YOINK_TIMEOUT", raising=False)
    cfg = config.load_config()
    assert cfg.model == config.DEFAULT_MODEL
    assert cfg.timeout == config.DEFAULT_TIMEOUT


def test_file_values_then_env_override(monkeypatch, tmp_path):
    path = tmp_path / "c.json"
    path.write_text(json.dumps({"model": "claude-sonnet-4-6", "timeout": 99}))
    monkeypatch.setenv("YOINK_CONFIG", str(path))
    monkeypatch.delenv("YOINK_MODEL", raising=False)
    monkeypatch.delenv("YOINK_TIMEOUT", raising=False)

    cfg = config.load_config()
    assert cfg.model == "claude-sonnet-4-6"
    assert cfg.timeout == 99.0

    monkeypatch.setenv("YOINK_MODEL", "claude-opus-4-8")
    assert config.load_config().model == "claude-opus-4-8"  # env wins over file


def test_corrupt_file_falls_back_to_defaults(monkeypatch, tmp_path):
    path = tmp_path / "c.json"
    path.write_text("not json {")
    monkeypatch.setenv("YOINK_CONFIG", str(path))
    monkeypatch.delenv("YOINK_MODEL", raising=False)
    assert config.load_config().model == config.DEFAULT_MODEL


def test_save_round_trips(monkeypatch, tmp_path):
    path = tmp_path / "nested" / "c.json"
    monkeypatch.setenv("YOINK_CONFIG", str(path))
    monkeypatch.delenv("YOINK_MODEL", raising=False)
    config.save_config(model="claude-sonnet-4-6")
    assert path.exists()
    assert config.load_config().model == "claude-sonnet-4-6"
