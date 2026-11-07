JOBS = [
    ("20 8,17 * * *", "python -m desk.engine daily"),
    ("*/15 * * * *", "python -m desk.engine lots"),
    ("*/5 4-20 * * 1-5", "python -m desk.engine quotes"),
    ("10 1-6 * * *", "python -m desk.engine backfill"),
    ("40 0 * * *", "python -m desk.engine research"),
]
