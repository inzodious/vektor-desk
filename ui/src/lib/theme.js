import { useCallback, useEffect, useState } from 'react';

const KEY = 'desk-theme';
const META = { light: '#f6eedc', dark: '#0d0e10' };

export function readTheme() {
  try {
    const q = new URLSearchParams(window.location.search).get('theme');
    if (q === 'dark' || q === 'light') return q;
    return window.localStorage.getItem(KEY) === 'dark' ? 'dark' : 'light';
  } catch {
    return 'light';
  }
}

export function applyTheme(theme, persist = true) {
  document.documentElement.classList.toggle('dark', theme === 'dark');
  document.querySelector('meta[name="theme-color"]')?.setAttribute('content', META[theme] || META.light);
  if (!persist) return;
  try {
    window.localStorage.setItem(KEY, theme);
  } catch {
    return;
  }
}

const listeners = new Set();
let current = typeof window === 'undefined' ? 'light' : readTheme();

export function useTheme() {
  const [theme, set] = useState(current);
  useEffect(() => {
    listeners.add(set);
    return () => {
      listeners.delete(set);
    };
  }, []);
  const setTheme = useCallback((next) => {
    current = next;
    applyTheme(next);
    listeners.forEach((fn) => fn(next));
  }, []);
  return [theme, setTheme];
}
