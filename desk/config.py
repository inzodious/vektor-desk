import os
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_TABLES = (
    "plans",
    "snapshots",
    "positions",
    "statements",
    "transactions",
    "merchantRules",
    "checkins",
    "quests",
    "xpEvents",
    "medals",
    "prefs",
    "activity",
    "paystubs",
    "prices",
    "priceCloses",
    "priceProfiles",
)


def _list(value: str | None) -> tuple[str, ...]:
    return tuple(t.strip() for t in (value or "").split(",") if t.strip())


@dataclass(frozen=True)
class Config:
    data_dir: Path = Path("/data")
    project: str = ""
    uid: str = ""
    credentials: Path = Path("/run/secrets/firestore-reader")
    tables: tuple[str, ...] = field(default_factory=tuple)
    timezone: str = "America/New_York"
    stale_hours: float = 14.0
    claude_token_expires: str = ""
    demo: bool = False

    @property
    def mirror_db(self) -> Path:
        return self.data_dir / "mirror.db"

    @property
    def desk_db(self) -> Path:
        return self.data_dir / "desk.db"

    @property
    def inbox(self) -> Path:
        return self.data_dir / "inbox"

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "Config":
        env = os.environ if env is None else env
        demo = env.get("DESK_DEMO", "") == "1"
        data_dir = Path(env.get("DESK_DATA_DIR", "/data"))
        return cls(
            data_dir=data_dir / "demo" if demo else data_dir,
            demo=demo,
            project=env.get("DESK_FIREBASE_PROJECT", "").strip(),
            uid=env.get("DESK_UID", "").strip(),
            credentials=Path(env.get("DESK_FIRESTORE_CREDENTIALS", "/run/secrets/firestore-reader")),
            tables=_list(env.get("DESK_MIRROR_TABLES")),
            timezone=env.get("TZ", "America/New_York"),
            stale_hours=float(env.get("DESK_STALE_HOURS", "14")),
            claude_token_expires=env.get("DESK_CLAUDE_TOKEN_EXPIRES", "").strip(),
        )
