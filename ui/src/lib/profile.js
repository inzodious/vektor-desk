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
  return 'desk.yaml';
}

export function defaultsText(p) {
  const list = (p?.defaults || []).map(keyWord);
  if (!list.length) return 'Everything is set in desk.yaml.';
  if (p?.set?.length === 0) return 'Every setting is still the default.';
  return null;
}
