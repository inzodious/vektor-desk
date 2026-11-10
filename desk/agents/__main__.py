import argparse
import json
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

from desk.agents import briefs, store
from desk.agents.console import process_queue, process_triggers, queue_retry
from desk.agents.debrief import parse_kinds, run_debrief_desk
from desk.agents.debrief import preview as preview_debrief
from desk.agents.desks import DESKS, Desk, get
from desk.agents.discounts import preview as preview_discounts
from desk.agents.discounts import run_discount_desk
from desk.agents.filings import preview as preview_filings
from desk.agents.filings import run_filings_desk
from desk.agents.pipeline import prepare, run_proposal_desk
from desk.agents.runner import GUARD_NOTE, LOCK, UNGUARDED, run_desk
from desk.agents.sources import NotReady, RealLab
from desk.agents.status import crew
from desk.agents.strategy import NO_FAMILY, nightly_inputs, queue_reviews, run_nightly
from desk.agents.strategy import build_prompt as build_strategy_prompt
from desk.config import Config
from desk.runlock import running

SMOKE = Desk("smoke", "Smoke test", "low", 0, 1, 1000)
SMOKE_SYSTEM = "You are a connectivity check. Reply with the single word OK."
EXIT = {"ok": 0, "disabled": 0, "over_budget": 0, "not_ready": 0, "unchanged": 0, "unhealthy": 0, "guarded": 0, "busy": 75, "deferred": 75}
RUN_WAIT = 2700
STANDALONE = ("filings", "discounts", "debrief")


def _recover(cfg: Config) -> None:
    fixed = store.recover(cfg, lock_free=not any(j.get("job") == LOCK for j in running(cfg)))
    if fixed["runs"] or fixed["requests"]:
        print(f"recovered {fixed['runs']} interrupted runs and {fixed['requests']} requests")


