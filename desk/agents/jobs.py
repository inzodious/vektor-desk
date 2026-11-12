from desk.agents.desks import DESKS

PORTFOLIO = "research"
PORTFOLIO_JOB = {"name": "run-research", "title": "Analyse every holding", "command": "python -m desk.agents run research"}

JOBS: list[tuple[str, str] | dict] = [
    *((line, f"python -m desk.agents run {d.name}") for d in DESKS.values() if d.live and d.name != PORTFOLIO for line in d.schedules),
    *(PORTFOLIO_JOB | {"schedule": line} | ({"overnight": 200} if i == 0 else {}) for i, line in enumerate(DESKS[PORTFOLIO].schedules)),
    ("45 17 * * *", "python -m desk.agents triggers"),
    ("* * * * *", "python -m desk.agents queue --now-only"),
    ("30 1-5 * * *", "python -m desk.agents queue"),
    ("30 6 * * *", "python -m desk.agents lab-reviews"),
]
