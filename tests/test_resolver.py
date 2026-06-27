from pathlib import Path

from helpers import write_transcript
from resolver import cwd_to_slug, default_projects_root, resolve


def _resolve(hint, projects_root, repo, caller_session_id=None, **kw):
    return resolve(hint, caller_session_id, repo, projects_root=projects_root, **kw)


def test_cwd_to_slug_replaces_slash_and_dot():
    assert cwd_to_slug("/Users/m/code.example") == "-Users-m-code-example"


def test_excludes_caller_session(projects_root, repo):
    write_transcript(projects_root, "me", repo, titles=[("ai", "auth login bug")])
    write_transcript(projects_root, "other", repo, titles=[("ai", "auth login bug")])
    res = _resolve("auth login", projects_root, repo, caller_session_id="me")
    ids = {c.session_id for c in res.candidates}
    assert "me" not in ids and "other" in ids


def test_caller_session_none_excludes_nothing(projects_root, repo):
    write_transcript(projects_root, "lonely", repo, titles=[("ai", "auth login bug")])
    res = _resolve("auth login", projects_root, repo, caller_session_id=None)
    assert [c.session_id for c in res.candidates] == ["lonely"]


def test_fork_transcripts_excluded(projects_root, repo):
    write_transcript(
        projects_root, "fork", repo,
        turns=[("user", "You are being asked ONE question by a peer tool, about X")],
        titles=[("ai", "auth login bug")],
    )
    write_transcript(projects_root, "real", repo, titles=[("ai", "auth login bug")])
    res = _resolve("auth login", projects_root, repo)
    assert "fork" not in {c.session_id for c in res.candidates}


def test_high_source_match_clear_winner(projects_root, repo):
    write_transcript(projects_root, "auth", repo, titles=[("ai", "auth login failures")])
    write_transcript(projects_root, "cache", repo, titles=[("ai", "cache metrics dashboard")])
    res = _resolve("auth login", projects_root, repo)
    assert res.source_match == "high"
    assert [c.session_id for c in res.candidates] == ["auth"]


def test_medium_source_match_close_runner_up(projects_root, repo):
    write_transcript(projects_root, "a", repo, titles=[("ai", "auth token rotation")])
    write_transcript(projects_root, "b", repo, titles=[("ai", "auth token retry")])
    res = _resolve("auth token", projects_root, repo)
    assert res.source_match == "medium"
    assert len(res.candidates) == 1


def test_low_blank_hint_returns_top_by_recency(projects_root, repo):
    write_transcript(projects_root, "old", repo, titles=[("ai", "x")], mtime=100)
    write_transcript(projects_root, "new", repo, titles=[("ai", "y")], mtime=200)
    res = _resolve("", projects_root, repo)
    assert res.source_match == "low"
    assert [c.session_id for c in res.candidates][:2] == ["new", "old"]


def test_topic_match_outranks_recency(projects_root, repo):
    write_transcript(projects_root, "match", repo, titles=[("ai", "auth login bug")], mtime=100)
    write_transcript(projects_root, "recent", repo, titles=[("ai", "unrelated refactor")], mtime=999)
    res = _resolve("auth login", projects_root, repo)
    assert res.candidates[0].session_id == "match"


def test_recency_breaks_ties_on_equal_topic(projects_root, repo):
    write_transcript(projects_root, "older", repo, titles=[("ai", "auth login")], mtime=100)
    write_transcript(projects_root, "newer", repo, titles=[("ai", "auth login")], mtime=200)
    res = _resolve("auth login", projects_root, repo)
    assert res.candidates[0].session_id == "newer"


def test_stopwords_do_not_dominate_match(projects_root, repo):
    write_transcript(projects_root, "auth", repo, titles=[("ai", "auth login")])
    write_transcript(projects_root, "cache", repo, titles=[("ai", "cache layer")])
    res = _resolve("the auth session", projects_root, repo)
    assert res.candidates[0].session_id == "auth"
    assert res.source_match == "high"


def test_no_candidates_returns_low_empty(projects_root, repo):
    res = _resolve("anything", projects_root, repo)
    assert res.source_match == "low"
    assert res.candidates == []


def test_only_self_session_returns_empty(projects_root, repo):
    write_transcript(projects_root, "me", repo, titles=[("ai", "auth login")])
    res = _resolve("auth login", projects_root, repo, caller_session_id="me")
    assert res.candidates == []


def test_missing_projects_root_returns_low_empty(tmp_path, repo):
    res = resolve("auth", None, repo, projects_root=tmp_path / "nope")
    assert res.source_match == "low"
    assert res.candidates == []


def test_target_project_cwd_read_from_transcript(projects_root, repo):
    write_transcript(
        projects_root, "a", repo,
        turns=[("user", "hi"), ("assistant", "done")],
        titles=[("ai", "auth login")],
    )
    res = _resolve("auth login", projects_root, repo)
    assert res.candidates[0].target_project_cwd == repo


