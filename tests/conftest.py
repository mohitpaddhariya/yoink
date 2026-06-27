import pytest


@pytest.fixture
def projects_root(tmp_path):
    """A throwaway stand-in for ``~/.claude/projects``."""
    root = tmp_path / "projects"
    root.mkdir()
    return root


@pytest.fixture
def repo(tmp_path):
    """An existing project directory to use as caller_cwd / a session's cwd.

    It must exist on disk so the resolver's ``_validate_cwd`` (os.path.isdir) accepts it.
    """
    directory = tmp_path / "repo"
    directory.mkdir()
    return str(directory)
