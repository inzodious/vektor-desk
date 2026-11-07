import { useCallback, useEffect, useRef, useState } from 'react';

export class ApiError extends Error {
  constructor(status, message) {
    super(message);
    this.status = status;
  }
}

function withScenario(path) {
  try {
    const scenario = new URLSearchParams(window.location.search).get('scenario');
    if (!scenario) return path;
    return `${path}${path.includes('?') ? '&' : '?'}scenario=${encodeURIComponent(scenario)}`;
  } catch {
    return path;
  }
}

export async function getJson(path, { signal } = {}) {
  let res;
  try {
    res = await fetch(withScenario(path), { signal, headers: { Accept: 'application/json' }, cache: 'no-store' });
  } catch (e) {
    if (e.name === 'AbortError') throw e;
    throw new ApiError(0, 'offline');
  }
  if (!res.ok) throw new ApiError(res.status, `HTTP ${res.status}`);
  try {
    return await res.json();
  } catch {
    throw new ApiError(res.status, 'bad json');
  }
}

export function useApi(path, { every } = {}) {
  const [state, setState] = useState({ data: null, error: null, loading: true });
  const [nonce, setNonce] = useState(0);
  const first = useRef(true);
  const reload = useCallback(() => setNonce((n) => n + 1), []);

  useEffect(() => {
    const ctl = new AbortController();
    if (!first.current) setState((s) => ({ ...s, loading: true }));
    first.current = false;
    getJson(path, { signal: ctl.signal })
      .then((data) => setState({ data, error: null, loading: false }))
      .catch((error) => {
        if (error.name !== 'AbortError') setState((s) => ({ data: s.data, error, loading: false }));
      });
    return () => ctl.abort();
  }, [path, nonce]);

  const ms = typeof every === 'function' ? every(state.data) : every;
  useEffect(() => {
    if (!ms) return undefined;
    const id = setInterval(reload, ms);
    return () => clearInterval(id);
  }, [ms, reload]);

  return { ...state, reload };
}

export async function postJson(path, body = {}, { method = 'POST' } = {}) {
  let res;
  try {
    res = await fetch(path, { method, headers: { Accept: 'application/json', 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  } catch {
    throw new ApiError(0, "The desk API didn't answer. Try again in a moment.");
  }
  const data = await res.json().catch(() => null);
  if (!res.ok) {
    const msg = typeof data?.detail === 'string' ? data.detail : typeof data?.error === 'string' ? data.error : `The desk API answered ${res.status}.`;
    throw new ApiError(res.status, msg);
  }
  return data;
}
