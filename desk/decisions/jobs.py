JOBS = [
    {"name": "sync", "schedule": "10 8,17 * * *", "command": "python -m desk.decisions sync"},
    {
        "name": "tidy",
        "title": "Clear out-of-date decisions",
        "schedule": "15 6 * * *",
        "command": "python -m desk.decisions tidy",
        "heavy": False,
        "overnight": 300,
    },
]
