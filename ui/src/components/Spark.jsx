import { sparkPath } from '../lib/charts.js';

export function Spark({ values, color = 'var(--s1)', base, w = 120, h = 26, label }) {
  if (!values || values.filter((v) => v != null).length < 2) return null;
  const { d, y } = sparkPath(base != null ? [...values] : values, w, h);
  const by = base != null ? y(base) : null;
  return (
    <svg viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" role={label ? 'img' : undefined} aria-label={label} aria-hidden={label ? undefined : 'true'}>
      {by != null && by >= 0 && by <= h ? <line x1="0" x2={w} y1={by} y2={by} stroke="currentColor" strokeOpacity=".3" strokeDasharray="2 3" vectorEffect="non-scaling-stroke" /> : null}
      <path d={d} fill="none" stroke={color} strokeWidth="1.8" vectorEffect="non-scaling-stroke" strokeLinejoin="round" />
    </svg>
  );
}
