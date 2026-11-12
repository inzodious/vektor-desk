import { useAsOf } from '../lib/asof.js';

export function AsOfLine() {
  const a = useAsOf();
  if (!a) return null;
  const f = a.figures;
  return (
    <p className={`ph-asof ${a.tone}`} title={a.title || undefined} data-testid="asof" data-day={a.day}>
      <b data-testid="asof-day">{a.text}</b>
      {a.provisional ? <span className="chip lilac">Provisional</span> : null}
      {a.behind ? <span className="chip watch">Behind</span> : null}
      {f ? (
        <>
          <span>
            Day{' '}
            <em className={f.tone} data-testid="asof-change">
              {f.change}
            </em>
          </span>
          <span>
            Cash ready <em data-testid="asof-cash">{f.cash}</em>
          </span>
          <span>
            Margin <em data-testid="asof-margin">{f.margin}</em>
          </span>
        </>
      ) : null}
    </p>
  );
}
