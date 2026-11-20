import pytest

from desk.engine import kinds
from tests.engine.helpers import MirrorBuilder


@pytest.fixture(autouse=True)
def lab_work_offered_to_a_worker(monkeypatch):
    monkeypatch.setenv(kinds.TO_WORKER, "1")


@pytest.fixture
def mirror(cfg, monkeypatch):
    b = MirrorBuilder(cfg.mirror_db, monkeypatch)
    yield b
    b.close()
