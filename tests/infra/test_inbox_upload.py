import json

from desk import inbox_upload

CSV = b"Account,Symbol,Quantity,Acquired,Cost Basis\nX-0000,TEST,1,2024-01-02,10.00\n"
DOC = json.dumps({"synthetic": True, "rows": []}).encode()


def put(client, broker, name, body, **headers):
    return client.put(f"/api/inbox/{broker}/{name}", content=body, headers=headers)


def test_upload_stores_csv_and_json_in_the_broker_folder(client, cfg):
    res = put(client, "fidelity", "lots 2026-11-08.csv", CSV)
    assert res.status_code == 201
    body = res.json()
    assert body == {
        "ok": True,
        "broker": "fidelity",
        "name": "lots 2026-11-08.csv",
        "size": len(CSV),
        "sha256": body["sha256"],
        "duplicate": False,
        "import_job": "engine-lots",
    }
    assert (cfg.inbox / "fidelity" / "lots 2026-11-08.csv").read_bytes() == CSV
    assert put(client, "fidelity", "history.json", DOC).status_code == 201
    listed = client.get("/api/inbox").json()
    assert listed["max_bytes"] == 25 * 1024 * 1024 and listed["suffixes"] == [".json", ".csv"]
    assert [f["name"] for f in listed["brokers"]["fidelity"]["files"]] == ["history.json", "lots 2026-11-08.csv"]
    assert not [p for p in (cfg.inbox / "fidelity").iterdir() if p.name.startswith(".")]


def test_same_file_twice_is_a_duplicate_and_a_new_one_with_the_same_name_gets_a_suffix(client, cfg):
    assert put(client, "fidelity", "lots.csv", CSV).status_code == 201
    again = put(client, "fidelity", "lots.csv", CSV)
    assert again.status_code == 200 and again.json()["duplicate"] is True
    other = put(client, "fidelity", "lots.csv", CSV + b"X-0000,TEST,2,2024-01-03,20.00\n")
    assert other.status_code == 201 and other.json()["name"] == "lots-2.csv"


def test_refuses_bad_names_brokers_types_and_content(client, cfg):
    cases = [
        ("empower", "a.csv", CSV, 404, "unknown_broker"),
        ("fidelity", "a.exe", CSV, 400, "bad_name"),
        ("fidelity", ".hidden.csv", CSV, 400, "bad_name"),
        ("fidelity", "a..csv", CSV, 400, "bad_name"),
        ("fidelity", "a.json", b"{not json", 400, "bad_json"),
        ("fidelity", "a.csv", b"just words\n", 400, "bad_csv"),
        ("fidelity", "a.csv", b"\x00\x01binary", 400, "not_text"),
        ("fidelity", "a.csv", b"", 400, "empty"),
    ]
    for broker, name, body, code, error in cases:
        res = put(client, broker, name, body)
        assert (res.status_code, res.json().get("error")) == (code, error), name
    assert client.put("/api/inbox/fidelity/..%2F..%2Fdesk.db", content=CSV).status_code in (400, 404)
    assert not (cfg.inbox / "fidelity").exists() or not any((cfg.inbox / "fidelity").iterdir())
    log = [json.loads(line)["outcome"] for line in (cfg.data_dir / "run" / "inbox-uploads.log").read_text().splitlines()]
    assert log[: len(cases)] == [c[4] for c in cases]


def test_size_cap(client, cfg, monkeypatch):
    monkeypatch.setenv("DESK_INBOX_MAX_MB", "1")
    big = b"a,b\n" + b"1,2\n" * (300 * 1024)
    res = put(client, "fidelity", "big.csv", big)
    assert res.status_code == 413 and res.json()["error"] == "too_large"
    assert inbox_upload.max_bytes() == 1024 * 1024
    assert not (cfg.inbox / "fidelity" / "big.csv").exists()
