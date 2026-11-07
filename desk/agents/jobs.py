from desk.agents.desks import DESKS

JOBS: list[tuple[str, str]] = [
    *((line, f"python -m desk.agents run {d.name}") for d in DESKS.values() if d.live for line in d.schedules),
    ("45 17 * * *", "python -m desk.agents triggers"),
    ("* * * * *", "python -m desk.agents queue --now-only"),
    ("30 1-5 * * *", "python -m desk.agents queue"),
    ("30 6 * * *", "python -m desk.agents lab-reviews"),
]
