(function () {
  const D = window.DATA;
  const qs = new URLSearchParams(location.search);
  const STILL = qs.has('still');

  // ---------- theme ----------
  function readTheme() {
    const q = qs.get('theme');
    if (q === 'dark' || q === 'light') return q;
    try { return localStorage.getItem('desk-theme') || 'light'; } catch (e) { return 'light'; }
  }
  function applyTheme(t) {
    document.documentElement.classList.toggle('dark', t === 'dark');
    try { localStorage.setItem('desk-theme', t); } catch (e) { }
  }
  applyTheme(readTheme());

  // ---------- format ----------
  const usd = (v, o = {}) => {
    const s = Math.abs(v).toLocaleString('en-US', { minimumFractionDigits: o.cents ? 2 : 0, maximumFractionDigits: o.cents ? 2 : 0 });
    const sign = v < 0 ? '−' : o.sign ? '+' : '';
    return `${sign}$${s}`;
  };
  const pct = (v, dg = 1, sign) => `${v < 0 ? '−' : sign ? '+' : ''}${Math.abs(v * 100).toFixed(dg)}%`;
  const pts = (v, sign = true) => `${v < 0 ? '−' : sign ? '+' : ''}${Math.abs(v * 100).toFixed(1)} pts`;
  const px = (v) => (v >= 1000 ? v.toLocaleString('en-US', { maximumFractionDigits: 0 }) : v.toFixed(2));
  const mon = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  const dShort = (dt) => `${mon[dt.getUTCMonth()]} ${dt.getUTCDate()}`;
  const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

  // ---------- icons ----------
  const P = {
    bridge: '<path d="M3 17h18M5 17V9l7-4 7 4v8M9 17v-4h6v4"/>',
    research: '<circle cx="11" cy="11" r="6"/><path d="M20 20l-4.5-4.5M8.5 11h5M11 8.5v5"/>',
    decisions: '<path d="M4 6h10M4 12h7M4 18h10"/><path d="M15 15l2.5 2.5L22 12"/>',
    plan: '<circle cx="12" cy="12" r="8"/><circle cx="12" cy="12" r="4"/><circle cx="12" cy="12" r="1"/>',
    lab: '<path d="M9 3h6M10 3v6l-5 9a2 2 0 0 0 2 3h10a2 2 0 0 0 2-3l-5-9V3"/><path d="M7.5 15h9"/>',
    settings: '<circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M4.2 4.2l2.1 2.1M17.7 17.7l2.1 2.1M2 12h3M19 12h3M4.2 19.8l2.1-2.1M17.7 6.3l2.1-2.1"/>',
    search: '<circle cx="11" cy="11" r="7"/><path d="M20 20l-4-4"/>',
    moon: '<path d="M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5z"/>',
    sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
    chev: '<path d="M6 9l6 6 6-6"/>',
    right: '<path d="M9 6l6 6-6 6"/>',
    x: '<path d="M6 6l12 12M18 6L6 18"/>',
    star: '<path d="M12 2l1.4 8.1L22 12l-8.6 1.9L12 22l-1.4-8.1L2 12l8.6-1.9z"/>',
    gauge: '<path d="M4 16a8 8 0 1 1 16 0"/><path d="M12 16l4-5"/>',
    calendar: '<rect x="4" y="5" width="16" height="15" rx="3"/><path d="M4 10h16M9 3v4M15 3v4"/>',
    bolt: '<path d="M13 2L5 14h6l-1 8 8-12h-6z"/>',
    check: '<path d="M5 12.5l4.5 4.5L19 7"/>',
    copy: '<rect x="8" y="8" width="12" height="12" rx="3"/><path d="M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2"/>',
    compass: '<circle cx="12" cy="12" r="9"/><path d="M15.5 8.5l-2 5-5 2 2-5z"/>',
    coin: '<circle cx="12" cy="12" r="8"/><path d="M14.5 9.5c-.5-1-1.5-1.5-2.5-1.5-1.5 0-2.5.8-2.5 2s1 1.7 2.5 2 2.5.8 2.5 2-1 2-2.5 2c-1 0-2-.5-2.5-1.5M12 6.5v1.5M12 16v1.5"/>',
    shield: '<path d="M12 3l7 3v5c0 5-3 8-7 10-4-2-7-5-7-10V6z"/>',
    book: '<path d="M5 4h9a3 3 0 0 1 3 3v13H8a3 3 0 0 1-3-3z"/><path d="M5 17a3 3 0 0 1 3-3h9"/>',
    telescope: '<path d="M3 13l12-6 2 4-12 6zM15 7l3-1.5 2 4-3 1.5M9 16l-2 5M11 15l2 6"/>',
    eye: '<path d="M2 12s3.5-6 10-6 10 6 10 6-3.5 6-10 6S2 12 2 12z"/><circle cx="12" cy="12" r="2.5"/>',
    user: '<circle cx="12" cy="8" r="4"/><path d="M4 21c1-4 4-6 8-6s7 2 8 6"/>',
    play: '<path d="M7 5l12 7-12 7z"/>',
    pin: '<path d="M12 21s-6-5.5-6-11a6 6 0 0 1 12 0c0 5.5-6 11-6 11z"/><circle cx="12" cy="10" r="2"/>',
    info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 8v.01"/>',
    flag: '<path d="M5 21V4M5 4h11l-2 4 2 4H5"/>',
    clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    send: '<path d="M4 12l16-8-6 16-2-6z"/>',
    snooze: '<path d="M12 21a8 8 0 1 0-8-8"/><path d="M12 9v4l2 2M3 4l3 3"/>',
    plus: '<path d="M12 5v14M5 12h14"/>',
    layers: '<path d="M12 3l9 5-9 5-9-5z"/><path d="M3 13l9 5 9-5"/>',
    swap: '<path d="M7 7h12l-3-3M17 17H5l3 3"/>',
  };
  const ico = (n) => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${P[n] || P.star}</svg>`;
  const ROBOT = '<svg viewBox="0 0 40 40" aria-hidden="true"><path d="M20 4v5" stroke="currentColor" stroke-width="2" stroke-linecap="round"/><circle cx="20" cy="4" r="2.4" fill="var(--coral)"/><rect x="7" y="10" width="26" height="20" rx="7" fill="var(--mustard)" stroke="var(--ink)" stroke-width="2"/><rect x="11.5" y="15" width="17" height="9" rx="4" fill="var(--board)"/><circle cx="16.5" cy="19.5" r="2" fill="var(--mint)"/><circle cx="23.5" cy="19.5" r="2" fill="var(--mint)"/><path d="M4 18v6M36 18v6" stroke="var(--ink)" stroke-width="2.4" stroke-linecap="round"/><path d="M14 30v4h12v-4" fill="none" stroke="var(--ink)" stroke-width="2"/></svg>';

  // ---------- nav ----------
  const AREAS = [
    { key: 'bridge', title: 'Bridge', short: 'Bridge', href: 'bridge.html' },
    { key: 'research', title: 'Research', short: 'Research', href: 'research.html' },
    { key: 'decisions', title: 'Decisions', short: 'Decide', href: 'decisions.html', badge: 5 },
    { key: 'plan', title: 'Plan', short: 'Plan', href: 'plan.html' },
    { key: 'lab', title: 'Lab', short: 'Lab', href: 'lab-compare.html' },
    { key: 'settings', title: 'Settings', short: 'Settings', href: 'settings.html' },
  ];
  const SUBS = {
    research: [['research.html', 'Dossiers'], ['#', 'Sources'], ['#', 'Watchlist'], ['#', 'Calendar']],
    decisions: [['decisions.html', 'Queue'], ['journal.html', 'Journal'], ['flight.html', 'Flight record']],
    plan: [['plan.html', 'Mix and drift'], ['#', 'Deposits'], ['#', 'Rules'], ['#', 'Tax calendar'], ['#', 'FI path']],
    lab: [['lab-compare.html', 'Compare'], ['lab-risk.html', 'Risk'], ['lab-patterns.html', 'Patterns'], ['#', 'Saved boards']],
  };
  const here = location.pathname.split('/').pop() || 'bridge.html';
  const subtabs = (area) => `<nav class="subtabs" aria-label="${area} views">${SUBS[area].map(([h, t]) => `<a href="${h}"${h === here ? ' aria-current="page"' : ''}>${t}</a>`).join('')}</nav>`;

  function links(active) {
    return AREAS.map((a) => `<a href="${a.href}"${a.key === active ? ' aria-current="page"' : ''} title="${a.title}">${ico(a.key)}<span class="long">${a.title}</span><span class="short">${a.short}</span>${a.badge ? `<span class="badge">${a.badge}</span>` : ''}</a>`).join('');
  }

  function shell(active) {
    const dark = document.documentElement.classList.contains('dark');
    const top = document.createElement('header');
    top.className = 'topbar';
    top.innerHTML = `
      <a class="brand" href="bridge.html" aria-label="Vektor Desk home"><img src="assets/mark.svg" alt=""><b>Vektor <em>Desk</em></b></a>
      <nav class="nav" aria-label="Areas">${links(active)}</nav>
      <div class="tools">
        <button class="search" type="button" data-search>${ico('search')}<span>Symbol or command</span><kbd>/</kbd></button>
        <span class="clock" title="Market open · prices from Finnhub every 5 s"><i class="pulse"></i><span class="lbl">Market open</span> <small data-clock>11:42 AM ET</small></span>
        <button class="icon-btn" type="button" data-console aria-label="Open the console" title="Console">${ROBOT.replace('<svg', '<svg style="width:24px;height:24px"')}</button>
        <button class="icon-btn" type="button" data-theme aria-label="${dark ? 'Switch to light mode' : 'Switch to dark mode'}">${ico(dark ? 'sun' : 'moon')}</button>
      </div>`;
    document.body.prepend(top);
    const dock = document.createElement('nav');
    dock.className = 'nav dock';
    dock.setAttribute('aria-label', 'Areas');
    dock.innerHTML = links(active);
    document.body.append(dock);
    top.querySelector('[data-theme]').onclick = () => {
      const next = document.documentElement.classList.contains('dark') ? 'light' : 'dark';
      applyTheme(next);
      top.querySelector('[data-theme]').innerHTML = ico(next === 'dark' ? 'sun' : 'moon');
      window.dispatchEvent(new Event('desk:theme'));
    };
    top.querySelector('[data-console]').onclick = openConsole;
    top.querySelector('[data-search]').onclick = () => openSymbol('FTEC');
    document.addEventListener('keydown', (e) => {
      if (e.key === '/' && !/input|textarea/i.test(document.activeElement.tagName)) { e.preventDefault(); openSymbol('FTEC'); }
    });
    ['tip', 'scrim', 'drawer', 'sheet', 'console'].forEach((k) => {
      const el = document.createElement('div');
      el.className = k === 'sheet' || k === 'console' ? `drawer ${k}` : k;
      el.id = `desk-${k}`;
      if (k !== 'tip' && k !== 'scrim') { el.setAttribute('role', 'dialog'); el.setAttribute('aria-modal', 'true'); }
      document.body.append(el);
    });
    document.getElementById('desk-scrim').onclick = closeAll;
    document.addEventListener('keydown', (e) => { if (e.key === 'Escape') { closeAll(); closeCombos(); } });
    document.addEventListener('click', (e) => {
      if (!e.target.closest('.combo')) closeCombos();
      const chip = e.target.closest('[data-sym]');
      if (chip) { e.preventDefault(); openSymbol(chip.dataset.sym); }
    });
  }

  // ---------- hero art ----------
  function art(kind) {
    const hills = '<path d="M0 118 C120 92 220 104 330 96 C460 86 560 112 700 98 C820 86 900 104 1000 96 L1000 160 L0 160Z" fill="var(--hill-a)"/><path d="M0 132 C160 118 300 128 450 122 C600 116 760 134 1000 120 L1000 160 L0 160Z" fill="var(--hill-b)"/>';
    const stars = Array.from({ length: 22 }, (_, i) => `<circle cx="${(i * 97) % 1000}" cy="${12 + ((i * 53) % 70)}" r="${i % 3 ? 1.1 : 1.7}" fill="#fff" opacity="var(--star-o)" style="opacity:var(--star-o)"/>`).join('');
    const sun = (x, y, r) => `<g><circle cx="${x}" cy="${y}" r="${r}" fill="var(--sun-disc)"/><path d="M${x - r} ${y + 8}h${2 * r}M${x - r + 4} ${y + 18}h${2 * r - 8}M${x - r + 12} ${y + 28}h${2 * r - 24}" stroke="var(--sky-c)" stroke-width="5"/></g>`;
    const A = {
      bridge: `${stars}${sun(820, 112, 54)}<g fill="none" stroke="var(--ink)" stroke-opacity=".28" stroke-width="1.4" stroke-dasharray="3 6"><ellipse cx="420" cy="80" rx="300" ry="46"/><ellipse cx="420" cy="80" rx="190" ry="28"/></g><g><circle cx="420" cy="80" r="15" fill="var(--teal)" stroke="var(--ink)" stroke-width="2"/><circle cx="160" cy="92" r="7" fill="var(--coral)"/><circle cx="660" cy="66" r="9" fill="var(--mustard)" stroke="var(--ink)" stroke-width="1.5"/><circle cx="560" cy="102" r="5" fill="var(--lilac)"/><circle cx="270" cy="58" r="6" fill="var(--sky)"/></g><path d="M600 40 l10 -12 l3 10 z" fill="var(--coral)"/>${hills}`,
      research: `${stars}${sun(150, 120, 46)}<g stroke="var(--ink)" stroke-width="2" fill="var(--card)"><path d="M560 104 l140 -60 l14 26 l-140 60z"/><path d="M700 44 l24 -10 l14 26 l-24 10z" fill="var(--mustard)"/><path d="M610 122 l-20 38M630 114 l14 46"/></g><g fill="var(--teal)"><circle cx="880" cy="40" r="5"/><circle cx="930" cy="70" r="3"/><circle cx="840" cy="78" r="3"/></g>${hills}`,
      decisions: `${stars}<g transform="translate(470 18)" stroke="var(--ink)" stroke-width="2"><rect x="0" y="0" width="300" height="96" rx="16" fill="var(--board)"/>${['ok', 'ok', 'watch', 'ok', 'act', 'ok'].map((t, i) => `<circle cx="${34 + i * 46}" cy="40" r="13" fill="${t === 'ok' ? 'var(--mint)' : t === 'watch' ? 'var(--mustard)' : 'var(--coral)'}"/>`).join('')}<path d="M24 74h252" stroke="var(--flap-dim)" stroke-dasharray="4 6"/></g>${sun(200, 116, 50)}${hills}`,
      plan: `${stars}${sun(500, 120, 60)}<g fill="none" stroke="var(--ink)" stroke-opacity=".35" stroke-width="1.6"><path d="M80 120 C240 30 420 20 980 30" stroke-dasharray="5 7"/></g><g transform="translate(820 32) rotate(14)"><path d="M0 -14 c8 6 9 16 6 24 h-12 c-3 -8 -2 -18 6 -24z" fill="var(--card)" stroke="var(--ink)" stroke-width="2"/><path d="M-4 10 l4 12 l4 -12" fill="var(--coral)"/></g>${hills}`,
      lab: `${stars}${sun(860, 118, 48)}<g stroke="var(--ink)" stroke-width="2"><circle cx="300" cy="92" r="30" fill="var(--teal-soft)"/><circle cx="346" cy="92" r="30" fill="var(--coral-soft)" fill-opacity=".8"/><circle cx="323" cy="62" r="30" fill="var(--mustard-soft)" fill-opacity=".7"/></g><g fill="var(--ink)" opacity=".5">${Array.from({ length: 14 }, (_, i) => `<circle cx="${520 + i * 18}" cy="${110 - Math.sin(i / 2) * 30 - i * 2}" r="3"/>`).join('')}</g>${hills}`,
      settings: `${stars}${sun(160, 118, 44)}<g transform="translate(640 74)" stroke="var(--ink)" stroke-width="2"><circle r="38" fill="var(--card)"/><circle r="14" fill="var(--mustard)"/>${Array.from({ length: 8 }, (_, i) => `<rect x="-6" y="-50" width="12" height="14" rx="3" fill="var(--card)" transform="rotate(${i * 45})"/>`).join('')}</g>${hills}`,
    };
    return `<svg class="art" viewBox="0 0 1000 160" preserveAspectRatio="xMidYMax slice" aria-hidden="true">${A[kind] || A.bridge}</svg>`;
  }

  function hero(o) {
    return `<section class="phero card" style="--i:0">
      <div class="ph-copy">
        <span class="ph-kick">${ico('star')}${o.kicker}</span>
        <h1 class="ph-title">${o.title}</h1>
        ${o.big ? `<div class="ph-big">${o.big}</div>` : ''}
        ${o.sub ? `<p class="muted" style="font-size:12.5px">${o.sub}</p>` : ''}
        <div class="ph-foot">${o.foot || ''}</div>
      </div>
      <div class="window">${art(o.art)}${o.chips ? `<div class="win-chip">${o.chips}</div>` : ''}</div>
    </section>`;
  }

  // ---------- combos ----------
  function closeCombos(except) { document.querySelectorAll('.combo.open').forEach((c) => { if (c !== except) { c.classList.remove('open'); c.querySelector('button').setAttribute('aria-expanded', 'false'); } }); }
  function combo(label, options, sel, onChange) {
    const el = document.createElement('div');
    el.className = 'combo';
    const render = () => {
      const cur = options.find((o) => (o.v ?? o) === sel) ?? options[0];
      el.innerHTML = `<button type="button" aria-haspopup="listbox" aria-expanded="false"><small>${label}</small> ${cur.t ?? cur}${ico('chev')}</button><div role="listbox">${options.map((o) => `<div role="option" tabindex="0" data-v="${o.v ?? o}" aria-selected="${(o.v ?? o) === sel}"${o.off ? ' aria-disabled="true" style="opacity:.5"' : ''}>${o.t ?? o}${o.note ? `<small class="muted">${o.note}</small>` : ''}</div>`).join('')}</div>`;
      el.querySelector('button').onclick = (e) => { e.stopPropagation(); const open = !el.classList.contains('open'); closeCombos(el); el.classList.toggle('open', open); el.querySelector('button').setAttribute('aria-expanded', String(open)); };
      el.querySelectorAll('[role=option]').forEach((o) => {
        const pick = () => { if (o.getAttribute('aria-disabled')) return; sel = isNaN(o.dataset.v) ? o.dataset.v : o.dataset.v; el.classList.remove('open'); render(); onChange && onChange(sel); };
        o.onclick = pick;
        o.onkeydown = (e) => { if (e.key === 'Enter') pick(); };
      });
    };
    render();
    return el;
  }
  const ACCTS = [{ v: 'all', t: 'All accounts' }, { v: 'Individual', t: 'Individual' }, { v: 'HSA', t: 'HSA' }, { v: '401k', t: '401(k)', note: 'Not linked yet', off: true }];
  const PERIODS = ['1D', '1W', '1M', '3M', 'YTD', '1Y', 'Max'];
  function slicers(host, o = {}) {
    const row = document.createElement('div');
    row.className = 'slicers';
    row.append(combo('Account', ACCTS, o.acct || 'all', o.onAcct));
    if (o.period !== false) row.append(combo('Period', PERIODS, o.period || '1Y', o.onPeriod));
    if (o.bench !== false) row.append(combo('Versus', [{ v: 'plan', t: 'Plan shadow' }, { v: 'spx', t: 'S&P 500 shadow' }], o.bench || 'plan', o.onBench));
    (o.extra || []).forEach((x) => row.append(x));
    const f = document.createElement('span');
    f.className = 'filters';
    f.style.display = 'contents';
    row.append(f);
    row.insertAdjacentHTML('beforeend', `<span class="sp"></span><span class="fresh"><i class="dot"></i>Mirror 8:00 AM · lots Nov 1</span><span class="sample">Sample data</span>`);
    host.append(row);
    return { row, filters: f };
  }

  // ---------- tooltip ----------
  function tip(html, x, y) {
    const t = document.getElementById('desk-tip');
    t.innerHTML = html;
    t.classList.add('on');
    const r = t.getBoundingClientRect();
    let left = x + 14, top = y + 14;
    if (left + r.width > innerWidth - 8) left = x - r.width - 14;
    if (top + r.height > innerHeight - 8) top = y - r.height - 14;
    t.style.left = `${Math.max(8, left)}px`;
    t.style.top = `${Math.max(8, top)}px`;
  }
  const untip = () => document.getElementById('desk-tip')?.classList.remove('on');
  const trow = (c, l, v) => `<div class="r"><span>${c ? `<i style="--c:${c}"></i>` : ''}${l}</span><em>${v}</em></div>`;

  // ---------- chart helpers ----------
  function niceTicks(min, max, n = 4) {
    const span = max - min || 1;
    const step0 = span / n;
    const mag = 10 ** Math.floor(Math.log10(step0));
    const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => span / s <= n) || 10 * mag;
    const lo = Math.floor(min / step) * step, hi = Math.ceil(max / step) * step;
    const out = [];
    for (let v = lo; v <= hi + step / 2; v += step) out.push(+v.toFixed(10));
    return out;
  }
  function onResize(el, fn) {
    let w = 0;
    const ro = new ResizeObserver(() => { if (Math.abs(el.clientWidth - w) > 2) { w = el.clientWidth; fn(); } });
    ro.observe(el);
    window.addEventListener('desk:theme', fn);
  }
  const legend = (series, kind = '') => `<div class="legend">${series.map((s) => `<span><i class="${s.dash ? 'dash' : kind}" style="--c:${s.color}"></i>${s.name}</span>`).join('')}</div>`;

  function lineChart(el, o) {
    el.classList.add('chart');
    const draw = () => {
      const W = Math.max(280, el.clientWidth), H = o.height || 240;
      const narrow = W < 520;
      const L = 48, R = o.endLabels && !narrow ? 92 : 12, T = 10, B = 26;
      const n = o.series[0].values.length;
      let lo = Infinity, hi = -Infinity;
      o.series.forEach((s) => s.values.forEach((v) => { if (v != null) { lo = Math.min(lo, v); hi = Math.max(hi, v); } }));
      (o.refs || []).forEach((r) => { lo = Math.min(lo, r.y); hi = Math.max(hi, r.y); });
      if (o.zero) lo = Math.min(lo, 0), hi = Math.max(hi, 0);
      const ticks = niceTicks(lo, hi, o.ticks || 4);
      lo = ticks[0]; hi = ticks[ticks.length - 1];
      const X = (i) => L + (i / (n - 1)) * (W - L - R);
      const Y = (v) => T + (1 - (v - lo) / (hi - lo)) * (H - T - B);
      const fy = o.fmtY || ((v) => v);
      let g = ticks.map((t) => `<line class="gridl" x1="${L}" x2="${W - R}" y1="${Y(t)}" y2="${Y(t)}"/><text x="${L - 8}" y="${Y(t) + 4}" text-anchor="end">${fy(t)}</text>`).join('');
      if (o.x) {
        let last = -1, lx = -999;
        o.x.forEach((d, i) => {
          const key = o.xKey ? o.xKey(d, i) : d.getUTCMonth();
          const lab = o.xLabel ? o.xLabel(d, i) : mon[d.getUTCMonth()];
          if ((i > 0 || o.xLabel) && lab && key !== last && X(i) - lx >= (narrow ? 52 : 40) && (o.xLabel || (X(i) > L + 14 && X(i) < W - R - 14))) { g += `<text x="${X(i)}" y="${H - 6}" text-anchor="middle">${lab}</text>`; lx = X(i); }
          last = key;
        });
      }
      (o.refs || []).forEach((r) => { g += `<line class="ref" x1="${L}" x2="${W - R}" y1="${Y(r.y)}" y2="${Y(r.y)}"/>${r.label ? `<text x="${r.start ? L + 6 : W - R - 4}" y="${Y(r.y) - 6}" text-anchor="${r.start ? 'start' : 'end'}" class="lbl" style="font-weight:600">${r.label}</text>` : ''}`; });
      if (o.zero) g += `<line class="axis" x1="${L}" x2="${W - R}" y1="${Y(0)}" y2="${Y(0)}"/>`;
      const paths = o.series.map((s, k) => {
        let d = '', pen = false;
        s.values.forEach((v, i) => { if (v == null) { pen = false; return; } d += `${pen ? 'L' : 'M'}${X(i).toFixed(1)} ${Y(v).toFixed(1)}`; pen = true; });
        return `<path class="mark s${k}" d="${d}" fill="none" stroke="${s.color}" stroke-width="${s.width || 2}" stroke-linejoin="round" stroke-linecap="round"${s.dash ? ' stroke-dasharray="5 5"' : ''}/>`;
      }).join('');
      let ends = '';
      if (o.endLabels && !narrow) {
        const placed = [];
        o.series.forEach((s) => {
          const v = s.values[n - 1];
          let y = Y(v) + 4;
          placed.forEach((p) => { if (Math.abs(p - y) < 14) y = p + (y >= p ? 14 : -14); });
          placed.push(y);
          ends += `<text x="${W - R + 8}" y="${y}" class="lbl">${s.short || s.name}</text>`;
        });
      }
      const marks = (o.markers || []).map((m) => `<circle cx="${X(m.i)}" cy="${Y(o.series[0].values[m.i])}" r="5" fill="${m.color || 'var(--card)'}" stroke="${o.series[0].color}" stroke-width="2"/>`).join('');
      el.innerHTML = `${o.series.length > 1 && o.legend !== false ? legend(o.series) : ''}<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(o.label || 'Line chart')}">${g}${paths}${marks}${ends}<line class="xh" x1="0" x2="0" y1="${T}" y2="${H - B}"/>${o.series.map((s, k) => `<circle class="hd" data-k="${k}" r="4.5" fill="${s.color}" stroke="var(--card)" stroke-width="2" style="opacity:0"/>`).join('')}<rect class="hit" x="${L}" y="${T}" width="${W - L - R}" height="${H - T - B}"/></svg>`;
      const svg = el.querySelector('svg'), xh = svg.querySelector('.xh'), dots = svg.querySelectorAll('.hd');
      const hit = svg.querySelector('.hit');
      hit.onmousemove = (e) => {
        const r = svg.getBoundingClientRect();
        const sx = ((e.clientX - r.left) / r.width) * W;
        const i = Math.max(0, Math.min(n - 1, Math.round(((sx - L) / (W - L - R)) * (n - 1))));
        el.classList.add('hover');
        xh.setAttribute('x1', X(i)); xh.setAttribute('x2', X(i));
        dots.forEach((dt) => { const s = o.series[dt.dataset.k]; const v = s.values[i]; if (v == null) { dt.style.opacity = 0; return; } dt.setAttribute('cx', X(i)); dt.setAttribute('cy', Y(v)); dt.style.opacity = 1; });
        const head = o.x ? (o.tipX ? o.tipX(o.x[i], i) : `${dShort(o.x[i])}, ${o.x[i].getUTCFullYear()}`) : `#${i}`;
        tip(`<b>${head}</b>${o.series.map((s) => (s.values[i] == null ? '' : trow(s.color, s.name, (o.fmtTip || fy)(s.values[i], s, i)))).join('')}${o.tipHint ? `<div class="hint">${o.tipHint}</div>` : ''}`, e.clientX, e.clientY);
      };
      hit.onmouseleave = () => { el.classList.remove('hover'); dots.forEach((dt) => (dt.style.opacity = 0)); untip(); };
      if (o.onClick) hit.onclick = (e) => { const r = svg.getBoundingClientRect(); const i = Math.round(((((e.clientX - r.left) / r.width) * W - L) / (W - L - R)) * (n - 1)); o.onClick(Math.max(0, Math.min(n - 1, i))); };
    };
    onResize(el, draw);
    draw();
  }

  function hbars(el, o) {
    el.classList.add('chart');
    const draw = () => {
      const W = Math.max(260, el.clientWidth);
      const rowH = o.rowH || 30, LW = Math.min(o.labelW || 120, W * 0.36), VW = o.valueW || 70;
      const H = o.items.length * rowH + 8;
      const vals = o.items.map((it) => it.value);
      const lo = Math.min(0, ...vals, ...(o.items.map((it) => it.ref ?? 0))), hi = Math.max(0, ...vals, ...(o.items.map((it) => it.ref ?? 0)));
      const span = hi - lo || 1;
      const x0 = LW + 8, x1 = W - VW;
      const X = (v) => x0 + ((v - lo) / span) * (x1 - x0);
      const zero = X(0);
      let g = lo < 0 ? `<line class="axis" x1="${zero}" x2="${zero}" y1="0" y2="${H}"/>` : '';
      o.items.forEach((it, i) => {
        const y = i * rowH + 6, bh = Math.min(14, rowH - 12);
        const a = X(Math.min(0, it.value)), b = X(Math.max(0, it.value));
        const w = Math.max(2, b - a);
        const col = it.color || (it.value < 0 ? 'var(--dn)' : 'var(--up)');
        const rx = 4;
        g += `<g class="mark row" data-i="${i}"><text x="0" y="${y + bh / 2 + 4}" class="lbl" style="font-weight:600">${esc(it.label)}</text>`;
        g += `<rect x="${a}" y="${y}" width="${w}" height="${bh}" rx="${rx}" fill="${col}"/>`;
        if (it.ref != null) g += `<line x1="${X(it.ref)}" x2="${X(it.ref)}" y1="${y - 3}" y2="${y + bh + 3}" stroke="var(--ink)" stroke-width="2"/>`;
        g += `<text x="${W}" y="${y + bh / 2 + 4}" text-anchor="end" class="lbl">${(o.fmt || ((v) => v))(it.value, it)}</text>`;
        g += `<rect class="hit" x="0" y="${i * rowH}" width="${W}" height="${rowH}"/></g>`;
      });
      el.innerHTML = `${o.legendHtml || ''}<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(o.label || 'Bar chart')}">${g}</svg>`;
      el.querySelectorAll('g.row').forEach((r) => {
        const it = o.items[r.dataset.i];
        r.onmousemove = (e) => { el.classList.add('dim'); r.classList.add('on'); tip(it.tip || `<b>${esc(it.label)}</b>${trow(it.color || 'var(--up)', o.name || 'Value', (o.fmt || ((v) => v))(it.value, it))}${o.onClick ? '<div class="hint">Click to drill in</div>' : ''}`, e.clientX, e.clientY); };
        r.onmouseleave = () => { el.classList.remove('dim'); r.classList.remove('on'); untip(); };
        if (o.onClick) { r.style.cursor = 'pointer'; r.onclick = () => o.onClick(it, +r.dataset.i); }
      });
    };
    onResize(el, draw);
    draw();
  }

  function columns(el, o) {
    el.classList.add('chart');
    const draw = () => {
      const W = Math.max(260, el.clientWidth), H = o.height || 180, L = 40, B = 24, T = 8;
      const vals = o.items.map((i) => i.value);
      const ticks = niceTicks(Math.min(0, ...vals), Math.max(0, ...vals), 3);
      const lo = ticks[0], hi = ticks[ticks.length - 1];
      const Y = (v) => T + (1 - (v - lo) / (hi - lo)) * (H - T - B);
      const n = o.items.length, slot = (W - L) / n, bw = Math.max(3, Math.min(o.maxW || 34, slot - 2));
      const fy = o.fmtY || ((v) => v);
      let g = ticks.map((t) => `<line class="gridl" x1="${L}" x2="${W}" y1="${Y(t)}" y2="${Y(t)}"/><text x="${L - 6}" y="${Y(t) + 4}" text-anchor="end">${fy(t)}</text>`).join('');
      g += `<line class="axis" x1="${L}" x2="${W}" y1="${Y(0)}" y2="${Y(0)}"/>`;
      const skip = Math.ceil(n / Math.floor((W - L) / 34));
      o.items.forEach((it, i) => {
        const x = L + i * slot + (slot - bw) / 2;
        const y0 = Y(Math.max(0, it.value)), h = Math.max(1.5, Math.abs(Y(it.value) - Y(0)));
        const col = it.color || (it.value < 0 ? 'var(--dn)' : 'var(--up)');
        const r = Math.min(4, bw / 2);
        const path = it.value >= 0
          ? `M${x} ${y0 + h}V${y0 + r}q0 -${r} ${r} -${r}h${bw - 2 * r}q${r} 0 ${r} ${r}V${y0 + h}z`
          : `M${x} ${Y(0)}V${Y(0) + h - r}q0 ${r} ${r} ${r}h${bw - 2 * r}q${r} 0 ${r} -${r}V${Y(0)}z`;
        g += `<g class="mark col" data-i="${i}"><path d="${path}" fill="${col}"/><rect class="hit" x="${L + i * slot}" y="${T}" width="${slot}" height="${H - T - B}"/>${i % skip === 0 ? `<text x="${x + bw / 2}" y="${H - 6}" text-anchor="middle">${esc(it.label)}</text>` : ''}</g>`;
      });
      el.innerHTML = `${o.legendHtml || ''}<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(o.label || 'Column chart')}">${g}</svg>`;
      el.querySelectorAll('g.col').forEach((c) => {
        const it = o.items[c.dataset.i];
        c.onmousemove = (e) => { el.classList.add('dim'); c.classList.add('on'); tip(it.tip || `<b>${esc(it.full || it.label)}</b>${trow(it.color || (it.value < 0 ? 'var(--dn)' : 'var(--up)'), o.name || 'Value', (o.fmtTip || fy)(it.value))}`, e.clientX, e.clientY); };
        c.onmouseleave = () => { el.classList.remove('dim'); c.classList.remove('on'); untip(); };
      });
    };
    onResize(el, draw);
    draw();
  }

  function heatmap(el, o) {
    el.classList.add('chart');
    const draw = () => {
      const W = Math.max(260, el.clientWidth);
      const LW = o.labelW || 56, TH = 22;
      const cols = o.cols.length, cw = (W - LW) / cols, ch = Math.min(o.cellH || 34, cw * (o.square ? 1 : 0.9));
      const H = TH + o.rows.length * ch;
      const color = o.color;
      let g = o.cols.map((c, j) => `<text x="${LW + j * cw + cw / 2}" y="14" text-anchor="middle" class="lbl" style="font-weight:600">${esc(c)}</text>`).join('');
      o.rows.forEach((r, i) => {
        g += `<text x="${LW - 8}" y="${TH + i * ch + ch / 2 + 4}" text-anchor="end" class="lbl" style="font-weight:600">${esc(r)}</text>`;
        o.values[i].forEach((v, j) => {
          if (v == null) return;
          const c = color(v, i, j);
          g += `<g class="mark cell" data-i="${i}" data-j="${j}"><rect x="${LW + j * cw + 1}" y="${TH + i * ch + 1}" width="${cw - 2}" height="${ch - 2}" rx="5" fill="${c.fill}"/>${o.showVals && cw > 34 ? `<text x="${LW + j * cw + cw / 2}" y="${TH + i * ch + ch / 2 + 4}" text-anchor="middle" style="fill:${c.ink};font-weight:700;font-size:11px">${o.fmt(v)}</text>` : ''}</g>`;
        });
      });
      el.innerHTML = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(o.label || 'Heatmap')}">${g}</svg>${o.scaleHtml || ''}`;
      el.querySelectorAll('g.cell').forEach((c) => {
        const i = +c.dataset.i, j = +c.dataset.j;
        c.onmousemove = (e) => { el.classList.add('dim'); c.classList.add('on'); tip(`<b>${esc(o.tipHead ? o.tipHead(i, j) : `${o.rows[i]} · ${o.cols[j]}`)}</b>${trow(null, o.name || 'Value', o.fmt(o.values[i][j]))}`, e.clientX, e.clientY); };
        c.onmouseleave = () => { el.classList.remove('dim'); c.classList.remove('on'); untip(); };
      });
    };
    onResize(el, draw);
    draw();
  }

  function scatter(el, o) {
    el.classList.add('chart');
    const draw = () => {
      const W = Math.max(280, el.clientWidth), H = o.height || 260, L = 46, R = 16, T = 12, B = 34;
      const xs = o.points.map((p) => p.x), ys = o.points.map((p) => p.y);
      const xt = niceTicks(Math.min(0, ...xs), Math.max(...xs), 4), yt = niceTicks(Math.min(0, ...ys), Math.max(...ys), 4);
      const X = (v) => L + ((v - xt[0]) / (xt[xt.length - 1] - xt[0])) * (W - L - R);
      const Y = (v) => T + (1 - (v - yt[0]) / (yt[yt.length - 1] - yt[0])) * (H - T - B);
      let g = yt.map((t) => `<line class="gridl" x1="${L}" x2="${W - R}" y1="${Y(t)}" y2="${Y(t)}"/><text x="${L - 6}" y="${Y(t) + 4}" text-anchor="end">${o.fmtY(t)}</text>`).join('');
      g += xt.map((t) => `<text x="${X(t)}" y="${H - 16}" text-anchor="middle">${o.fmtX(t)}</text>`).join('');
      g += `<text x="${W - R}" y="${H - 2}" text-anchor="end">${o.xName} →</text><text x="${L}" y="${T - 2}" >${o.yName}</text>`;
      if (yt[0] < 0) g += `<line class="axis" x1="${L}" x2="${W - R}" y1="${Y(0)}" y2="${Y(0)}"/>`;
      o.points.forEach((p, i) => {
        g += `<g class="mark pt${p.em ? ' on' : ''}" data-i="${i}"><circle cx="${X(p.x)}" cy="${Y(p.y)}" r="${p.r || 6}" fill="${p.color || 'var(--s1)'}" stroke="var(--card)" stroke-width="2"/><text x="${X(p.x) + (p.left ? -12 : 9)}" y="${Y(p.y) + 4 + (p.dy || 0)}" text-anchor="${p.left ? 'end' : 'start'}" class="lbl" style="font-size:11px">${esc(p.label)}</text><circle class="hit" cx="${X(p.x)}" cy="${Y(p.y)}" r="14"/></g>`;
      });
      el.innerHTML = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(o.label || 'Scatter')}">${g}</svg>`;
      el.querySelectorAll('g.pt').forEach((c) => {
        const p = o.points[c.dataset.i];
        c.onmousemove = (e) => { tip(`<b>${esc(p.label)}</b>${trow(p.color || 'var(--s1)', o.yName, o.fmtY(p.y))}${trow(null, o.xName, o.fmtX(p.x))}${p.sym ? '<div class="hint">Click to open</div>' : ''}`, e.clientX, e.clientY); };
        c.onmouseleave = untip;
        if (p.sym) { c.style.cursor = 'pointer'; c.onclick = () => openSymbol(p.sym); }
      });
    };
    onResize(el, draw);
    draw();
  }

  function spark(values, o = {}) {
    const w = o.w || 120, h = o.h || 26;
    const lo = Math.min(...values), hi = Math.max(...values);
    const d = values.map((v, i) => `${i ? 'L' : 'M'}${((i / (values.length - 1)) * w).toFixed(1)} ${(h - 2 - ((v - lo) / (hi - lo || 1)) * (h - 4)).toFixed(1)}`).join('');
    const base = o.base != null ? h - 2 - ((o.base - lo) / (hi - lo || 1)) * (h - 4) : null;
    return `<svg viewBox="0 0 ${w} ${h}" preserveAspectRatio="none" aria-hidden="true">${base != null ? `<line x1="0" x2="${w}" y1="${base}" y2="${base}" stroke="currentColor" stroke-opacity=".3" stroke-dasharray="2 3" vector-effect="non-scaling-stroke"/>` : ''}<path d="${d}" fill="none" stroke="${o.color || 'var(--s1)'}" stroke-width="1.8" vector-effect="non-scaling-stroke" stroke-linejoin="round"/></svg>`;
  }

  function gauge(o) {
    const a0 = -120, a1 = 120;
    const ang = (v) => a0 + ((v - o.min) / (o.max - o.min)) * (a1 - a0);
    const pt = (a, r) => [100 + r * Math.sin((a * Math.PI) / 180), 100 - r * Math.cos((a * Math.PI) / 180)];
    const arc = (v0, v1, r) => { const [x0, y0] = pt(ang(v0), r), [x1, y1] = pt(ang(v1), r); const large = ang(v1) - ang(v0) > 180 ? 1 : 0; return `M${x0} ${y0}A${r} ${r} 0 ${large} 1 ${x1} ${y1}`; };
    let s = `<circle cx="100" cy="100" r="86" fill="var(--card)" stroke="var(--ink)" stroke-width="3"/><circle cx="100" cy="100" r="78" fill="none" stroke="var(--line-2)" stroke-width="1"/>`;
    o.zones.forEach((z) => { s += `<path d="${arc(z.from, z.to, 66)}" fill="none" stroke="${z.color}" stroke-width="12" stroke-linecap="butt"/>`; });
    for (let i = 0; i <= 10; i++) { const v = o.min + (i / 10) * (o.max - o.min); const [x0, y0] = pt(ang(v), 76), [x1, y1] = pt(ang(v), i % 5 ? 70 : 64); s += `<line x1="${x0}" y1="${y0}" x2="${x1}" y2="${y1}" stroke="var(--ink)" stroke-width="${i % 5 ? 1.5 : 2.5}" stroke-linecap="round"/>`; }
    const [nx, ny] = pt(ang(Math.max(o.min, Math.min(o.max, o.value))), 58);
    s += `<line x1="100" y1="100" x2="${nx}" y2="${ny}" stroke="var(--coral)" stroke-width="4" stroke-linecap="round"/><circle cx="100" cy="100" r="9" fill="var(--ink)"/><circle cx="100" cy="100" r="3.5" fill="var(--mustard)"/>`;
    s += `<text x="100" y="136" text-anchor="middle" style="font-family:var(--f-poster);font-size:15px;fill:var(--ink-3);letter-spacing:.12em">${o.unit || ''}</text>`;
    return `<svg viewBox="10 10 180 180" aria-hidden="true">${s}</svg>`;
  }

  function driftRows(el, rows, onClick) {
    el.innerHTML = rows.map((p, i) => {
      const max = 0.65;
      const X = (v) => `${(v / max) * 100}%`;
      const lo = Math.max(0, p.target - p.band), hi = p.cap ?? p.target + p.band;
      const over = p.weight > hi || p.weight < lo;
      return `<button type="button" class="drift-row" data-i="${i}" style="display:grid;grid-template-columns:110px minmax(0,1fr) 74px;gap:12px;align-items:center;width:100%;padding:8px 4px;border:0;background:none;border-radius:10px;cursor:pointer;text-align:left">
        <span style="font-weight:700;color:var(--ink);font-size:13px;white-space:nowrap">${p.sleeve}</span>
        <span style="position:relative;height:22px">
          <span style="position:absolute;left:0;right:0;top:10px;height:2px;background:var(--track);border-radius:2px"></span>
          <span style="position:absolute;left:${X(lo)};width:calc(${X(hi)} - ${X(lo)});top:5px;height:12px;border-radius:6px;background:var(--teal-soft);border:1px solid color-mix(in srgb,var(--teal) 45%,transparent)"></span>
          <span style="position:absolute;left:${X(p.target)};top:1px;width:2px;height:20px;background:var(--ink);border-radius:1px"></span>
          <span style="position:absolute;left:calc(${X(p.weight)} - 7px);top:4px;width:14px;height:14px;border-radius:50%;background:${over ? 'var(--mustard)' : 'var(--teal)'};border:2px solid var(--card);box-shadow:0 0 0 1.5px ${over ? 'var(--mustard-ink)' : 'var(--teal-ink)'}"></span>
        </span>
        <span style="text-align:right;font-weight:800;color:var(--ink);font-size:13px;font-variant-numeric:tabular-nums">${pct(p.weight)}<small style="display:block;font-weight:700;font-size:11px;color:${over ? 'var(--watch)' : 'var(--ink-3)'}">${pts(p.drift)}</small></span>
      </button>`;
    }).join('') + `<div class="legend" style="margin:8px 0 0 4px"><span><i class="dot" style="--c:var(--teal)"></i>Actual</span><span><i style="--c:var(--ink);width:2px;height:12px"></i>Target</span><span><i style="--c:var(--teal-soft);height:10px;width:18px;border:1px solid var(--teal)"></i>Band</span><span><i class="dot" style="--c:var(--mustard)"></i>Outside band</span></div>`;
    el.querySelectorAll('.drift-row').forEach((b) => {
      const p = rows[b.dataset.i];
      b.onmouseenter = () => (b.style.background = 'var(--track)');
      b.onmouseleave = () => { b.style.background = 'none'; untip(); };
      b.onmousemove = (e) => tip(`<b>${p.sleeve}</b>${trow('var(--teal)', 'Actual', pct(p.weight))}${trow(null, 'Target', pct(p.target, 0))}${trow(null, p.cap ? 'Cap' : 'Band', p.cap ? pct(p.cap, 0) : `± ${(p.band * 100).toFixed(0)} pts`)}${trow(null, 'Value', usd(p.value))}<div class="hint">Click to see the funds</div>`, e.clientX, e.clientY);
      if (onClick) b.onclick = () => onClick(p);
    });
  }

  // ---------- drawer ----------
  function closeAll() {
    ['desk-drawer', 'desk-sheet', 'desk-console'].forEach((id) => document.getElementById(id)?.classList.remove('on'));
    document.getElementById('desk-scrim')?.classList.remove('on');
    untip();
  }
  function openPanel(id, html) {
    closeAll();
    const el = document.getElementById(id);
    el.innerHTML = html;
    el.classList.add('on');
    document.getElementById('desk-scrim').classList.add('on');
    el.querySelectorAll('[data-close]').forEach((b) => (b.onclick = closeAll));
    return el;
  }
  function openDrawer(o) {
    const crumbs = (o.crumbs || []).map((c, i) => `<button type="button" data-c="${i}">${c.label}</button><span class="sep">›</span>`).join('');
    const el = openPanel('desk-drawer', `<header><div class="t"><div class="crumbs">${crumbs}<span>${o.title}</span></div><h3>${o.title}</h3>${o.sub ? `<p class="muted" style="font-size:12.5px">${o.sub}</p>` : ''}</div><button class="icon-btn" type="button" data-close aria-label="Close">${ico('x')}</button></header><div class="body">${o.body}</div>`);
    el.querySelectorAll('[data-c]').forEach((b) => (b.onclick = () => o.crumbs[b.dataset.c].go()));
    o.after && o.after(el);
    return el;
  }

  // ---------- symbol sheet ----------
  function openSymbol(sym) {
    const s = D.SYM[sym];
    if (!s) return;
    const held = D.H.filter((h) => h.sym === sym);
    const shares = held.reduce((a, h) => a + h.shares, 0), cost = held.reduce((a, h) => a + h.cost, 0);
    const value = shares * s.px, day = shares * (s.px - s.prev);
    const chg = s.px / s.prev - 1;
    const sleeve = D.PLAN.find((p) => p.funds.includes(sym));
    const lots = D.LOTS[sym] || [];
    const props = D.PROPOSALS.filter((p) => p.symbol === sym);
    const ev = D.EVENTS.filter((e) => e.sym === sym);
    const dos = D.DOSSIERS.find((d) => d.sym === sym);
    const body = `
      <div style="display:flex;align-items:baseline;gap:12px;flex-wrap:wrap">
        <b data-live="${sym}" style="font-family:var(--f-poster);font-weight:400;font-size:44px;line-height:.9;color:var(--ink)">$${px(s.px)}</b>
        <span class="${chg >= 0 ? 'up' : 'dn'}" style="font-weight:800">${usd(s.px - s.prev, { cents: true, sign: true })} · ${pct(chg, 2, true)} today</span>
        ${s.nav ? '<span class="chip info">Mutual fund · prices at 4 PM NAV</span>' : '<span class="chip ok"><i class="pulse" style="width:6px;height:6px"></i>Live</span>'}
      </div>
      <div><div class="card-head" style="margin-bottom:4px"><span class="kicker">Price, 1 year</span><span class="muted" style="font-size:11.5px">Dots are your buys · dashed line is your average cost</span></div><div id="sheet-chart"></div></div>
      ${held.length ? `<div class="mini-kpis"><div><small>Position</small><b>${usd(value)}</b></div><div><small>Gain</small><b class="${value - cost >= 0 ? 'up' : 'dn'}">${usd(value - cost, { sign: true })}</b></div><div><small>Today</small><b class="${day >= 0 ? 'up' : 'dn'}">${usd(day, { sign: true })}</b></div></div>` : `<div class="note">${ico('eye')}<span><b style="color:var(--ink)">Not held.</b> On the watchlist with a trigger at $21.00. Drafting a buy here runs Preflight first.</span></div>`}
      ${sleeve ? `<div><span class="kicker">Plan</span><div id="sheet-drift" style="margin-top:4px"></div></div>` : ''}
      ${lots.length ? `<div><div class="card-head" style="margin-bottom:2px"><span class="kicker">Lots · Individual</span><span class="muted" style="font-size:11.5px">From the Nov 1 export</span></div><div class="tscroll"><table class="t"><thead><tr><th>Acquired</th><th class="r">Shares</th><th class="r">Cost</th><th class="r">Gain</th><th>Term</th></tr></thead><tbody>${lots.map((l) => { const gn = l.shares * (s.px - l.cost); return `<tr><td>${l.acq}</td><td class="r">${l.shares}</td><td class="r">$${l.cost.toFixed(2)}</td><td class="r ${gn >= 0 ? 'up' : 'dn'}">${usd(gn, { sign: true })}</td><td>${l.term}${l.toLong ? `<small class="muted"> · long ${l.toLong.replace(/, \d+$/, '')}</small>` : ''}</td></tr>`; }).join('')}</tbody></table></div></div>` : ''}
      ${dos ? `<div><div class="card-head" style="margin-bottom:6px"><span class="kicker">Dossier · ${dos.updated}</span><span class="chip ${dos.tone}">${dos.verdict}</span></div><div class="bb"><div class="bull"><b>Thesis</b>${THESIS[sym]?.[0] || 'Plan fund. Owned for the market, not a story.'}</div><div class="bear"><b>Bear case</b>${THESIS[sym]?.[1] || 'Tracks the market down too. That is the deal.'}</div></div></div>` : ''}
      ${props.length || ev.length ? `<div><span class="kicker">Open decisions and events</span><div class="rows" style="margin-top:4px">${props.map((p) => `<a class="row" href="decisions.html#${p.id}"><span class="l"><span class="desk-ico ${p.desk}" style="width:30px;height:30px;border-radius:9px">${ico(DESK_ICO[p.desk])}</span><div><b>${p.title}</b><small>${p.deskName} · expires ${p.expires}</small></div></span><span class="v">${ico('right').replace('<svg', '<svg style="width:16px;height:16px"')}</span></a>`).join('')}${ev.map((e) => `<div class="row"><span class="l"><span class="datebox"><small>${e.m}</small><b>${e.d}</b></span><div><b>${e.title}</b><small>${e.sub}</small></div></span><span></span></div>`).join('')}</div></div>` : ''}
      <div style="display:flex;gap:8px;flex-wrap:wrap"><a class="btn" href="decisions.html">${ico('plus')}Draft a decision</a><a class="btn ghost" href="research.html">${ico('book')}Dossier</a><a class="btn ghost" href="lab-compare.html">${ico('swap')}Compare</a></div>`;
    const el = openPanel('desk-sheet', `<header><div class="t"><div class="crumbs"><span>${s.kind}</span><span class="sep">·</span><span>${sleeve ? sleeve.sleeve : s.sleeve}</span></div><h3><span class="sym" style="font-size:20px"><i style="--c:var(--s1)"></i>${sym}</span> <small class="muted" style="font:600 13px var(--f-body)">${s.name}</small></h3></div><button class="icon-btn" type="button" data-close aria-label="Close">${ico('x')}</button></header><div class="body">${body}</div>`);
    const lotsAvg = shares ? cost / shares : null;
    const buyIdx = lots.map((l, i) => ({ i: 252 - [200, 120, 60][i % 3] }));
    lineChart(el.querySelector('#sheet-chart'), { height: 170, series: [{ name: sym, color: 'var(--s1)', values: s.series }], x: D.days, fmtY: (v) => `$${v >= 100 ? v.toFixed(0) : v.toFixed(2)}`, fmtTip: (v) => `$${v.toFixed(2)}`, refs: lotsAvg ? [{ y: lotsAvg, label: `Avg cost $${lotsAvg.toFixed(2)}` }] : [], markers: held.length ? buyIdx : [] });
    if (sleeve) driftRows(el.querySelector('#sheet-drift'), [sleeve]);
  }
  const DESK_ICO = { plan: 'compass', tax: 'coin', risk: 'shield', research: 'book', scout: 'telescope', skeptic: 'eye', me: 'user' };
  const THESIS = {
    FTEC: ['Owns the profit engine of the index at a low fee. Kept as a tilt, not a bet.', 'Top three names are about 45% of the fund, and FSKAX already holds them.'],
    UFO: ['Launch cadence and backlogs keep rising; a basket beats picking one rocket.', 'Many holdings are unprofitable; 0.75% fee; already past the satellite cap.'],
    RIVN: ['Cost per vehicle is falling and the van contract is real revenue.', 'Cash burn and dilution; the loss is worth more to you harvested than held.'],
    AAPL: ['Services margin and buybacks; a durable compounder.', 'Already about 7% of FSKAX and 15% of FTEC. Owning it again adds little.'],
    SMR: ['Small reactors are getting first orders; policy tailwind.', 'Pre-revenue at scale; first plants are years out.'],
  };

  // ---------- console ----------
  function openConsole() {
    const el = openPanel('desk-console', `
      <header><span style="width:40px;height:40px;flex:none">${ROBOT}</span><div class="t"><h3>Console</h3><p class="muted" style="font-size:12.5px">Ask a desk. Questions run tonight at 1:00 AM unless you press Run now.</p></div><button class="icon-btn" type="button" data-close aria-label="Close">${ico('x')}</button></header>
      <div class="body">
        <div class="term">
          <p class="t-hi">&gt; Why is the tax desk suggesting RIVN now?</p>
          <p class="t-step">${ico('layers')}Read brief: tax.lots, tax.wash_window, tax.marginal_rate</p>
          <p class="t-step">${ico('check')}2 lots, 1 at a loss over $250</p>
          <p class="t-ans"><b>Two reasons.</b> The Jun 2024 lot is down $693 and is long-term, so it offsets gains first. Selling by Nov 10 keeps the wash window clear of the Dec 19 FTEC distribution reinvest.</p>
          <p class="t-hi">&gt; Deep dive on NuScale for the nuclear theme</p>
          <p class="t-step">${ico('clock')}Queued for Research desk · tonight 1:00 AM · about 9 turns</p>
        </div>
        <div style="display:flex;gap:6px;flex-wrap:wrap"><button class="chip" type="button">${ico('star')}What would a 20% drop cost me?</button><button class="chip" type="button">${ico('star')}Where does the next deposit go?</button><button class="chip" type="button">${ico('star')}Compare FTEC with FSKAX overlap</button></div>
        <div style="display:flex;gap:8px"><div class="field" style="flex:1"><input aria-label="Ask a desk" placeholder="Ask a desk or request research"></div><button class="btn ghost">${ico('clock')}Tonight</button><button class="btn">${ico('play')}Run now</button></div>
        <p class="muted" style="font-size:11.5px">Answers are advice from the desks. Numbers come from the engine; nothing here can place a trade.</p>
      </div>`);
    return el;
  }

  // ---------- live ticks ----------
  const subs = [];
  function onTick(fn) { subs.push(fn); }
  if (!STILL) {
    const R = D.rng(7);
    setInterval(() => {
      const changed = [];
      Object.entries(D.SYM).forEach(([k, s]) => {
        if (s.nav || R() > 0.45) return;
        const old = s.px;
        s.px = +(s.px * (1 + (R() - 0.5) * 0.0024)).toFixed(2);
        s.intraday = [...s.intraday.slice(1), s.px];
        changed.push({ sym: k, dir: s.px >= old ? 1 : -1 });
      });
      D.H.forEach((h) => { h.px = D.SYM[h.sym].px; h.value = h.shares * h.px; h.day = h.shares * (h.px - D.SYM[h.sym].prev); });
      subs.forEach((fn) => fn(changed));
      document.querySelectorAll('[data-live]').forEach((b) => { const s = D.SYM[b.dataset.live]; if (s) b.textContent = `$${px(s.px)}`; });
    }, 2600);
  }

  // ---------- flap ----------
  const flap = (txt) => `<span class="flap">${String(txt).split('').map((c) => `<span>${c === ' ' ? '&nbsp;' : esc(c)}</span>`).join('')}</span>`;

  window.DESK = { shell, hero, subtabs, slicers, combo, lineChart, hbars, columns, heatmap, scatter, spark, gauge, driftRows, openDrawer, openSymbol, openConsole, closeAll, onTick, tip, untip, trow, ico, flap, usd, pct, pts, px, dShort, esc, DESK_ICO, THESIS, ROBOT, legend };
})();
