const A0 = -120;
const A1 = 120;

function pt(a, r) {
  return [100 + r * Math.sin((a * Math.PI) / 180), 100 - r * Math.cos((a * Math.PI) / 180)];
}

export function Gauge({ value, min = 0, max = 10, zones = [], unit = '', label, reading, note, onOpen }) {
  const ang = (v) => A0 + ((v - min) / (max - min || 1)) * (A1 - A0);
  const arc = (v0, v1, r) => {
    const [x0, y0] = pt(ang(v0), r);
    const [x1, y1] = pt(ang(v1), r);
    const large = ang(v1) - ang(v0) > 180 ? 1 : 0;
    return `M${x0} ${y0}A${r} ${r} 0 ${large} 1 ${x1} ${y1}`;
  };
  const ticks = Array.from({ length: 11 }, (_, i) => {
    const v = min + (i / 10) * (max - min);
    const [x0, y0] = pt(ang(v), 76);
    const [x1, y1] = pt(ang(v), i % 5 ? 70 : 64);
    return { i, x0, y0, x1, y1 };
  });
  const has = value != null;
  const Tag = onOpen ? 'button' : 'div';
  const [nx, ny] = pt(ang(has ? Math.max(min, Math.min(max, value)) : min), 58);
  return (
    <Tag {...(onOpen ? { type: 'button', onClick: onOpen } : { role: 'img' })} className={`gauge${onOpen ? '' : ' still'}`} aria-label={`${label}: ${reading}${note ? `, ${note}` : ''}`}>
      <svg viewBox="10 10 180 180" aria-hidden="true">
        <circle cx="100" cy="100" r="86" fill="var(--card)" stroke="var(--ink)" strokeWidth="3" />
        <circle cx="100" cy="100" r="78" fill="none" stroke="var(--line-2)" strokeWidth="1" />
        {zones.map((z) => (
          <path key={`${z.from}-${z.to}`} d={arc(z.from, z.to, 66)} fill="none" stroke={z.color} strokeWidth="12" />
        ))}
        {ticks.map((t) => (
          <line key={t.i} x1={t.x0} y1={t.y0} x2={t.x1} y2={t.y1} stroke="var(--ink)" strokeWidth={t.i % 5 ? 1.5 : 2.5} strokeLinecap="round" />
        ))}
        {has ? <line x1="100" y1="100" x2={nx} y2={ny} stroke="var(--coral)" strokeWidth="4" strokeLinecap="round" /> : null}
        <circle cx="100" cy="100" r="9" fill="var(--ink)" />
        <circle cx="100" cy="100" r="3.5" fill="var(--mustard)" />
        <text x="100" y="136" textAnchor="middle" style={{ fontFamily: 'var(--f-poster)', fontSize: 15, fill: 'var(--ink-3)', letterSpacing: '.12em' }}>
          {unit}
        </text>
      </svg>
      <b>{reading}</b>
      <small>{label}</small>
      {note ? <small className="gauge-note">{note}</small> : null}
    </Tag>
  );
}
