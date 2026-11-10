import { Link, NavLink, Outlet, useLocation } from 'react-router-dom';
import { HealthBanner } from './HealthBanner.jsx';
import { Icon } from './Icon.jsx';
import { AREAS } from '../lib/areas.js';
import { clockState } from '../lib/clock.js';
import { useLive } from '../live/context.js';
import { etTime } from '../lib/format.js';
import { useTheme } from '../lib/theme.js';
import { useNow } from '../lib/useNow.js';
import { ConsoleButton } from '../research/Console.jsx';
import { SymbolSearch } from '../research/SymbolSearch.jsx';

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
      const here = pathname === '/' || pathname === '/results' || pathname.startsWith('/results/');
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
          <MarketClock />
          <ConsoleButton />
          <ThemeButton />
        </div>
      </header>
      <main className="content" id="main" tabIndex={-1}>
        <HealthBanner />
        <Outlet />
      </main>
      <nav className="nav dock" aria-label="Areas, phone">
        <NavLinks badges={badges} />
      </nav>
    </>
  );
}
