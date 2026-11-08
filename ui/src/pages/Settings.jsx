import { useState } from 'react';
import { Link } from 'react-router-dom';
import { Hero } from '../components/Hero.jsx';
import { Jobs } from '../settings/Jobs.jsx';
import { Icon } from '../components/Icon.jsx';
import { Combo } from '../components/Combo.jsx';
import { Panel } from '../components/Panel.jsx';
import { useApi } from '../lib/api.js';
import { Crew, Usage } from '../agents/Crew.jsx';
import { useTheme } from '../lib/theme.js';
import { ago, count, etStamp, etTime, plural } from '../lib/format.js';
import { MIRROR, THEMES, TOKEN, daysLabel, mirrorLine, summary, tokenLine } from '../lib/status.js';
import { originName } from '../lib/decisions.js';
import { defaultsText, keyWord, profileSource } from '../lib/profile.js';

// ---------- cards ----------
function Freshness({ mirror, onOpen }) {
  const m = MIRROR[mirror.state] || MIRROR.error;
  const tables = mirror.tables ? Object.keys(mirror.tables).length : 0;
  return (
    <div className="card c6" style={{ '--i': 1 }}>
      <div className="card-head">
        <span className="tag sky">Data freshness</span>
        {tables ? (
          <span className="acts">
            <button className="link" type="button" onClick={onOpen}>
              {plural(tables, 'table')}
            </button>
          </span>
        ) : null}
      </div>
      <button className="rule rule-btn" type="button" onClick={onOpen} disabled={!tables} data-testid="mirror-row">
        <span style={{ color: `var(--${m.tone})` }}>
          <Icon name={m.icon} />
        </span>
        <span>
          <b>Mirror from Escape Vektor</b>
          <small>{mirrorLine(mirror)}</small>
        </span>
        <span className={`chip ${m.tone}`}>{m.chip}</span>
      </button>
      {mirror.state === 'failing' && mirror.last_error ? (
        <div className="note" style={{ marginTop: 10 }}>
          <Icon name="info" />
          <span>
            <b style={{ color: 'var(--ink)' }}>Latest try:</b> {mirror.last_error}. The desk keeps using the last good pull.
          </span>
        </div>
      ) : null}
      {mirror.state === 'stale' ? (
        <div className="note" style={{ marginTop: 10 }}>
          <Icon name="info" />
          <span>Older than the stale limit. Numbers still show, tagged stale, until the next pull lands.</span>
        </div>
      ) : null}
      {mirror.state === 'error' && mirror.note ? (
        <div className="note" style={{ marginTop: 10 }}>
          <Icon name="info" />
          <span>{mirror.note}</span>
        </div>
      ) : null}
    </div>
  );
}

function Token({ token }) {
  const t = TOKEN[token.state] || TOKEN.unknown;
  const pctLeft = token.days_left == null ? 0 : Math.max(0, Math.min(100, (token.days_left / 365) * 100));
  return (
    <div className="card c6" style={{ '--i': 2 }}>
      <div className="card-head">
        <span className="tag mustard">Claude token</span>
        <span className={`chip ${t.tone}`}>{t.chip}</span>
      </div>
      {token.days_left != null ? (
        <div className="token-big">
          <b className="num">{daysLabel(token)}</b>
          <span className="muted">{tokenLine(token)}</span>
        </div>
      ) : (
        <p className="muted">{tokenLine(token)}</p>
      )}
      {token.days_left != null ? (
        <div className="meter" style={{ marginTop: 8 }} aria-hidden="true">
          <i style={{ width: `${pctLeft}%`, background: token.state === 'ok' ? 'var(--teal)' : 'var(--mustard)' }} />
        </div>
      ) : null}
      {token.state === 'unknown' ? (
        <div className="note" style={{ marginTop: 10 }}>
          <Icon name="info" />
          <span>{token.note || 'Set DESK_CLAUDE_TOKEN_EXPIRES in desk.env.'}</span>
        </div>
      ) : null}
      {token.state === 'renew' || token.state === 'expired' ? (
        <div className="note" style={{ marginTop: 10 }}>
          <Icon name="info" />
          <span>
            Run <code>claude setup-token</code> on your PC, rerun <code>setup-truenas.sh</code>, then redeploy the app.
            {token.state === 'expired' ? ' Desks stay paused until then.' : ''}
          </span>
        </div>
      ) : null}
    </div>
  );
}

