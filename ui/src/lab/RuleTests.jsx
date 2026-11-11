import { Link } from 'react-router-dom';
import { Icon } from '../components/Icon.jsx';
import { useApi } from '../lib/api.js';
import { RULE_WORD, paramText, verdictOf } from '../lib/strategy.js';

function RuleRow({ r }) {
  const v = verdictOf(r.verdict);
  return (
    <Link className="row strat-row" to={`/strategies/${encodeURIComponent(r.id)}`} data-rule={r.id}>
      <span className="l">
        <span className="desk-ico sm">
          <Icon name="swap" />
        </span>
        <span style={{ minWidth: 0 }}>
          <b>{RULE_WORD[r.rule] || r.rule}</b>
          <small>
            {r.id} · best: {paramText(r.best)}
          </small>
        </span>
      </span>
      <span className={`chip ${v.tone}`}>{v.t}</span>
    </Link>
  );
}

export function RuleTests() {
  const api = useApi('/api/lab/strategies');
  const rules = api.data?.rules || [];
  return (
    <section className="card" data-testid="rules">
      <div className="card-head">
        <span className="tag mustard">Rule tests</span>
        <span className="chip">Your habits, replayed</span>
      </div>
      {rules.length ? (
        <div className="rows rule-rows">
          {rules.map((r) => (
            <RuleRow r={r} key={`${r.id}-${r.version}`} />
          ))}
        </div>
      ) : (
        <p className="empty-hint">{api.loading ? 'Opening the ledger…' : 'No rule tests yet. Rebalance bands, steering deposits, harvesting and margin can each be replayed on your own mix.'}</p>
      )}
    </section>
  );
}
