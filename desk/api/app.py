import html
import json
import os
import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from desk import __version__
from desk.config import Config
from desk.db import apply_schemas, connect
from desk.packages import seams
from desk.status import status

BUILD = os.environ.get("DESK_BUILD", "dev")


def latest_positions(cfg: Config) -> dict:
    if not cfg.mirror_db.exists():
        return {"asOf": None, "positions": []}
    conn = connect(cfg.mirror_db, readonly=True)
    try:
        snaps = [json.loads(r["json"]) for r in conn.execute("SELECT json FROM rows WHERE tbl='snapshots'")]
        if not snaps:
            return {"asOf": None, "positions": []}
        snap = max(snaps, key=lambda s: str(s.get("asOf", "")))
        rows = conn.execute(
            "SELECT json FROM rows WHERE tbl='positions' AND json_extract(json, '$.snapshotId') = ?",
            (snap.get("id"),),
        )
        positions = []
        for r in rows:
            p = json.loads(r["json"])
            positions.append({k: p.get(k) for k in ("accountKey", "symbol", "description", "quantity", "lastPrice", "value", "cost", "isCash")})
    except sqlite3.Error:
        return {"asOf": None, "positions": []}
    finally:
        conn.close()
    positions.sort(key=lambda p: -(p.get("value") or 0))
    return {"asOf": snap.get("asOf"), "total": snap.get("total"), "positions": positions}


def smoke_page(cfg: Config) -> str:
    s = status(cfg)
    held = latest_positions(cfg)
    rows = "".join(
        f"<tr><td>{html.escape(str(p.get('symbol') or ''))}</td><td>{html.escape(str(p.get('accountKey') or ''))}</td>"
        f"<td class=n>{(p.get('value') or 0):,.2f}</td></tr>"
        for p in held["positions"]
    )
    mirror = s["mirror"]
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Vektor Desk</title>
<style>
:root{{color-scheme:light dark;--bg:#f6f3ec;--ink:#1d1b26;--muted:#6b6878;--line:#ddd6c8}}
@media (prefers-color-scheme:dark){{:root{{--bg:#1c1d21;--ink:#ecebef;--muted:#9a99a6;--line:#33343a}}}}
body{{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,sans-serif}}
main{{max-width:720px;margin:0 auto;padding:24px 16px}}
h1{{font-size:22px;margin:0 0 4px}}p{{color:var(--muted);margin:0 0 16px}}
table{{width:100%;border-collapse:collapse}}td{{padding:6px 4px;border-bottom:1px solid var(--line)}}.n{{text-align:right;font-variant-numeric:tabular-nums}}
</style></head><body><main>
<h1>Vektor Desk is up</h1>
<p>Mirror {html.escape(mirror["state"])}{f", last pull {html.escape(str(mirror.get('last_ok')))}" if mirror.get("last_ok") else ""}.
Holdings as of {html.escape(str(held["asOf"] or "no snapshot yet"))}. Build {html.escape(BUILD[:7])}.</p>
<table>{rows}</table>
</main></body></html>"""


def create_app(cfg: Config | None = None, *, packages: list[str] | None = None, schemas: bool = True) -> FastAPI:
    cfg = cfg or Config.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if schemas:
            app.state.schemas = apply_schemas(cfg, only=packages)
        yield

    app = FastAPI(title="Vektor Desk", version=__version__, docs_url=None, redoc_url=None, openapi_url="/api/openapi.json", lifespan=lifespan)
    app.state.cfg = cfg

    @app.get("/api/health")
    def health() -> dict:
        return {"ok": True, "build": BUILD, "version": __version__}

    @app.get("/api/status")
    def get_status() -> JSONResponse:
        return JSONResponse(status(cfg), headers={"Cache-Control": "no-store"})

    @app.get("/api/positions")
    def get_positions() -> JSONResponse:
        return JSONResponse(latest_positions(cfg), headers={"Cache-Control": "no-store"})

    app.state.routers = []
    for pkg, mod in seams("api", packages).items():
        router = getattr(mod, "router", None)
        if router is None:
            raise RuntimeError(f"desk/{pkg}/api.py has no `router`")
        app.include_router(router)
        app.state.routers.append(pkg)

    ui = Path(os.environ.get("DESK_UI_DIR", "/app/ui/dist"))
    if (ui / "index.html").exists():
        app.mount("/", StaticFiles(directory=ui, html=True), name="ui")
    else:

        @app.get("/", response_class=HTMLResponse)
        def home() -> str:
            return smoke_page(cfg)

    return app


app = create_app()