function About({ status, health, checkedAt, onRefresh, refreshing }) {
  const [theme, setTheme] = useTheme();
  return (
    <div className="card c6" style={{ '--i': 4 }}>
      <div className="card-head">
        <span className="tag lilac">This desk</span>
        <span className="acts">
          <button className="btn ghost sm" type="button" onClick={onRefresh} disabled={refreshing}>
            <Icon name="swap" />
            {refreshing ? 'Checking…' : 'Check again'}
          </button>
        </span>
      </div>
      <div className="kv">
        <div>
          <small>Version</small>
          <b>{status.version}</b>
        </div>
        <div>
          <small>Build</small>
          <b>{health?.build ? health.build.slice(0, 7) : '—'}</b>
        </div>
        <div>
          <small>API</small>
          <b>{health?.ok ? 'Answering' : 'No reply'}</b>
        </div>
        <div>
          <small>Checked</small>
          <b>{etTime(checkedAt)} ET</b>
        </div>
      </div>
      <div className="rule" style={{ marginTop: 6 }}>
        <span style={{ color: 'var(--teal-ink)' }}>
          <Icon name={theme === 'dark' ? 'moon' : 'sun'} />
        </span>
        <span>
          <b>Theme</b>
          <small>Saved in this browser</small>
        </span>
        <Combo label="Theme" options={THEMES} value={theme} onChange={setTheme} />
      </div>
    </div>
  );
}

function MirrorTables({ mirror, open, onClose }) {
  const rows = Object.entries(mirror.tables || {}).sort((a, b) => b[1] - a[1]);
  const total = rows.reduce((a, [, n]) => a + n, 0);
  const m = MIRROR[mirror.state] || MIRROR.error;
  return (
    <Panel open={open} onClose={onClose} title="Mirror tables" sub="Read-only copy of Escape Vektor. The desk never writes back." crumbs={[{ label: 'Settings', go: onClose }, { label: 'Data freshness', go: onClose }]}>
      <div className="mini-kpis">
        <div>
          <small>State</small>
          <b className={`tone-${m.tone}`}>{m.chip}</b>
        </div>
        <div>
          <small>Tables</small>
          <b>{rows.length}</b>
        </div>
        <div>
          <small>Rows</small>
          <b>{count(total)}</b>
        </div>
      </div>
      <p className="muted" style={{ fontSize: 12.5 }}>
        {mirrorLine(mirror)}
      </p>
      <div className="tscroll">
        <table className="t">
          <thead>
            <tr>
              <th scope="col">Table</th>
              <th scope="col" className="r">
                Rows
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map(([name, n]) => (
              <tr key={name} className="still">
                <td>{name}</td>
                <td className="r">{n ? count(n) : <span className="muted">Empty</span>}</td>
              </tr>
            ))}
          </tbody>
          <tfoot>
            <tr>
              <td>Total</td>
              <td className="r">{count(total)}</td>
            </tr>
          </tfoot>
        </table>
      </div>
    </Panel>
  );
}

