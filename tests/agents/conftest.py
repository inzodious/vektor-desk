import pytest

from desk.agents import store


@pytest.fixture(autouse=True)
def guard_lifted(cfg):
    store.set_guard(cfg, False)
    return cfg
