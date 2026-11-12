import { Fragment, useEffect } from 'react';
import { Link, NavLink, Outlet, useLocation } from 'react-router-dom';
import { HealthWatch } from './HealthWatch.jsx';
import { MemoryStrip } from './MemoryStrip.jsx';
import { WorkerStrip } from './WorkerStrip.jsx';
import { Icon } from './Icon.jsx';
import { AREAS, SETTINGS } from '../lib/areas.js';
import { clockState } from '../lib/clock.js';
import { useApi } from '../lib/api.js';
import { useLive } from '../live/context.js';
import { etTime } from '../lib/format.js';
import { useTheme } from '../lib/theme.js';
import { useNow } from '../lib/useNow.js';
import { ConsoleButton } from '../research/Console.jsx';
import { SymbolSearch } from '../research/SymbolSearch.jsx';
import { setupChip } from '../lib/start.js';
import { WORKERS_EVENT, workerChip } from '../lib/workers.js';
import { StartBanner } from '../start/StartDesk.jsx';
import { useStart } from '../start/context.js';

// ---------- clock ----------
export function MarketClock() {
  const now = useNow();
  const { live } = useLive();
  const m = clockState(now, live);
  return (
    <span className="clock" title={m.hint} data-state={m.state} data-feed={m.feed} data-testid="market-clock">
      <i className={`pulse${m.feed === 'live' ? '' : m.feed === 'delayed' ? ' late' : ' off'}`} />
      <span className="lbl">{m.label}</span> <small>{etTime(now)} ET</small>
      <span className="sr">. {m.hint}</span>
    </span>
  );
}

// ---------- theme ----------
export function ThemeButton() {
  const [theme, setTheme] = useTheme();
  const dark = theme === 'dark';
  return (
    <button className="icon-btn" type="button" aria-label={dark ? 'Switch to light mode' : 'Switch to dark mode'} title={dark ? 'Light mode' : 'Dark mode'} onClick={() => setTheme(dark ? 'light' : 'dark')}>
      <Icon name={dark ? 'sun' : 'moon'} />
    </button>
  );
}

// ---------- settings ----------
export function SettingsButton() {
  return (
    <NavLink className="icon-btn gear-btn" to={SETTINGS.path} aria-label="Settings" title="Settings" data-testid="settings-open">
      <Icon name="gear" />
    </NavLink>
  );
}

// ---------- setup ----------
export function SetupChip() {
  const { setup } = useStart();
  const chip = setupChip(setup);
  if (!chip) return null;
  return (
    <Link className="setup-chip" to="/settings/first-run" aria-label={chip.label} title="Open the first-run checklist" data-testid="setup-chip" data-left={setup.left}>
      <Icon name="flag" />
      <span className="long">{chip.text}</span>
      <span className="short">{chip.short}</span>
    </Link>
  );
}

// ---------- worker ----------
function useWorkers() {
  const api = useApi('/api/workers', { every: 60000 });
  const reload = api.reload;
  useEffect(() => {
    window.addEventListener(WORKERS_EVENT, reload);
    return () => window.removeEventListener(WORKERS_EVENT, reload);
  }, [reload]);
  return api.data;
}

export function WorkerChip({ data, dot = false }) {
  const chip = workerChip(data);
  if (!chip) return null;
  return (
    <Link className={`${dot ? 'worker-dot' : 'worker-chip'} ${chip.tone}`} to={chip.to} aria-label={chip.label} title={chip.label} data-testid={dot ? 'worker-dot' : 'worker-chip'} data-state={chip.state}>
      {dot ? (
        chip.count || null
      ) : (
        <>
          <i className={`pulse${chip.state === 'online' ? '' : ' off'}`} />
          {chip.text}
        </>
      )}
    </Link>
  );
}

// ---------- nav ----------
function NavLinks({ badges }) {
  const { pathname } = useLocation();
  return AREAS.map((a) => {
    const inner = (
      <>
        <Icon name={a.key} />
        <span className="long">{a.title}</span>
        <span className="short">{a.short}</span>
        {badges?.[a.key] ? <span className="badge">{badges[a.key]}</span> : null}
      </>
    );
    if (a.path === '/') {
      const here = pathname === '/';
      return (
        <Link key={a.key} to="/" title={a.title} aria-current={here ? 'page' : undefined}>
          {inner}
        </Link>
      );
    }
    return (
      <NavLink key={a.key} to={a.path} title={a.title}>
        {inner}
      </NavLink>
    );
  });
}

export function Shell({ badges }) {
  const { view, epoch } = useStart();
  const { pathname } = useLocation();
  const workers = useWorkers();
  const starting = view.mode === 'never' || view.mode === 'running';
  return (
    <>
      <a className="skip" href="#main">
        Skip to content
      </a>
      <header className="topbar">
        <Link className="brand" to="/" aria-label="Vektor Desk home">
          <img src="/icon-192.png" alt="" />
          <b>
            Vektor <em>Desk</em>
          </b>
        </Link>
        <nav className="nav" aria-label="Areas">
          <NavLinks badges={badges} />
        </nav>
        <div className="tools">
          <SymbolSearch />
          <WorkerChip data={workers} />
          <SetupChip />
          <MarketClock />
          <ConsoleButton />
          <ThemeButton />
          <span className="gear-wrap">
            <SettingsButton />
            <WorkerChip data={workers} dot />
          </span>
        </div>
      </header>
      <main className="content" id="main" tabIndex={-1}>
        <StartBanner />
        {pathname === '/' ? <MemoryStrip /> : null}
        {pathname === '/' ? <WorkerStrip data={workers} /> : null}
        {starting ? null : <HealthWatch />}
        <Fragment key={epoch}>
          <Outlet />
        </Fragment>
      </main>
      <nav className="nav dock" aria-label="Areas, phone">
        <NavLinks badges={badges} />
      </nav>
    </>
  );
}
