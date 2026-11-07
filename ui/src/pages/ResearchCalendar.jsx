import { useMemo } from "react";
import { LineChart } from "../components/LineChart.jsx";
import { DateBox } from "../research/Dossier.jsx";
import { MarketCard, ResearchHero } from "../research/parts.jsx";
import { useResearchData, useResearchMany } from "../lib/useResearch.js";
import { useLive } from "../live/context.js";
import { useApi } from "../lib/api.js";
import { periodStart, parseDay } from "../lib/charts.js";
import { plural } from "../lib/format.js";
import { todayEt } from "../lib/tax.js";
import { eventsOf, isLink, rateLines, upcomingOf } from "../lib/research.js";

const AHEAD = 60;
const BACK = 30;

function EventRows({ items, empty }) {
  if (!items.length) return <p className="empty-hint">{empty}</p>;
  return (
    <div className="rows">
      {items.map((e) => (
        <div
          className="row still"
          key={`${e.symbol}-${e.key}`}
          data-kind={e.kind}
        >
          <span className="l">
            <DateBox day={e.date} />
            <span style={{ minWidth: 0 }}>
              <b>
                <button
                  type="button"
                  className="sym sym-btn"
                  data-sym={e.symbol}
                >
                  <i style={{ "--c": "var(--s1)" }} />
                  {e.symbol}
                </button>{" "}
                {isLink(e) ? (
                  <a href={e.url} target="_blank" rel="noreferrer noopener">
                    {e.title}
                  </a>
                ) : (
                  e.title
                )}
              </b>
              <small>{e.detail}</small>
            </span>
          </span>
          <span />
        </div>
      ))}
    </div>
  );
}

function Rates({ start }) {
  const macro = useApi(`/api/engine/macro?start=${start}`);
  const r = useMemo(() => rateLines(macro.data?.series), [macro.data]);
  return (
    <div className="card c12" data-testid="rates">
      <div className="card-head">
        <span className="tag">Treasury yields, 1 year</span>
        <span className="chip">FRED</span>
      </div>
      {r.x.length > 1 ? (
        <LineChart
          label="3-month, 2-year and 10-year Treasury yields"
          height={220}
          x={r.x}
          series={r.series}
          fmtY={(v) => `${v.toFixed(1)}%`}
          fmtTip={(v) => `${v.toFixed(2)}%`}
          endLabels
        />
      ) : (
        <p className="empty-hint">
          {macro.loading
            ? "Reading FRED…"
            : "No yields yet. They fill in once the FRED key is set and the engine runs."}
        </p>
      )}
    </div>
  );
}

export default function ResearchCalendar() {
  const r = useResearchData();
  const live = useLive();
  const today = todayEt();
  const symbols = useMemo(
    () => [
      ...r.list.map((d) => d.symbol),
      ...r.watchRows.map((w) => w.symbol),
      ...live.symbols.map((s) => s.symbol),
    ],
    [r.list, r.watchRows, live.symbols],
  );
  const many = useResearchMany(symbols);
  const events = useMemo(
    () =>
      Object.entries(many.data).flatMap(([sym, d]) =>
        eventsOf(d, today).map((e) => ({ ...e, symbol: sym })),
      ),
    [many.data, today],
  );
  const ahead = upcomingOf(events, today, AHEAD);
  const cut = new Date(parseDay(today).getTime() - BACK * 86400000)
    .toISOString()
    .slice(0, 10);
  const recent = events
    .filter((e) => e.date < today && e.date >= cut)
    .sort((a, b) => b.date.localeCompare(a.date));
  const start = periodStart("1Y", today);

  return (
    <>
      <ResearchHero
        kicker="Calendar"
        big={
          many.loading ? (
            <b>Checking…</b>
          ) : (
            <>
              <b>{ahead.length}</b>
              <span className="muted">
                {ahead.length === 1 ? "event" : "events"} in the next {AHEAD}{" "}
                days · {plural(new Set(symbols).size, "symbol")} covered
              </span>
            </>
          )
        }
      />
      <section className="grid">
        <div className="stack c6">
          <div className="card" data-testid="cal-ahead">
            <div className="card-head">
              <span className="tag coral">Coming up</span>
              <span className="chip">Next {AHEAD} days</span>
            </div>
            <EventRows
              items={ahead}
              empty={
                many.loading
                  ? "Reading the calendar…"
                  : "Nothing scheduled. Earnings dates show here once Finnhub has them."
              }
            />
          </div>
          <MarketCard />
        </div>
        <div className="card c6" data-testid="cal-recent">
          <div className="card-head">
            <span className="tag sky">Last {BACK} days</span>
            <span className="chip">Filings, reports, insider trades</span>
          </div>
          <EventRows
            items={recent}
            empty={
              many.loading
                ? "Reading filings…"
                : "Quiet month. No filings or insider trades on file."
            }
          />
        </div>
        <Rates start={start} />
      </section>
    </>
  );
}
