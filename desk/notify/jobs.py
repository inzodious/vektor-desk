JOBS = [
    ("20 9,18 * * *", "python -m desk.notify ops"),
    {"name": "morning", "title": "Morning alert", "schedule": "45 6 * * *", "command": "python -m desk.overnight alert", "heavy": False},
]
