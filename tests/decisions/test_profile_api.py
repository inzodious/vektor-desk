def test_profile_and_rules_endpoints(cfg, app_client, monkeypatch):
    path = cfg.data_dir / "desk.yaml"
    monkeypatch.setenv("DESK_PROFILE", str(path))
    path.write_text("risk_level: 2\nrules:\n  - {id: d, kind: drift_max_pts, params: {pts: 5}}\n")
    client = app_client(packages=["decisions"])
    body = client.get("/api/decisions/profile").json()
    assert body["version"] == 1 and body["profile"]["risk_level"] == 2
    rules = client.get("/api/decisions/rules").json()
    assert rules == {"version": 1, "rules": [{"id": "d", "kind": "drift_max_pts", "params": {"pts": 5}, "enabled": True, "label": "Drift limit 5 points"}]}
    path.write_text("risk_level: 3\nrules:\n  - {id: d, kind: drift_max_pts, params: {pts: 6}}\n")
    assert [v["version"] for v in client.get("/api/decisions/profile/versions").json()["versions"]] == [2, 1]
    assert len(client.get("/api/decisions/rules/versions").json()["versions"]) == 2
    assert client.get("/api/decisions/profile/versions/1").json()["profile"]["risk_level"] == 2
    assert client.get("/api/decisions/profile/versions/99").status_code == 404
