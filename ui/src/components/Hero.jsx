import { useMemo } from 'react';
import { Icon } from './Icon.jsx';
import { artMarkup } from './art.js';
import { AsOfLine } from '../asof/AsOfLine.jsx';

export function Hero({ kicker, title, art, big, sub, foot, chips }) {
  const markup = useMemo(() => artMarkup(art), [art]);
  return (
    <section className="phero card" style={{ '--i': 0 }}>
      <div className="ph-copy">
        <span className="ph-kick">
          <Icon name="star" />
          {kicker}
        </span>
        <h1 className="ph-title">{title}</h1>
        {big ? <div className="ph-big">{big}</div> : null}
        {sub ? <p className="muted" style={{ fontSize: 12.5 }}>{sub}</p> : null}
        <AsOfLine />
        <div className="ph-foot">{foot}</div>
      </div>
      <div className="window">
        <svg className="art" viewBox="0 0 1000 160" preserveAspectRatio="xMidYMax slice" aria-hidden="true" dangerouslySetInnerHTML={{ __html: markup }} />
        {chips ? <div className="win-chip">{chips}</div> : null}
      </div>
    </section>
  );
}