def _dry_run(cfg: Config, name: str, args) -> int:
    if name == "skeptic":
        print("The Skeptic only runs on a proposal; dry-run research or scout instead.")
        return 2
    print(f"# Dry run: {get(name).title} (no model call, nothing written)")
    if name in STANDALONE:
        if name == "debrief":
            report, prompt = preview_debrief(cfg, kinds=parse_kinds(args.kinds), so_far=args.so_far)
        else:
            report, prompt = (preview_filings if name == "filings" else preview_discounts)(cfg)
        print(report.note)
        if report.status == "disabled":
            print(f"Would skip (disabled): switch it on in Settings or set agents.desks.{name} to true.")
        elif report.status == "ok" and store.guard_on(cfg) and name not in UNGUARDED:
            print(f"Would skip (guarded): {GUARD_NOTE}")
        if not prompt:
            return 0
        schema = briefs.schema_file(name)
    elif name == "strategy":
        try:
            question, extra = args.question, None
            if args.trigger == "schedule" and not args.question and not args.symbol:
                inputs = nightly_inputs(cfg, RealLab())
                if inputs is None:
                    print(f"Would skip (not_ready): {NO_FAMILY}")
                    return 0
                question, extra = inputs
                print(f"  nightly family {extra['family']['key']}, {len(extra['family']['prior'])} earlier specs")
            _, prompt = build_strategy_prompt(cfg, RealLab(), question=question, strategy_id=args.symbol, extra=extra)
        except NotReady as e:
            print(f"Would skip (not_ready): Strategy lab not ready: {e}")
            return 0
        schema = briefs.schema_file("strategy")
    else:
        prep = prepare(cfg, name, trigger=args.trigger, question=args.question, symbol=(args.symbol or "").upper() or None)
        slice_ = prep.slice_
        print(f"Brief as of {slice_.get('as_of')} (data {slice_.get('data_as_of')}), profile {prep.version}")
        for h in slice_.get("data_health") or ():
            print(f"  health {h.get('status', '?'):<5} {h.get('check')}: {h.get('detail') or ''}")
        sections = slice_.get("sections") or {}
        print("  sections " + ", ".join(f"{k} {len(v or ())}" for k, v in sections.items()))
        if prep.symbol:
            print(f"  focus {prep.symbol}")
        guard = store.guard_on(cfg) and name not in UNGUARDED
        if prep.skip or guard:
            status, note = prep.skip or ("guarded", GUARD_NOTE)
            print(f"Would skip ({status}): {note}")
        if not prep.prompt:
            return 0
        prompt, schema = prep.prompt, prep.schema
    if args.system:
        print("\n## System prompt\n")
        print(briefs.prompt_file(name) if name in STANDALONE else briefs.system_prompt(name))
    print(f"\n## Prompt ({len(prompt):,} characters, about {len(prompt) // 4:,} tokens)\n")
    print(prompt)
    if args.schema:
        print("\n## Output schema\n")
        print(json.dumps(schema, indent=1))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m desk.agents", description="Vektor Desk agents.")
    sub = parser.add_subparsers(dest="cmd", required=True)
    run = sub.add_parser("run", help="run one desk now")
    run.add_argument("desk", choices=sorted(DESKS))
    run.add_argument("--trigger", default="schedule")
    run.add_argument("--limit", type=int, help="filings and discount desks only: at most this many this run")
    run.add_argument("--kinds", help="debrief desk only: day,week,month,year (default: all that are due)")
    run.add_argument("--so-far", action="store_true", help="debrief desk only: also debrief periods that are still open")
    queue = sub.add_parser("queue", help="work through Console and trigger requests")
    queue.add_argument("--now-only", action="store_true", help="only requests marked Run now")
    sub.add_parser("triggers", help="turn today's engine triggers into requests")
    sub.add_parser("lab-reviews", help="queue a Strategy desk run for each new lab result")
    sub.add_parser("smoke", help="one-turn check that the CLI and token work")
    sub.add_parser("status", help="print the crew status as JSON")
    dry = sub.add_parser("dry-run", help="build a desk's real brief and prompt and print them, without calling claude")
    dry.add_argument("desk", choices=sorted(DESKS))
    dry.add_argument("--symbol", help="focus symbol (research) or strategy id (strategy)")
    dry.add_argument("--question", help="a Console question to include")
    dry.add_argument("--trigger", default="console", help="schedule shows the plan keeper's unchanged-brief skip")
    dry.add_argument("--system", action="store_true", help="also print the system prompt")
    dry.add_argument("--schema", action="store_true", help="also print the output schema")
    dry.add_argument("--kinds", help="debrief desk only: day,week,month,year")
    dry.add_argument("--so-far", action="store_true", help="debrief desk only: include periods that are still open")
    guard = sub.add_parser("guard", help="the first-run guard: only the Plan keeper, Tax, Debrief and Plan desks run while it is on")
    guard.add_argument("state", choices=("on", "off", "status"), nargs="?", default="status")
    args = parser.parse_args(argv)
    cfg = Config.from_env()
    if args.cmd == "status":
        json.dump(crew(cfg), sys.stdout, indent=2)
        print()
        return 0
    if args.cmd == "dry-run":
        return _dry_run(cfg, args.desk, args)
    if args.cmd == "guard":
        if args.state != "status":
            store.set_guard(cfg, args.state == "on")
        on = store.guard_on(cfg)
        print(f"first-run guard {'on: only ' + ', '.join(UNGUARDED) + ' run' if on else 'off: every enabled desk runs'}")
        return 0
    if args.cmd in ("run", "queue"):
        _recover(cfg)
    if args.cmd == "smoke":
        out = run_desk(SMOKE, SMOKE_SYSTEM, "Connectivity check.", cfg=cfg, trigger="smoke", wait=60)
        print(f"{out.status}: {(out.result.text if out.result else out.note) or ''}".strip())
        return EXIT.get(out.status, 1)
    if args.cmd == "queue":
        tally = process_queue(cfg, now_only=args.now_only)
        if tally.ran:
            print(f"queue: {tally.ran} ran, {tally.done} done, {tally.failed} failed, {tally.requeued} moved to tonight")
        return 0
    if args.cmd == "triggers":
        made = process_triggers(cfg)
        print(f"triggers: {len(made)} new requests")
        return 0
    if args.cmd == "lab-reviews":
        made = queue_reviews(cfg)
        print(f"lab-reviews: {len(made)} new requests")
        return 0
    desk = get(args.desk)
    if not desk.live or not desk.schedules:
        print(f"{desk.title} doesn't run on its own.")
        return 2
    if args.trigger == "schedule" and not desk.due_on(datetime.now(ZoneInfo(cfg.timezone)).date()):
        print(f"{desk.title}: not due today.")
        return 0
    if desk.name == "strategy":
        nightly = run_nightly(cfg, wait=RUN_WAIT if args.trigger == "schedule" else 0.0)
        queued = f" Queued {nightly.queued.name}." if nightly.queued else ""
        if nightly.lane:
            queued = f" Registered lane {nightly.lane['id']} v{nightly.lane['version']}."
        print(f"{desk.title}: {nightly.status}.{queued} {nightly.note or ''}".rstrip())
        return EXIT.get(nightly.status, 1)
    if desk.name == "debrief":
        wait = RUN_WAIT if args.trigger == "schedule" else 0.0
        review = run_debrief_desk(cfg, kinds=parse_kinds(args.kinds), so_far=args.so_far, trigger=args.trigger, wait=wait)
        done = ", ".join(review.written) or "none"
        print(f"{desk.title}: {review.status}, wrote {done}, {len(review.failed)} failed. {review.note or ''}".strip())
        return EXIT.get(review.status, 1)
    if desk.name == "discounts":
        day = run_discount_desk(cfg, trigger=args.trigger, limit=args.limit, wait=RUN_WAIT if args.trigger == "schedule" else 0.0)
        votes = list(day.verdicts.values())
        tally = ", ".join(f"{v} {votes.count(v)}" for v in ("buy", "wait", "avoid") if v in votes)
        written = f"{len(day.written)} written" + (f" ({tally})" if tally else "")
        print(f"{desk.title}: {day.status}, {written}, {len(day.failed)} failed of {day.pending}. {day.note or ''}".strip())
        return EXIT.get(day.status, 1)
    if desk.name == "filings":
        night = run_filings_desk(cfg, trigger=args.trigger, limit=args.limit, wait=RUN_WAIT if args.trigger == "schedule" else 0.0)
        extra = f", {len(night.rejected)} refused" if night.rejected else ""
        print(f"{desk.title}: {night.status}, {len(night.scored)} scored, {len(night.failed)} failed{extra} of {night.pending}. {night.note or ''}".strip())
        return EXIT.get(night.status, 1)
    report = run_proposal_desk(cfg, desk.name, trigger=args.trigger, wait=RUN_WAIT if args.trigger == "schedule" else 0.0)
    if report.status in ("deferred", "busy") and args.trigger == "schedule":
        queue_retry(cfg, desk.name)
    print(f"{desk.title}: {report.status}, {len(report.created)} proposals, {len(report.rejected)} rejected. {report.note or ''}".strip())
    return EXIT.get(report.status, 1)


if __name__ == "__main__":
    sys.exit(main())
