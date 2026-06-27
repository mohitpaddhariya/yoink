import install


def test_patch_claude_md_creates_when_absent(tmp_path):
    path = tmp_path / "sub" / "CLAUDE.md"
    action = install.patch_claude_md(path)
    assert action == "created"
    text = path.read_text()
    assert install.BEGIN in text and install.END in text
    assert "ask_recorded_session" in text


def test_patch_claude_md_preserves_existing_and_is_idempotent(tmp_path):
    path = tmp_path / "CLAUDE.md"
    path.write_text("# My project\n\nSome existing rules.\n")
    install.patch_claude_md(path)
    text = path.read_text()
    assert "# My project" in text  # existing content preserved
    assert "Some existing rules." in text
    assert "ask_recorded_session" in text

    install.patch_claude_md(path)  # re-run
    assert path.read_text().count(install.BEGIN) == 1  # block not duplicated


def test_patch_claude_md_refreshes_block_in_place(tmp_path):
    path = tmp_path / "CLAUDE.md"
    path.write_text(f"# top\n\n{install.BEGIN}\nold yoink text\n{install.END}\n\n# bottom\n")
    install.patch_claude_md(path)
    text = path.read_text()
    assert text.count(install.BEGIN) == 1
    assert "old yoink text" not in text
    assert "# top" in text and "# bottom" in text  # surrounding content kept
