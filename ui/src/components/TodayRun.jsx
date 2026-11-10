import { Link } from 'react-router-dom';
import { Icon } from './Icon.jsx';
import { useApi } from '../lib/api.js';
import { todayRun } from '../lib/todayRun.js';

export function TodayRun({ i = 7 }) {
  const api = useApi('/api/jobs', { every: 60000 });
  const d = api.data;
  if (!d || !Array.isArray(d.jobs)) return null;
  const run = todayRun(d);
  return (
    <div className="card c12 run" style={{ '--i': i }} data-testid="today-run" data-done={run.done} data-total={run.total}>
      <div className="card-head">
        <span className="tag sky">Today’s run</span>
        <span className="acts">
          <span className={`chip ${run.tone}`} data-testid="run-head">
            {run.head}
          </span>
          <Link className="link" to="/settings#jobs" data-testid="run-jobs">
            All jobs
          </Link>
        </span>
      </div>
      <ol className="run-stages">
        {run.stages.map((s) => (
          <li key={s.id} className="run-stage" data-stage={s.id} data-state={s.state} title={s.blurb}>
            <span className="run-dot" aria-hidden="true">
              {s.state === 'ok' ? <Icon name="check" /> : null}
            </span>
            <span className="run-text">
              {s.id === 'review' && s.state !== 'soon' ? (
                <Link className="run-link" to="/results/day" data-testid="run-results">
                  {s.title}
                </Link>
              ) : (
                <b>{s.title}</b>
              )}
              <small>
                <span className="sr-only">{s.word.t}. </span>
                {s.line}
              </small>
            </span>
          </li>
        ))}
      </ol>
    </div>
  );
}
