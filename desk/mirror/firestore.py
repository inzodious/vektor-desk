import re
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol
from urllib.parse import quote

FIRESTORE = "https://firestore.googleapis.com/v1"
SCOPE = "https://www.googleapis.com/auth/datastore"
ROOT = "lockIn"
PAGE = 300
TABLE_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9]{0,39}$")


class MirrorError(RuntimeError):
    def __init__(self, message: str, *, status: int | None = None):
        super().__init__(message)
        self.status = status


class Session(Protocol):
    def get(self, url: str, **kwargs: Any) -> Any: ...
    def post(self, url: str, **kwargs: Any) -> Any: ...


@dataclass(frozen=True)
class Row:
    id: str
    json: str
    at: str | None


def norm_ts(value: str | None) -> str | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _row(doc: dict) -> Row | None:
    fields = doc.get("fields", {})
    raw = fields.get("json", {}).get("stringValue")
    if not isinstance(raw, str):
        return None
    return Row(id=doc["name"].rsplit("/", 1)[-1], json=raw, at=norm_ts(fields.get("at", {}).get("timestampValue")))


def service_account_session(path: str) -> Session:
    from google.auth.transport.requests import AuthorizedSession
    from google.oauth2 import service_account

    creds = service_account.Credentials.from_service_account_file(path, scopes=[SCOPE])
    return AuthorizedSession(creds)


class FirestoreReader:
    def __init__(self, project: str, uid: str, session: Session, *, timeout: float = 60.0):
        if not project:
            raise MirrorError("DESK_FIREBASE_PROJECT is not set.")
        if not uid:
            raise MirrorError("DESK_UID is not set.")
        self.project = project
        self.uid = uid
        self.session = session
        self.timeout = timeout

    @property
    def base(self) -> str:
        return f"{FIRESTORE}/projects/{quote(self.project, safe='')}/databases/(default)/documents/{ROOT}/{quote(self.uid, safe='')}"

    def _check(self, res: Any, what: str) -> dict:
        if res.status_code != 200:
            raise MirrorError(f"Firestore answered {res.status_code} {what}.", status=res.status_code)
        return res.json()

    def tables(self) -> list[str]:
        found: list[str] = []
        token = ""
        while True:
            body = {"pageSize": 100}
            if token:
                body["pageToken"] = token
            data = self._check(self.session.post(f"{self.base}:listCollectionIds", json=body, timeout=self.timeout), "listing tables")
            found.extend(t for t in data.get("collectionIds", []) if TABLE_NAME.match(t))
            token = data.get("nextPageToken", "")
            if not token:
                return sorted(set(found))

    def rows(self, table: str) -> Iterator[Row]:
        if not TABLE_NAME.match(table):
            raise MirrorError(f"Refusing odd table name {table!r}.")
        token = ""
        while True:
            params: list[tuple[str, str | int]] = [("pageSize", PAGE), ("mask.fieldPaths", "json"), ("mask.fieldPaths", "at")]
            if token:
                params.append(("pageToken", token))
            data = self._check(self.session.get(f"{self.base}/{table}", params=params, timeout=self.timeout), f"reading {table}")
            for doc in data.get("documents", []):
                row = _row(doc)
                if row is not None:
                    yield row
            token = data.get("nextPageToken", "")
            if not token:
                return

    def changed(self, table: str, since: str) -> Iterator[Row]:
        if not TABLE_NAME.match(table):
            raise MirrorError(f"Refusing odd table name {table!r}.")
        query = {
            "structuredQuery": {
                "from": [{"collectionId": table}],
                "where": {"fieldFilter": {"field": {"fieldPath": "at"}, "op": "GREATER_THAN_OR_EQUAL", "value": {"timestampValue": since}}},
                "select": {"fields": [{"fieldPath": "json"}, {"fieldPath": "at"}]},
            }
        }
        res = self.session.post(f"{self.base}:runQuery", json=query, timeout=self.timeout)
        if res.status_code != 200:
            raise MirrorError(f"Firestore answered {res.status_code} querying {table}.", status=res.status_code)
        for item in res.json():
            doc = item.get("document")
            row = _row(doc) if doc else None
            if row is not None:
                yield row
