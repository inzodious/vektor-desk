import os
import sys

import uvicorn
from uvicorn.supervisors import Multiprocess

MAX_REQUESTS = 1000
JITTER = 100
FOLDERS = ("home", "inbox/fidelity", "run")


def config() -> uvicorn.Config:
    env = os.environ
    return uvicorn.Config(
        env.get("DESK_API_APP", "desk.api.app:app"),
        host=env.get("DESK_API_HOST", "0.0.0.0"),  # noqa: S104
        port=int(env.get("DESK_API_PORT", "8000")),
        workers=1,
        proxy_headers=True,
        forwarded_allow_ips="*",
        limit_max_requests=int(env.get("DESK_API_MAX_REQUESTS", MAX_REQUESTS)),
        limit_max_requests_jitter=int(env.get("DESK_API_MAX_REQUESTS_JITTER", JITTER)),
        timeout_worker_healthcheck=20,
    )


def main() -> int:
    data = os.environ.get("DESK_DATA_DIR", "/data")
    for folder in FOLDERS:
        os.makedirs(os.path.join(data, folder), exist_ok=True)
    cfg = config()
    Multiprocess(cfg, sockets=[cfg.bind_socket()]).run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
