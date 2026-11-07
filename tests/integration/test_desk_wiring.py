import pytest

GET_ROUTES = [
    "/api/health",
    "/api/status",
    "/api/positions",
    "/api/live",
    "/api/engine/holdings",
    "/api/engine/value",
    "/api/engine/lots",
    "/api/decisions/profile",
    "/api/decisions/rules",
    "/api/decisions/deposits",
    "/api/decisions/calendar",
    "/api/decisions/queue",
    "/api/decisions/summary",
    "/api/decisions/journal",
    "/api/decisions/unmatched",
    "/api/agents/status",
    "/api/agents/brief",
    "/api/agents/runs",
    "/api/agents/console",
    "/api/agents/dossiers",
]


@pytest.fixture
def demo_client(app_client, demo_cfg):
    return app_client(config=demo_cfg)


def test_every_package_router_is_mounted(demo_client):
    paths = set(demo_client.get("/api/openapi.json").json()["paths"])
    for prefix in ("/api/engine/", "/api/decisions/", "/api/agents/"):
        assert any(p.startswith(prefix) for p in paths), prefix
    assert "/api/live" in paths


@pytest.mark.parametrize("path", GET_ROUTES)
def test_get_routes_answer_on_demo_data(demo_client, path):
    res = demo_client.get(path)
    assert res.status_code == 200, (path, res.status_code, res.text[:300])
    assert res.headers["content-type"].startswith("application/json")
    res.json()


def test_unknown_api_path_is_json_404(demo_client):
    res = demo_client.get("/api/does-not-exist")
    assert res.status_code == 404
    assert res.headers["content-type"].startswith("application/json")


def test_demo_positions_are_synthetic_and_present(demo_client):
    body = demo_client.get("/api/positions").json()
    assert body["positions"], body
    assert body["asOf"]


def test_scheduler_discovers_package_jobs():
    from desk.scheduler import package_jobs

    labels = {j.line.split(".jobs")[0] for j in package_jobs()}
    assert {"agents", "decisions", "engine"} <= labels, labels
    for job in package_jobs():
        assert job.command[:4] == ["python", "-m", "desk.runlock", "--hold"], job.command
