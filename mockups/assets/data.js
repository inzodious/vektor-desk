(function () {
  // ---------- seeded random ----------
  function rng(seed) {
    let a = seed >>> 0;
    return function () {
      a |= 0; a = (a + 0x6d2b79f5) | 0;
      let t = Math.imul(a ^ (a >>> 15), 1 | a);
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }
  const R = rng(20261107);
  const gauss = () => { let u = 0, v = 0; while (!u) u = R(); while (!v) v = R(); return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v); };

  // ---------- trading days ----------
  const days = [];
  const d = new Date(Date.UTC(2025, 10, 7));
  while (days.length < 253) {
    const wd = d.getUTCDay();
    if (wd !== 0 && wd !== 6) days.push(new Date(d));
    d.setUTCDate(d.getUTCDate() + 1);
  }
  const N = days.length;
  const market = Array.from({ length: N }, (_, i) => (i === 0 ? 0 : 0.0005 + 0.0095 * gauss() - (i > 150 && i < 175 ? 0.0035 : 0) + (i > 175 && i < 200 ? 0.0025 : 0)));

  // ---------- symbols (synthetic) ----------
  const SYM = {
    FSKAX: { name: 'Fidelity Total Market Index', kind: 'Mutual fund', sleeve: 'US core', beta: 1.0, idio: 0.0015, px: 168.40, er: 0.015, yld: 1.2, nav: true },
    FXAIX: { name: 'Fidelity 500 Index', kind: 'Mutual fund', sleeve: 'US core', beta: 0.98, idio: 0.0012, px: 226.30, er: 0.015, yld: 1.2, nav: true },
    FTIHX: { name: 'Fidelity Total International Index', kind: 'Mutual fund', sleeve: 'International', beta: 0.72, idio: 0.006, px: 16.10, er: 0.06, yld: 2.8, nav: true },
    FTEC: { name: 'Fidelity MSCI Information Technology ETF', kind: 'ETF', sleeve: 'Tech tilt', beta: 1.32, idio: 0.007, px: 212.80, er: 0.084, yld: 0.5 },
    UFO: { name: 'Procure Space ETF', kind: 'ETF', sleeve: 'Satellite', beta: 1.15, idio: 0.014, px: 30.90, er: 0.75, yld: 0.9 },
    AAPL: { name: 'Apple Inc.', kind: 'Stock', sleeve: 'Satellite', beta: 1.12, idio: 0.012, px: 236.50, er: 0, yld: 0.4, single: true },
    RIVN: { name: 'Rivian Automotive', kind: 'Stock', sleeve: 'Satellite', beta: 1.6, idio: 0.032, px: 13.25, er: 0, yld: 0, single: true },
    SPY: { name: 'SPDR S&P 500 ETF', kind: 'ETF', sleeve: 'Benchmark', beta: 1.0, idio: 0.0008, px: 598.20, er: 0.0945, yld: 1.2 },
    VXUS: { name: 'Vanguard Total International Stock ETF', kind: 'ETF', sleeve: 'Watchlist', beta: 0.74, idio: 0.006, px: 68.40, er: 0.05, yld: 3.0 },
    SMR: { name: 'NuScale Power', kind: 'Stock', sleeve: 'Watchlist', beta: 1.7, idio: 0.04, px: 24.10, er: 0, yld: 0, single: true },
  };
  Object.entries(SYM).forEach(([k, s], j) => {
    const raw = [1];
    for (let i = 1; i < N; i++) raw.push(raw[i - 1] * Math.exp(s.beta * market[i] + s.idio * gauss() + (k === 'RIVN' ? -0.0011 : 0) + (k === 'FTEC' ? 0.0006 : 0)));
    const f = s.px / raw[N - 1];
    s.series = raw.map((v) => v * f);
    s.prev = s.series[N - 2];
    s.sym = k;
    s.color = j;
  });

  // ---------- holdings ----------
  const H = [
    { sym: 'FSKAX', acct: 'Individual', shares: 125, cost: 18600 },
    { sym: 'FTIHX', acct: 'Individual', shares: 520, cost: 7900 },
    { sym: 'FTEC', acct: 'Individual', shares: 30, cost: 5050 },
    { sym: 'UFO', acct: 'Individual', shares: 70, cost: 2050 },
    { sym: 'AAPL', acct: 'Individual', shares: 9, cost: 1620 },
    { sym: 'RIVN', acct: 'Individual', shares: 100, cost: 2140 },
    { sym: 'FXAIX', acct: 'HSA', shares: 9.6, cost: 1960 },
  ];
  const CASH = 1600, MARGIN = 850, MARGIN_RATE = 0.12;
  H.forEach((h) => { const s = SYM[h.sym]; h.px = s.px; h.value = h.shares * s.px; h.gain = h.value - h.cost; h.day = h.shares * (s.px - s.prev); h.name = s.name; h.sleeve = s.sleeve; h.kind = s.kind; });
  const invested = H.reduce((a, h) => a + h.value, 0);
  const total = invested + CASH;
  H.forEach((h) => { h.weight = h.value / total; });

  const PLAN = [
    { sleeve: 'US core', target: 0.55, band: 0.05, funds: ['FSKAX', 'FXAIX'] },
    { sleeve: 'International', target: 0.20, band: 0.04, funds: ['FTIHX'] },
    { sleeve: 'Tech tilt', target: 0.12, band: 0.03, funds: ['FTEC'] },
    { sleeve: 'Satellite', target: 0.08, band: 0.02, cap: 0.10, funds: ['UFO', 'AAPL', 'RIVN'] },
    { sleeve: 'Cash', target: 0.05, band: 0.03, funds: ['SPAXX'] },
  ];
  PLAN.forEach((p) => {
    p.value = p.sleeve === 'Cash' ? CASH : H.filter((h) => h.sleeve === p.sleeve).reduce((a, h) => a + h.value, 0);
    p.weight = p.value / total;
    p.drift = p.weight - p.target;
  });

  // ---------- performance ----------
  const port = days.map((_, i) => H.reduce((a, h) => a + h.shares * SYM[h.sym].series[i], 0) + CASH);
  const planIdx = days.map((_, i) => PLAN.reduce((a, p) => a + p.target * (p.sleeve === 'Cash' ? 1 : p.funds.reduce((b, f) => b + SYM[f].series[i] / SYM[f].series[0], 0) / p.funds.length), 0));
  const planShadow = planIdx.map((v) => (v / planIdx[0]) * port[0]);
  const spyShadow = SYM.SPY.series.map((v) => (v / SYM.SPY.series[0]) * port[0]);

  // ---------- intraday (78 five-minute bars) ----------
  Object.values(SYM).forEach((s) => {
    const pts = [s.prev];
    for (let i = 1; i < 78; i++) pts.push(pts[i - 1] * (1 + (s.idio + 0.002) * 0.25 * gauss()));
    s.intraday = pts.map((p, i) => p + (s.px - pts[77]) * (i / 77));
  });

  // ---------- lots ----------
  const LOTS = {
    FTEC: [
      { acq: 'Mar 12, 2024', shares: 10, cost: 142.0, term: 'Long' },
      { acq: 'Nov 20, 2024', shares: 12, cost: 178.5, term: 'Long' },
      { acq: 'Aug 14, 2026', shares: 8, cost: 189.75, term: 'Short', toLong: 'Aug 15, 2027' },
    ],
    RIVN: [
      { acq: 'Jun 3, 2024', shares: 60, cost: 24.8, term: 'Long' },
      { acq: 'Feb 18, 2026', shares: 40, cost: 16.3, term: 'Short', toLong: 'Feb 19, 2027' },
    ],
    AAPL: [{ acq: 'Jan 8, 2025', shares: 9, cost: 180.0, term: 'Long' }],
    UFO: [{ acq: 'May 2, 2025', shares: 70, cost: 29.29, term: 'Long' }],
  };

  // ---------- proposals (proposal contract shape) ----------
  const PROPOSALS = [
    { id: 'p1', desk: 'plan', deskName: 'Plan keeper', kind: 'deposit_route', title: 'Route the Nov 18 deposit: $1,400 FSKAX, $600 FTIHX', symbol: 'FSKAX', account: 'Individual', amount: 2000, funding: 'deposit', why: 'US core is 3.6 points under target. This split closes most of it without selling.', rule: 'Deposits close drift first', conf: 0.62, horizon: '90 days', expires: 'Nov 24', lights: ['ok', 'ok', 'ok', 'ok', 'ok', 'ok'] },
    { id: 'p2', desk: 'tax', deskName: 'Tax desk', kind: 'harvest', title: 'Harvest RIVN Jun 2024 lot, 60 shares', symbol: 'RIVN', account: 'Individual', amount: 795, funding: 'sale_proceeds', why: 'Realizes about $693 of long-term loss, worth roughly $166 at your marginal rate.', rule: 'Harvest losses over $250', conf: 0.71, horizon: 'Dec 31', expires: 'Nov 14', lights: ['ok', 'ok', 'ok', 'watch', 'ok', 'ok'], washNote: 'No RIVN buys in any account until Dec 10' },
    { id: 'p3', desk: 'research', deskName: 'Research desk', kind: 'buy', title: 'Add $500 UFO on launch-cadence thesis', symbol: 'UFO', account: 'Individual', amount: 500, funding: 'cash', why: 'Launch cadence and backlog keep rising. Satellite is already 2.4 points past its cap.', rule: 'Industry focus: space', conf: 0.41, horizon: '90 days', expires: 'Nov 13', lights: ['act', 'watch', 'ok', 'ok', 'ok', 'act'], skeptic: 'Flag. Backlog growth is priced in at 31x sales; the cap exists for this.' },
    { id: 'p4', desk: 'risk', deskName: 'Risk desk', kind: 'hold_off', title: 'Pay the $850 margin debit from SPAXX', symbol: 'SPAXX', account: 'Individual', amount: 850, funding: 'cash', why: 'Saves about $9 a month in interest. Cash stays above the 2% floor.', rule: 'No borrowing to invest', conf: 0.88, horizon: '30 days', expires: 'Nov 21', lights: ['ok', 'ok', 'ok', 'ok', 'ok', 'ok'] },
    { id: 'p5', desk: 'me', deskName: 'Your draft', kind: 'buy', title: 'Buy $1,000 AAPL on margin', symbol: 'AAPL', account: 'Individual', amount: 1000, funding: 'margin', why: 'Drafted from the Symbol sheet. Margin funding and the satellite cap both light up.', rule: 'None', conf: null, horizon: '90 days', expires: 'Nov 12', lights: ['act', 'watch', 'act', 'ok', 'ok', 'act'] },
  ];
  const PREFLIGHT = ['Concentration', 'Drift after', 'Funding', 'Wash sales', 'Lots and tax', 'Plan rules'];

  // ---------- decision journal ----------
  const JOURNAL = [
    { day: 'Nov 4', items: [{ kind: 'deposit_route', sym: 'FSKAX', amt: 1400, origin: 'Plan keeper', status: 'Followed plan', s30: null }, { kind: 'deposit_route', sym: 'FTIHX', amt: 600, origin: 'Plan keeper', status: 'Followed plan', s30: null }] },
    { day: 'Oct 28', items: [{ kind: 'buy', sym: 'UFO', amt: 400, origin: 'You', status: 'Override', reason: 'Launch week, wanted a bit more', s30: -18 }] },
    { day: 'Oct 21', items: [{ kind: 'deposit_route', sym: 'FSKAX', amt: 2000, origin: 'Plan keeper', status: 'Followed plan', s30: 0 }, { kind: 'trim', sym: 'FTEC', amt: 600, origin: 'Risk desk', status: 'Passed', reason: 'Inside the band, let it ride', s30: 12 }] },
    { day: 'Oct 7', items: [{ kind: 'harvest', sym: 'RIVN', amt: 420, origin: 'Tax desk', status: 'Dismissed', reason: 'Waiting for earnings', s30: -31 }] },
    { day: 'Sep 23', items: [{ kind: 'deposit_route', sym: 'FSKAX', amt: 2000, origin: 'Plan keeper', status: 'Followed plan', s30: 0 }, { kind: 'buy', sym: 'AAPL', amt: 500, origin: 'You', status: 'Override', reason: 'Dip after the event', s30: 41 }] },
  ];

  const SCORE = [
    { who: 'Plan keeper', n: 14, d30: 4, d90: 12, hit: 0.57, brier: 0.21, usage: 38 },
    { who: 'Tax desk', n: 6, d30: 96, d90: 210, hit: 0.67, brier: 0.18, usage: 22 },
    { who: 'Risk desk', n: 5, d30: 18, d90: 35, hit: 0.6, brier: 0.24, usage: 19 },
    { who: 'Research desk', n: 7, d30: -22, d90: -60, hit: 0.43, brier: 0.29, usage: 61 },
    { who: 'Scout', n: 2, d30: -9, d90: null, hit: 0.5, brier: null, usage: 12 },
    { who: 'You', n: 11, d30: -46, d90: -140, hit: 0.45, brier: null, usage: 0 },
  ];

  const ALERTS = [
    { tone: 'watch', icon: 'gauge', title: 'Satellite is 2.4 points past its 10% cap', sub: 'New buys there light up in Preflight' },
    { tone: 'info', icon: 'calendar', title: 'RIVN wash-sale window closes Dec 10', sub: 'Any account, including the HSA' },
    { tone: 'act', icon: 'bolt', title: 'AAPL reports earnings tomorrow after close', sub: 'Average move on the last 8 reports: 4.1%' },
    { tone: 'ok', icon: 'check', title: 'Mirror pulled at 8:00 AM, prices live', sub: 'Lot export from Nov 1' },
  ];

  const EVENTS = [
    { m: 'Nov', d: 8, title: 'AAPL earnings', sub: 'After close', sym: 'AAPL' },
    { m: 'Nov', d: 18, title: 'Deposit $2,000', sub: 'Plan keeper split ready', sym: 'FSKAX' },
    { m: 'Dec', d: 10, title: 'RIVN wash window closes', sub: 'If the harvest goes through Nov 10', sym: 'RIVN' },
    { m: 'Dec', d: 19, title: 'FTEC distribution', sub: 'Estimated, last year $0.41', sym: 'FTEC' },
    { m: 'Dec', d: 31, title: 'Last day to harvest', sub: 'Trade date counts', sym: null },
  ];

  const DOSSIERS = [
    { sym: 'FTEC', title: 'FTEC · Tech tilt', verdict: 'Hold in band', tone: 'ok', updated: 'Nov 5', sources: 9 },
    { sym: 'UFO', title: 'UFO · Space', verdict: 'Cap reached', tone: 'watch', updated: 'Nov 6', sources: 12 },
    { sym: 'RIVN', title: 'RIVN · EV maker', verdict: 'Harvest candidate', tone: 'watch', updated: 'Oct 30', sources: 11 },
    { sym: 'AAPL', title: 'AAPL · Apple', verdict: 'Hold, no adds', tone: 'ok', updated: 'Oct 22', sources: 8 },
    { sym: 'SMR', title: 'Theme · Nuclear', verdict: 'Watching', tone: 'info', updated: 'Oct 18', sources: 14 },
    { sym: 'FSKAX', title: 'FSKAX · US core', verdict: 'Plan fund', tone: 'ok', updated: 'Sep 30', sources: 4 },
  ];

  window.DATA = { SYM, H, PLAN, CASH, MARGIN, MARGIN_RATE, total, invested, days, port, planShadow, spyShadow, LOTS, PROPOSALS, PREFLIGHT, JOURNAL, SCORE, ALERTS, EVENTS, DOSSIERS, rng, gauss };
})();
