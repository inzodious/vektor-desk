import pytest

from tests.engine.helpers import MirrorBuilder


@pytest.fixture
def mirror(cfg, monkeypatch):
    b = MirrorBuilder(cfg.mirror_db, monkeypatch)
    yield b
    b.close()
