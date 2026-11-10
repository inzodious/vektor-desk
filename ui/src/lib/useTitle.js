import { useEffect } from 'react';
import { useLocation } from 'react-router-dom';
import { AREAS } from './areas.js';

export function titleFor(pathname) {
  const area = AREAS.filter((a) => a.path !== '/').find((a) => pathname === a.path || pathname.startsWith(`${a.path}/`));
  if (area) return `${area.title} · Vektor Desk`;
  if (pathname === '/results' || pathname.startsWith('/results/')) return 'Results · Vektor Desk';
  return pathname === '/' ? 'Bridge · Vektor Desk' : 'Vektor Desk';
}

export function useTitle() {
  const { pathname } = useLocation();
  useEffect(() => {
    document.title = titleFor(pathname);
    window.scrollTo(0, 0);
  }, [pathname]);
}
