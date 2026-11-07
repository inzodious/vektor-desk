(function () {
  const D = window.DATA, K = window.DESK;
  const { ico, usd, pct, pts, px, esc } = K;

  // ---------- KPI tile ----------
  function kpi(o) {
    return `<button type="button" class="card kpi${o.cream ? ' cream' : ''}" data-kpi="${o.id}" style="--i:${o.i || 1}" title="${o.metric} · as of ${o.asOf || '11:42 AM'}">
      <span class="kicker"><span>${o.label}</span>${ico('right')}</span>
      <span class="v">${o.value}${o.unit ? `<small>${o.unit}</small>` : ''}</span>
      <span class="d">${o.quality ? `<span class="chip lilac" style="font-size:10.5px;padding:1px 7px;margin-right:4px">${o.quality}</span>` : ''}${o.line}</span>
      ${o.spark ? `<span class="spark">${o.spark}</span>` : ''}
    </button>`;
  }

  // ---------- proposal card ----------
  const LIGHT = { ok: 'var(--mint)', watch: 'var(--mustard)', act: 'var(--coral)' };
  const lights = (p, big) => `<span class="lights" style="display:inline-flex;gap:${big ? 8 : 4}px;align-items:center" aria-label="Preflight">${p.lights.map((l, i) => `<i title="${D.PREFLIGHT[i]}: ${l === 'ok' ? 'clear' : l === 'watch' ? 'heads up' : 'needs a reason'}" style="width:${big ? 14 : 9}px;height:${big ? 14 : 9}px;border-radius:50%;background:${LIGHT[l]};box-shadow:0 0 0 1.5px var(--card),0 0 0 2.5px ${l === 'ok' ? 'transparent' : LIGHT[l]};display:inline-block"></i>`).join('')}</span>`;
  const conf = (c) => (c == null ? '' : `<span class="conf" title="Confidence ${Math.round(c * 100)}%">${[0.2, 0.4, 0.6, 0.8, 1].map((t) => `<i class="${c >= t - 0.1 ? 'on' : ''}"></i>`).join('')}</span>`);
  const fundLabel = { deposit: 'From deposit', cash: 'From cash', margin: 'On margin', sale_proceeds: 'Sale proceeds' };
  function prop(p, o = {}) {
    const blocked = p.lights.includes('act');
    return `<div class="prop${o.on ? ' on' : ''}" data-prop="${p.id}" role="button" tabindex="0">
      <span class="desk-ico ${p.desk}">${ico(K.DESK_ICO[p.desk])}</span>
      <span style="min-width:0">
        <span class="kicker" style="font-size:10px">${p.deskName} · ${p.kind.replace('_', ' ')}</span>
        <b>${esc(p.title)}</b>
        <span class="why" style="display:block">${esc(p.why)}</span>
        <span class="meta">${lights(p)}<span class="chip ${p.funding === 'margin' ? 'act' : ''}">${fundLabel[p.funding]}</span>${blocked && p.funding === 'margin' ? `<span class="chip watch">About $${Math.round(p.amount * D.MARGIN_RATE / 12)} a month in interest</span>` : ''}${p.skeptic ? '<span class="chip lilac">Skeptic: flag</span>' : ''}<span class="chip">Expires ${p.expires}</span></span>
      </span>
      <span style="display:grid;gap:6px;justify-items:end">${conf(p.conf)}${o.actions ? `<span style="display:flex;gap:6px"><button class="btn sm" type="button" data-act="approve">${blocked ? 'Review' : 'Approve'}</button><button class="icon-btn" style="width:30px;height:30px;box-shadow:none" type="button" title="Snooze a day" aria-label="Snooze">${ico('snooze')}</button><button class="icon-btn" style="width:30px;height:30px;box-shadow:none" type="button" title="Dismiss" aria-label="Dismiss">${ico('x')}</button></span>` : ''}</span>
    </div>`;
  }

  // ---------- departures board ----------
  function board(el, rows) {
    const draw = () => {
      el.innerHTML = `<div class="board" role="table" aria-label="Live holdings">
        <div class="board-row head" role="row"><span>Symbol</span><span>Name</span><span style="text-align:right">Last</span><span style="text-align:right">Today</span><span style="text-align:right">Value</span><span>Session</span></div>
        ${rows().map((r) => `<div class="board-row" role="row" data-sym="${r.sym}" id="br-${r.sym}">${K.flap(r.sym.padEnd(5, ' '))}<span class="nm">${esc(r.name)}${r.nav ? '<span class="tag-nav">NAV</span>' : ''}</span><span class="px" data-px>${px(r.px)}</span><span class="ch ${r.chg >= 0 ? 'u' : 'd'}" data-ch>${pct(r.chg, 2, true)}<small style="display:block;font-weight:600;opacity:.8">${usd(r.day, { sign: true })}</small></span><span class="px" style="font-size:18px">${usd(r.value)}</span><span class="sp">${K.spark(r.intraday, { color: r.chg >= 0 ? '#7fe3c2' : '#ffd677', base: r.prev })}</span></div>`).join('')}
      </div>`;
    };
    draw();
    K.onTick((changed) => {
      changed.forEach((c) => {
        const row = el.querySelector(`#br-${c.sym}`);
        if (!row) return;
        const s = D.SYM[c.sym];
        const h = D.H.filter((x) => x.sym === c.sym);
        const day = h.reduce((a, x) => a + x.shares * (s.px - s.prev), 0);
        const chg = s.px / s.prev - 1;
        const pxEl = row.querySelector('[data-px]');
        pxEl.textContent = px(s.px);
        pxEl.animate([{ color: c.dir > 0 ? '#7fe3c2' : '#ffd677' }, { color: 'var(--flap)' }], { duration: 1200 });
        const ch = row.querySelector('[data-ch]');
        ch.className = `ch ${chg >= 0 ? 'u' : 'd'}`;
        ch.innerHTML = `${pct(chg, 2, true)}<small style="display:block;font-weight:600;opacity:.8">${usd(day, { sign: true })}</small>`;
        row.querySelector('.sp').innerHTML = K.spark(s.intraday, { color: chg >= 0 ? '#7fe3c2' : '#ffd677', base: s.prev });
      });
    });
  }
  const liveRows = (list) => () => list.map((h) => { const s = D.SYM[h.sym]; return { sym: h.sym, name: s.name, px: s.px, prev: s.prev, chg: s.px / s.prev - 1, day: h.shares ? h.shares * (s.px - s.prev) : 0, value: h.shares ? h.shares * s.px : 0, intraday: s.intraday, nav: s.nav }; });

  // ---------- stamped ledger ----------
  const STATUS = { 'Followed plan': 'ok', Override: 'watch', Passed: 'info', Dismissed: '', Approved: 'ok' };
  function ledger(groups) {
    return groups.map((g) => `<div class="ledger-day" style="display:grid;grid-template-columns:64px minmax(0,1fr);gap:12px;padding:10px 0;border-top:1px dashed var(--line-2)">
      <span class="stamp-day" style="align-self:start;justify-self:start;transform:rotate(-6deg);border:2px solid var(--coral-ink);color:var(--coral-ink);border-radius:8px;padding:4px 7px 1px;font-family:var(--f-poster);font-size:17px;letter-spacing:.06em;line-height:1;text-align:center;white-space:nowrap">${g.day.toUpperCase()}</span>
      <div class="rows">${g.items.map((it) => `<div class="row ledger-row" data-sym="${it.sym}" style="grid-template-columns:minmax(0,1.2fr) minmax(0,1.2fr) minmax(0,.8fr) 120px">
        <span class="l"><span class="sym"><i style="--c:var(--s1)"></i>${it.sym}</span><small style="display:inline;margin-left:6px">${it.kind.replace('_', ' ')}</small></span>
        <span><span class="chip ${STATUS[it.status] || ''}">${it.status}</span>${it.reason ? `<small style="margin-top:3px">“${esc(it.reason)}”</small>` : ''}</span>
        <span style="font-size:12.5px;color:var(--ink-3)">${it.origin}</span>
        <span class="v">${usd(it.amt)}<small style="display:block;color:${it.s30 == null ? 'var(--ink-3)' : it.s30 >= 0 ? 'var(--ok)' : 'var(--watch)'}">${it.s30 == null ? 'Scores Dec 4' : `${usd(it.s30, { sign: true })} vs plan`}</small></span>
      </div>`).join('')}</div>
    </div>`).join('');
  }

  // ---------- page boot ----------
  function page(area, build) {
    K.shell(area);
    const main = document.getElementById('main');
    build(main);
    main.querySelectorAll('.card').forEach((c, i) => { if (!c.style.getPropertyValue('--i')) c.style.setProperty('--i', Math.min(i, 8)); });
    const q = new URLSearchParams(location.search);
    if (q.get('sym')) setTimeout(() => K.openSymbol(q.get('sym')), 300);
    if (q.get('open') === 'console') setTimeout(K.openConsole, 300);
  }

  Object.assign(K, { kpi, prop, lights, conf, board, liveRows, ledger, page, fundLabel });
})();
