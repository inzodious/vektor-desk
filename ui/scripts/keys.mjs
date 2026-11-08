const at = (hm, day = '2026-11-09') => `${day}T${hm}:00Z`;
const SET = ['CLAUDE_CODE_OAUTH_TOKEN', 'DESK_CLAUDE_TOKEN_EXPIRES', 'TIINGO_API_KEY', 'FRED_API_KEY', 'DESK_SEC_USER_AGENT', 'ALPACA_API_KEY_ID', 'ALPACA_API_SECRET_KEY', 'DESK_FIREBASE_PROJECT', 'DESK_UID', 'PORKBUN_API_KEY', 'PORKBUN_API_SECRET_KEY'];

// ---------- keys: most set, box quiet, first day ----------
export function keysFixtures(api) {
  const base = { ...api, now: at('16:42'), host_alive: true, ready: true };
  const keys = api.keys.map((k) => {
    const row = { ...k, set: SET.includes(k.name), pending: false, last: null };
    if (k.name === 'TIINGO_API_KEY') row.last = { name: k.name, request_id: 'k1', result: 'saved', message: 'Saved to desk.env', at: at('14:00') };
    if (k.name === 'FINNHUB_API_KEY') row.pending = true;
    if (k.name === 'TS_AUTHKEY') row.last = { name: k.name, request_id: 'k2', result: 'refused', message: 'That value has a line break.', at: at('13:10') };
    return row;
  });
  const blank = api.keys.map((k) => ({ ...k, set: false, pending: false, last: null }));
  return {
    'box.keys': { ...base, keys },
    'box.keys.down': { ...base, host_alive: false, ready: false, keys: blank },
    'box.keys.fresh': { ...base, host_alive: false, ready: false, keys: blank },
  };
}
