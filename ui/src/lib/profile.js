const KEY_WORD = {
  risk_level: 'Risk level',
  'industry_focus.themes': 'Themes',
  'industry_focus.exclude': 'Exclusions',
  'opportunity.satellite_cap_pct': 'Single-stock cap',
  'opportunity.ideas_per_month': 'Ideas a month',
  'opportunity.min_confidence': 'Minimum confidence',
  'tax.harvest_threshold_usd': 'Harvest threshold',
  'tax.lot_method': 'Lot method',
  'tax.year_end_start': 'Year-end start',
  'tax.wash_sale_accounts': 'Wash-sale accounts',
  'margin.rate_pct': 'Margin rate',
  'growth.horizon_years': 'Horizon',
  'growth.tilt': 'Tilt',
  'growth.fi_target_from_plan': 'FI target from Escape Vektor',
  'usage.overnight_window': 'Overnight window',
  'usage.weekly_runs': 'Weekly runs',
  'agents.enabled': 'Desks on or off',
  'agents.desks': 'Which desks run',
  deposits: 'Deposit schedule',
  'alerts.min_priority': 'Alert level',
  rules: 'Rules',
};

export function keyWord(key) {
  if (KEY_WORD[key]) return KEY_WORD[key];
  const last = String(key || '').split('.').pop().replace(/_/g, ' ');
  return last.charAt(0).toUpperCase() + last.slice(1);
}

export function profileSource(p) {
  if (!p) return null;
  if (p.source === 'defaults' || !p.exists) return 'Built-in defaults';
  return 'Your profile';
}

export function defaultsText(p) {
  const list = (p?.defaults || []).map(keyWord);
  if (!list.length) return 'Everything is set in your profile.';
  if (p?.set?.length === 0) return 'Every setting is still the default.';
  return null;
}

export function marginWords(margin) {
  const rate = margin?.rate_pct;
  if (typeof rate !== 'number' || Number.isNaN(rate)) return null;
  const yours = margin.source === 'profile' || margin.source === 'env';
  return { rate: `${Number(rate.toFixed(3))}%`, yours, line: yours ? 'Your rate, a year' : 'A typical rate until you set your own' };
}

// ---------- first profile, from a button ----------
export const INIT_PATH = '/api/decisions/profile/init';
export const INIT_LABEL = 'Set up my profile from my data';

export function profileInit(p) {
  if (!p || p.exists) return null;
  const i = p.init && typeof p.init === 'object' ? p.init : null;
  if (!i && !p.starter) return null;
  const path = typeof i?.path === 'string' && i.path.startsWith('/api/') ? i.path : INIT_PATH;
  const label = typeof i?.label === 'string' && i.label.trim() ? i.label.trim() : INIT_LABEL;
  return { path, label };
}
