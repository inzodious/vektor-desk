import pytest

from desk.config import Config


@pytest.fixture
def cfg(tmp_path):
    return Config(data_dir=tmp_path, project="demo-project", uid="user-1", claude_token_expires="2027-11-01")
