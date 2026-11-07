from desk.decisions import create_proposal


def test_queue_flow_over_http(cfg, app_client, preflight, mirror, proposal):
    client = app_client(packages=["decisions"])
    preflight["result"]["value"] = {"status": "blocked", "lights": [{"check": "Funding", "status": "act"}]}
    d = create_proposal(cfg, proposal(funding="margin", order_ticket={"action": "buy", "symbol": "ABCD", "limit": 49.5}), "research")
    q = client.get("/api/decisions/queue").json()
    assert q["count"] == 1 and q["items"][0]["id"] == d["id"]
    r = client.post(f"/api/decisions/{d['id']}/approve", json={})
    assert r.status_code == 422 and "reason" in r.json()["detail"]
    r = client.post(f"/api/decisions/{d['id']}/approve", json={"reason": "Small and paid off Friday"})
    assert r.status_code == 200 and r.json()["decision"] == "override"
    t = client.get(f"/api/decisions/{d['id']}/ticket").json()
    assert t["stamp"] == "READY"
    assert t["text"] == "Account: Brokerage\nAction: Buy\nSymbol: ABCD\nQuantity: $500.00\nOrder type: Limit\nLimit price: $49.50\nTime in force: Day"
    assert client.post(f"/api/decisions/{d['id']}/placed", json={"shares": 10}).json()["status"] == "placed"
    assert client.post(f"/api/decisions/{d['id']}/note", json={"text": "Placed at the open"}).json()["events"][-1]["event"] == "note"
    assert client.post(f"/api/decisions/{d['id']}/dismiss", json={}).status_code == 409
    assert client.get("/api/decisions/nope").status_code == 404


def test_draft_snooze_pass_and_summary_over_http(cfg, app_client, preflight, mirror):
    client = app_client(packages=["decisions"])
    r = client.post("/api/decisions", json={"kind": "sell", "symbol": "abcd", "shares": 3, "account": "Brokerage"})
    assert r.status_code == 422
    r = client.post("/api/decisions", json={"kind": "sell", "symbol": "abcd", "shares": 3, "account": "Brokerage", "thesis": "Trim back to band"})
    d = r.json()
    assert d["origin"] == "you" and d["symbol"] == "ABCD" and d["title"] == "Sell 3 shares ABCD"
    t = client.get(f"/api/decisions/{d['id']}/ticket").json()
    assert t["stamp"] == "DRAFT" and {"label": "Lots", "value": "Specific shares: highest cost first"} in t["fields"]
    assert client.post(f"/api/decisions/{d['id']}/snooze", json={"days": 2}).json()["status"] == "snoozed"
    assert client.get("/api/decisions/queue").json()["snoozed"] == 1
    assert client.post(f"/api/decisions/{d['id']}/pass", json={}).status_code == 422
    assert client.post(f"/api/decisions/{d['id']}/pass", json={"reason": "Inside the band after all"}).json()["status"] == "passed"
    assert client.post(f"/api/decisions/{d['id']}/preflight").status_code == 409
    mirror("t9", date="2026-11-05", accountKey="brokerage-9", kind="buy", symbol="ABCD", quantity=1, amount=-50)
    assert [t["activity_id"] for t in client.get("/api/decisions/unmatched?days=3650").json()["trades"]] == ["t9"]
    logged = client.post("/api/decisions/unmatched/t9/log", json={"reason": "Bought on the phone"}).json()
    assert logged["status"] == "filled"
    s = client.get("/api/decisions/summary").json()
    assert s["unmatched"] == 0 and s["waiting"] == 0
    j = client.get("/api/decisions/journal?origin=you").json()
    assert {i["id"] for day in j["days"] for i in day["items"]} >= {d["id"], logged["id"]}


def test_rerun_preflight_over_http(cfg, app_client, monkeypatch, proposal):
    from desk.decisions import records

    monkeypatch.setattr(records, "_checker", lambda: None)
    client = app_client(packages=["decisions"])
    d = create_proposal(cfg, proposal(), "plan_keeper")
    assert d["preflight_status"] == "pending"
    monkeypatch.setattr(records, "_checker", lambda: lambda c, t, ticket_id: {"status": "flagged", "lights": []})
    assert client.post(f"/api/decisions/{d['id']}/preflight").json()["preflight_status"] == "flagged"