function Profile({ api }) {
  const p = api.data;
  const [copied, setCopied] = useState(null);
  if (!p) {
    return (
      <div className="card c12" data-testid="profile">
        <div className="card-head">
          <span className="tag mint">Desk profile</span>
        </div>
        <p className="empty-hint">{api.loading ? 'Reading desk.yaml…' : 'The profile status did not answer.'}</p>
      </div>
    );
  }
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(p.starter);
      setCopied('ok');
    } catch {
      setCopied('fail');
    }
    setTimeout(() => setCopied(null), 1600);
  };
  const all = defaultsText(p);
  return (
    <div className="card c12" style={{ '--i': 5 }} data-testid="profile" data-source={p.exists ? 'file' : 'defaults'}>
      <div className="card-head">
        <span className="tag mint">Desk profile</span>
        <span className="acts">
          <span className="chip">v{p.version ?? '—'}</span>
          <span className={`chip${p.exists ? '' : ' lilac'}`}>{profileSource(p)}</span>
        </span>
      </div>
      {p.error ? (
        <p className="prof-error" role="status">
          <span className="chip watch">Heads up</span> {p.error}
        </p>
      ) : null}
      {p.starter ? (
        <div className="prof-starter" data-testid="starter">
          <p>
            <b>No desk.yaml yet.</b> Draft one from your data on the NAS, then edit what you like:
          </p>
          <div className="prof-cmd">
            <code>{p.starter}</code>
            <button className="btn sm" type="button" onClick={copy}>
              <Icon name={copied === 'ok' ? 'check' : 'copy'} />
              {copied === 'ok' ? 'Copied' : copied === 'fail' ? 'Copy failed' : 'Draft desk.yaml from your data'}
            </button>
          </div>
        </div>
      ) : null}
      <div className="mini-kpis prof-kpis">
        <div>
          <small>Desks</small>
          <b>{p.agents_enabled ? `${p.desks_on.length} on` : 'Off'}</b>
          <span>{p.agents_enabled ? p.desks_on.map(originName).join(', ') || 'None picked' : 'They advise only once turned on'}</span>
        </div>
        <div>
          <small>Rules</small>
          <b>{p.rules}</b>
          <span>{p.deposits_mode === 'auto' ? (p.deposits ? `${plural(p.deposits, 'deposit')} read from activity` : 'Read from your activity') : p.deposits ? `${plural(p.deposits, 'deposit')} scheduled` : 'No deposit schedule'}</span>
        </div>
        <div>
          <small>Loaded</small>
          <b>{p.loaded_at ? etStamp(p.loaded_at) : '—'}</b>
          <span>{p.set?.length ? `${plural(p.set.length, 'setting')} of yours` : 'Nothing of yours yet'}</span>
        </div>
      </div>
      <div className="prof-defaults" data-testid="still-default">
        <span className="kicker">Still default</span>
        {all ? (
          <p className="muted">{all}</p>
        ) : (
          <div className="chips-row">
            {p.defaults.map((k) => (
              <span className="chip" key={k} title={k}>
                {keyWord(k)}
              </span>
            ))}
          </div>
        )}
      </div>
      {p.warnings?.length ? (
        <ul className="lamp-notes">
          {p.warnings.map((w) => (
            <li key={w}>{w}</li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

// ---------- page ----------
export default function Settings() {
  const status = useApi('/api/status', { every: 30000 });
  const health = useApi('/api/health');
  const agents = useApi('/api/agents/status', { every: 60000 });
  const runs = useApi('/api/agents/runs?limit=8', { every: 120000 });
  const profile = useApi('/api/decisions/profile/status');
  const [drawer, setDrawer] = useState(false);
  const [checkedAt, setCheckedAt] = useState(() => new Date());
  const s = status.data;

  const refresh = () => {
    setCheckedAt(new Date());
    status.reload();
    health.reload();
  };

  if (!s && status.loading) {
    return (
      <>
        <Hero kicker="Settings" title="Settings" art="settings" big={<b>Checking…</b>} foot={<span className="chip">Asking the desk API</span>} />
        <section className="card" aria-busy="true">
          <p className="muted">Checking data freshness and the Claude token…</p>
        </section>
      </>
    );
  }

  if (!s) {
    return (
      <>
        <Hero kicker="Settings" title="Settings" art="settings" big={<b>No answer</b>} foot={<span className="chip watch">Desk API offline</span>} />
        <section className="card" role="alert">
          <div className="card-head">
            <span className="tag coral">The desk API didn&apos;t answer</span>
            <button className="btn sm" type="button" onClick={refresh}>
              <Icon name="swap" />
              Retry
            </button>
          </div>
          <p className="muted">
            {status.error?.status ? `It replied with ${status.error.status}.` : 'Nothing came back.'} If the NAS just restarted, give it a minute.
          </p>
        </section>
      </>
    );
  }

  const mt = MIRROR[s.mirror.state] || MIRROR.error;
  const tt = TOKEN[s.claude_token.state] || TOKEN.unknown;
  return (
    <>
      <Hero
        kicker={`Settings · desk v${s.version}`}
        title="Settings"
        art="settings"
        big={
          <>
            <b>{summary(s)}</b>
            <span className="muted">
              {s.mirror.age_hours != null ? `mirror ${ago(s.mirror.age_hours)}` : 'mirror not run'} · token {daysLabel(s.claude_token) ? `${daysLabel(s.claude_token)}${s.claude_token.days_left < 0 ? '' : ' left'}` : 'not set'}
            </span>
          </>
        }
        foot={
          <>
            <span className={`chip ${mt.tone}`}>Mirror · {mt.chip}</span>
            <span className={`chip ${tt.tone}`}>Token · {tt.chip}</span>
            <Link className="chip info" to="/settings/first-run" data-testid="first-run-link">
              First-run checklist
            </Link>
            {s.demo ? <span className="sample">Demo data</span> : null}
            {status.error ? <span className="chip watch">Last check failed · showing {etTime(checkedAt)}</span> : null}
          </>
        }
      />
      <section className="grid">
        <Freshness mirror={s.mirror} onOpen={() => setDrawer(true)} />
        <Token token={s.claude_token} />
        <About status={s} health={health.data} checkedAt={checkedAt} onRefresh={refresh} refreshing={status.loading} />
        <Jobs />
        <Profile api={profile} />
        <Crew
          status={agents}
          reload={() => {
            agents.reload();
            runs.reload();
          }}
        />
        <Usage status={agents} runs={runs} />
      </section>
      <MirrorTables mirror={s.mirror} open={drawer} onClose={() => setDrawer(false)} />
    </>
  );
}
