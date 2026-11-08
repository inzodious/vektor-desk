import base64
import json
import os
import re
import secrets
from dataclasses import dataclass
from datetime import datetime

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from desk.boxrun import box_dir, host_alive, log_request
from desk.config import Config
from desk.jobrun import _read, now_utc, stamp
from desk.paper_check import NotPaper, paper_base

NAME = re.compile(r"^[A-Z_][A-Z0-9_]{0,63}$")
DENIED = re.compile(r"^(PATH|HOME|USER|SHELL|ENV|BASH_ENV|NODE_OPTIONS|LD_.*|PYTHON.*|DESK_DATA_DIR)$")
MAX_VALUE = 1024
MAX_BODY = 8192


@dataclass(frozen=True)
class Key:
    name: str
    file: str
    secret: bool
    what: str


KNOWN = {
    k.name: k
    for k in (
        Key("CLAUDE_CODE_OAUTH_TOKEN", "desk.env", True, "Claude token from claude setup-token on your PC"),
        Key("DESK_CLAUDE_TOKEN_EXPIRES", "settings.env", False, "When that token expires, YYYY-MM-DD"),
        Key("TIINGO_API_KEY", "desk.env", True, "Tiingo prices"),
        Key("FINNHUB_API_KEY", "desk.env", True, "Finnhub news and earnings"),
        Key("FRED_API_KEY", "desk.env", True, "FRED rates and macro series"),
        Key("DESK_SEC_USER_AGENT", "desk.env", False, "SEC contact for its User-Agent, e.g. 'Vektor Desk you@example.com'"),
        Key("ALPACA_API_KEY_ID", "desk.env", True, "Alpaca PAPER key ID (starts with PK); live keys are refused"),
        Key("ALPACA_API_SECRET_KEY", "desk.env", True, "Alpaca PAPER secret key"),
        Key("DESK_FIREBASE_PROJECT", "settings.env", False, "Escape Vektor's Firebase project ID"),
        Key("DESK_UID", "settings.env", False, "Your Escape Vektor user ID"),
        Key("PORKBUN_API_KEY", "caddy.env", True, "Porkbun API key, for the certificate"),
        Key("PORKBUN_API_SECRET_KEY", "caddy.env", True, "Porkbun secret API key"),
        Key("TS_AUTHKEY", "tailscale.env", True, "Tailscale auth key, only for a fresh sign-in"),
    )
}


class Refused(Exception):
    def __init__(self, code: int, error: str, message: str):
        super().__init__(message)
        self.code, self.error, self.message = code, error, message


# ---- Files ----


def keys_dir(cfg: Config):
    return box_dir(cfg) / "keys"


def present(cfg: Config) -> dict[str, str]:
    state = _read(box_dir(cfg) / "keys.json") or {}
    return {
        r["name"]: r["file"] for r in state.get("present") or [] if isinstance(r, dict) and isinstance(r.get("name"), str) and isinstance(r.get("file"), str)
    }


def public_key(cfg: Config) -> rsa.RSAPublicKey | None:
    try:
        key = serialization.load_pem_public_key((box_dir(cfg) / "keys.pub").read_bytes())
    except (OSError, ValueError):
        return None
    return key if isinstance(key, rsa.RSAPublicKey) and key.key_size >= 3072 else None


def seal(key: rsa.RSAPublicKey, value: str) -> str:
    oaep = padding.OAEP(mgf=padding.MGF1(algorithm=hashes.SHA256()), algorithm=hashes.SHA256(), label=None)
    return base64.b64encode(key.encrypt(value.encode(), oaep)).decode()


# ---- Rules ----


def refusal(name: str, value: str, known: dict[str, str]) -> str | None:
    if not NAME.match(name):
        return "isn't a key name"
    if DENIED.match(name):
        return "can't be set from the app"
    if name not in KNOWN and name not in known:
        return "isn't one of the desk's keys"
    if not value:
        return "is empty"
    if len(value) > MAX_VALUE:
        return f"is longer than {MAX_VALUE} characters"
    if any(c in value for c in "\n\r'\x00"):
        return "can't contain a line break or a single quote"
    if name == "ALPACA_API_KEY_ID" and not value.startswith("PK"):
        return "isn't a paper key ID (paper key IDs start with PK); live keys are never allowed"
    if "ALPACA" in name and "URL" in name:
        try:
            paper_base(value)
        except NotPaper:
            return "isn't Alpaca's paper API; only paper trading is allowed"
    return None


# ---- State ----


def describe(cfg: Config, now: datetime | None = None) -> dict:
    now = now or now_utc()
    have = present(cfg)
    folder = keys_dir(cfg)
    rows = []
    for name in list(KNOWN) + sorted(set(have) - set(KNOWN)):
        k = KNOWN.get(name)
        rows.append(
            {
                "name": name,
                "file": have.get(name) or (k.file if k else None),
                "secret": k.secret if k else any(w in name for w in ("TOKEN", "KEY", "SECRET", "PASSWORD")),
                "what": k.what if k else None,
                "set": name in have,
                "pending": (folder / f"{name}.req").exists(),
                "last": _read(folder / f"{name}.json"),
            }
        )
    return {"now": stamp(now), "host_alive": host_alive(cfg, now), "ready": public_key(cfg) is not None, "keys": rows}


def request_key(cfg: Config, name: str, value: str, client: str | None = None, now: datetime | None = None) -> tuple[int, dict]:
    now = now or now_utc()

    def answer(code: int, outcome: str, body: dict) -> tuple[int, dict]:
        log_request(cfg, {"at": stamp(now), "action": "key", "key": name[:64], "client": client, "outcome": outcome})
        return code, body

    try:
        why = refusal(name, value, present(cfg))
        if why:
            raise Refused(404 if why == "isn't one of the desk's keys" else 400, "refused", f"{name[:64]} {why}.")
        key = public_key(cfg)
        if key is None or not host_alive(cfg, now):
            raise Refused(503, "host_down", "The box hasn't checked in with its key yet, so nothing would save this. Update the box script, then try again.")
    except Refused as e:
        return answer(e.code, e.error, {"ok": False, "error": e.error, "message": e.message})
    req = {"id": secrets.token_hex(6), "name": name, "requested_at": stamp(now), "ciphertext": seal(key, value)}
    folder = keys_dir(cfg)
    folder.mkdir(parents=True, exist_ok=True)
    tmp = folder / f".{name}.{req['id']}.tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(req, f)
    os.replace(tmp, folder / f"{name}.req")
    return answer(
        202,
        "queued",
        {
            "ok": True,
            "name": name,
            "request_id": req["id"],
            "requested_at": req["requested_at"],
            "message": "Saved on the box within 5 minutes, then the desk redeploys.",
        },
    )


# ---- API ----

router = APIRouter()


@router.get("/api/box/keys")
def get_keys(request: Request) -> JSONResponse:
    return JSONResponse(describe(request.app.state.cfg), headers={"Cache-Control": "no-store"})


@router.put("/api/box/keys/{name}")
async def put_key(name: str, request: Request) -> JSONResponse:
    raw = await request.body()
    headers = {"Cache-Control": "no-store"}
    try:
        value = json.loads(raw) if len(raw) <= MAX_BODY else None
    except ValueError:
        value = None
    if not isinstance(value, dict) or not isinstance(value.get("value"), str):
        return JSONResponse({"ok": False, "error": "bad_body", "message": 'Send {"value": "..."} as JSON.'}, status_code=400, headers=headers)
    client = request.client.host if request.client else None
    code, body = request_key(request.app.state.cfg, name, value["value"].strip(), client)
    return JSONResponse(body, status_code=code, headers=headers)
