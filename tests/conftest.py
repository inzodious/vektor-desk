import shutil
from collections.abc import Callable
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from desk.api.app import create_app
from desk.config import Config
from desk.db import apply_schemas, desk_conn
from desk.demo import build_demo_mirror


@pytest.fixture(autouse=True)
def _roomy_box(monkeypatch):
    from desk import scheduler

    monkeypatch.setenv("DESK_LOW_MEMORY", "off")
    monkeypatch.setitem(scheduler._LOW, "on", False)
    monkeypatch.setitem(scheduler._LOW, "checked", None)


@pytest.fixture
def cfg(tmp_path) -> Config:
    return Config(data_dir=tmp_path, project="demo-project", uid="user-1", claude_token_expires="2027-11-01")


DEMO_TODAY = date(2026, 11, 6)


@pytest.fixture(scope="session")
def _demo_master(tmp_path_factory) -> Path:
    return build_demo_mirror(tmp_path_factory.mktemp("demo-master") / "mirror.db", today=DEMO_TODAY)


@pytest.fixture
def demo_cfg(cfg, _demo_master) -> Config:
    shutil.copy(_demo_master, cfg.mirror_db)
    return cfg


@pytest.fixture
def desk_db(cfg):
    apply_schemas(cfg)
    conn = desk_conn(cfg)
    yield conn
    conn.close()


@pytest.fixture
def app_client(cfg) -> Callable[..., TestClient]:
    made: list[TestClient] = []

    def make(packages: list[str] | None = None, config: Config | None = None) -> TestClient:
        client = TestClient(create_app(config or cfg, packages=packages))
        client.__enter__()
        made.append(client)
        return client

    yield make
    for client in made:
        client.__exit__(None, None, None)


@pytest.fixture
def client(app_client) -> TestClient:
    return app_client()
