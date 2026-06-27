import pytest


@pytest.fixture
def projects_root(tmp_path):
    """A throwaway stand-in for ``~/.claude/projects``."""
    root = tmp_path / "projects"
    root.mkdir()
    return root
