import sqlite3
from collections.abc import Iterator

from fastapi import Request

from desk.config import Config
from desk.db import desk_conn


def get_cfg(request: Request) -> Config:
    return request.app.state.cfg


def get_desk_db(request: Request) -> Iterator[sqlite3.Connection]:
    conn = desk_conn(request.app.state.cfg)
    try:
        yield conn
    finally:
        conn.close()


def get_desk_db_readonly(request: Request) -> Iterator[sqlite3.Connection]:
    conn = desk_conn(request.app.state.cfg, readonly=True)
    try:
        yield conn
    finally:
        conn.close()
