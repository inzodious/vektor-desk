from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date

WEB = ("WebSearch", "WebFetch")


@dataclass(frozen=True)
class Desk:
    name: str
    title: str
    effort: str
    priority: int
    max_turns: int
    weekly_runs: int
    schedules: tuple[str, ...] = ()
    tools: tuple[str, ...] = ()
    model: str = "opus"
    live: bool = False
    only_if: Callable[[date], bool] | None = field(default=None, compare=False)

    def due_on(self, day: date) -> bool:
        return self.only_if is None or self.only_if(day)


def _first_week(day: date) -> bool:
    return day.day <= 7


DESKS: dict[str, Desk] = {
    d.name: d
    for d in (
        Desk("plan_keeper", "Plan keeper", "high", 1, 12, 10, ("30 17 * * *",), live=True),
        Desk("tax", "Tax desk", "high", 2, 16, 8, ("0 2 * 1-11 0", "0 2 * 12 *"), live=True),
        Desk("risk", "Risk desk", "high", 3, 16, 3, ("0 2 * * 6",), live=True),
        Desk("research", "Research desk", "xhigh", 4, 40, 4, ("0 1 * * 3",), WEB, live=True),
        Desk("skeptic", "Skeptic", "high", 4, 8, 10, live=True),
        Desk("scout", "Scout", "xhigh", 5, 40, 1, ("0 3 * * 0",), WEB, live=True, only_if=_first_week),
        Desk("strategy", "Strategy desk", "xhigh", 6, 40, 12, ("45 5 * * *",), WEB, live=True),
        Desk("filings", "Filings desk", "high", 7, 4, 280, ("15 4 * * *",), live=True),
        Desk("discounts", "Discount cases", "xhigh", 5, 16, 21, ("15 18 * * 1-5",), WEB, live=True),
    )
}


def get(name: str) -> Desk:
    try:
        return DESKS[name]
    except KeyError:
        raise KeyError(f"unknown desk {name!r}; known: {', '.join(DESKS)}") from None
