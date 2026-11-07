import json

from desk.mirror.firestore import norm_ts


class Res:
    def __init__(self, status, body):
        self.status_code = status
        self._body = body

    def json(self):
        return self._body


def doc(table, rid, row, at="2026-11-07T13:00:00Z"):
    return {
        "name": f"projects/demo-project/databases/(default)/documents/lockIn/user-1/{table}/{rid}",
        "fields": {"json": {"stringValue": json.dumps(row)}, "at": {"timestampValue": at}},
    }


class FakeFirestore:
    def __init__(self, tables, *, page=2, list_status=200):
        self.tables = tables
        self.page = page
        self.list_status = list_status
        self.calls = []

    def post(self, url, json=None, timeout=None):
        self.calls.append(("POST", url))
        if url.endswith(":runQuery"):
            q = json["structuredQuery"]
            since = q["where"]["fieldFilter"]["value"]["timestampValue"]
            docs = self.tables.get(q["from"][0]["collectionId"], [])
            hits = [{"document": d, "readTime": "x"} for d in docs if norm_ts(d["fields"]["at"]["timestampValue"]) >= since]
            return Res(200, hits or [{"readTime": "x"}])
        if self.list_status != 200:
            return Res(self.list_status, {})
        return Res(200, {"collectionIds": list(self.tables)})

    def get(self, url, params=None, timeout=None):
        self.calls.append(("GET", url))
        table = url.rsplit("/", 1)[-1]
        docs = self.tables.get(table, [])
        token = dict(p for p in params if p[0] == "pageToken").get("pageToken")
        start = int(token or 0)
        chunk = docs[start : start + self.page]
        body = {"documents": chunk} if chunk else {}
        if start + self.page < len(docs):
            body["nextPageToken"] = str(start + self.page)
        return Res(200, body)
