from desk.agents.desks import DESKS

JOBS: list[tuple[str, str]] = [(line, f"python -m desk.agents run {d.name}") for d in DESKS.values() if d.live for line in d.schedules]