def test_invalid_cwd_candidate_dropped(projects_root, repo, tmp_path):
    missing = str(tmp_path / "gone")  # never created -> os.path.isdir False
    # turns carry the cwd, so "bad" reaches _validate_cwd and is dropped there.
    write_transcript(projects_root, "bad", missing, turns=[("user", "work")], titles=[("ai", "auth login bug")])
    write_transcript(projects_root, "good", repo, turns=[("user", "work")], titles=[("ai", "auth login bug")])
    res = _resolve("auth login", projects_root, repo, cross_project=True)
    ids = {c.session_id for c in res.candidates}
    assert "bad" not in ids and "good" in ids


def test_custom_title_preferred_over_ai_title(projects_root, repo):
    write_transcript(
        projects_root, "a", repo,
        titles=[("ai", "ai generated name"), ("custom", "my custom name")],
    )
    res = _resolve("", projects_root, repo)
    assert res.candidates[0].title == "my custom name"


def test_latest_ai_title_line_wins(projects_root, repo):
    write_transcript(projects_root, "a", repo, titles=[("ai", "first title"), ("ai", "second title")])
    res = _resolve("", projects_root, repo)
    assert res.candidates[0].title == "second title"


def test_missing_title_falls_back_to_first_user(projects_root, repo):
    write_transcript(
        projects_root, "a", repo,
        turns=[("user", "investigate the auth regression"), ("assistant", "ok")],
    )
    res = _resolve("", projects_root, repo)
    assert "investigate" in res.candidates[0].title


def test_corrupt_line_skipped(projects_root, repo):
    path = write_transcript(
        projects_root, "a", repo,
        turns=[("assistant", "token refresh is the cause")],
        titles=[("ai", "auth login bug")],
    )
    with path.open("a") as handle:
        handle.write("this is not json\n")
    res = _resolve("auth login", projects_root, repo)
    assert res.candidates[0].session_id == "a"


def test_empty_file_skipped(projects_root, repo):
    slug_dir = projects_root / cwd_to_slug(repo)
    slug_dir.mkdir(parents=True, exist_ok=True)
    (slug_dir / "empty.jsonl").write_text("")
    write_transcript(projects_root, "real", repo, titles=[("ai", "auth login")])
    res = _resolve("auth login", projects_root, repo)
    ids = {c.session_id for c in res.candidates}
    assert "empty" not in ids and "real" in ids


def test_cross_project_default_deny_then_optin(projects_root, repo, tmp_path):
    other = str(tmp_path / "other")
    Path(other).mkdir()
    # turns carry the cwd; a foreign-slug session needs a recorded cwd to be resumable.
    write_transcript(projects_root, "here", repo, turns=[("user", "work")], titles=[("ai", "random refactor")])
    write_transcript(projects_root, "there", other, turns=[("user", "work")], titles=[("ai", "auth token bug")])
    default = _resolve("auth token", projects_root, repo)
    assert "there" not in {c.session_id for c in default.candidates}
    optin = _resolve("auth token", projects_root, repo, cross_project=True)
    assert optin.candidates[0].session_id == "there"


def test_default_projects_root_respects_config_dir(monkeypatch):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", "/tmp/cfg")
    assert default_projects_root() == Path("/tmp/cfg/projects")
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    assert default_projects_root().as_posix().endswith("/.claude/projects")


def test_huge_file_bounded_read_finds_tail_title(projects_root, repo):
    import json

    import resolver as R

    slug_dir = projects_root / cwd_to_slug(repo)
    slug_dir.mkdir(parents=True, exist_ok=True)
    path = slug_dir / "big.jsonl"

    lines = [json.dumps({"type": "user", "cwd": repo, "sessionId": "big",
                         "message": {"role": "user", "content": [{"type": "text", "text": "start"}]}})]
    pad = json.dumps({"type": "user", "cwd": repo,
                      "message": {"role": "user", "content": [{"type": "text", "text": "x" * 300}]}})
    while sum(len(line) + 1 for line in lines) < R.HEAD_BYTES + R.TAIL_BYTES + 5000:
        lines.append(pad)
    lines.append(json.dumps({"type": "ai-title", "aiTitle": "deep tail auth title", "sessionId": "big"}))
    path.write_text("\n".join(lines) + "\n")
    assert path.stat().st_size > R.HEAD_BYTES + R.TAIL_BYTES  # genuinely exceeds the bounded window

    res = resolve("deep tail auth", None, repo, projects_root=projects_root)
    assert res.candidates and res.candidates[0].session_id == "big"
    assert "deep tail" in res.candidates[0].title  # title recovered from the tail read
