import { PATHS } from './icons.js';

export function Icon({ name, size, className }) {
  const style = size ? { width: size, height: size } : undefined;
  return (
    <svg className={className} style={style} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" dangerouslySetInnerHTML={{ __html: PATHS[name] || PATHS.star }} />
  );
}

const ROBOT = '<path d="M20 4v5" stroke="currentColor" stroke-width="2" stroke-linecap="round"/><circle cx="20" cy="4" r="2.4" fill="var(--coral)"/><rect x="7" y="10" width="26" height="20" rx="7" fill="var(--mustard)" stroke="var(--ink)" stroke-width="2"/><rect x="11.5" y="15" width="17" height="9" rx="4" fill="var(--board)"/><circle cx="16.5" cy="19.5" r="2" fill="var(--mint)"/><circle cx="23.5" cy="19.5" r="2" fill="var(--mint)"/><path d="M4 18v6M36 18v6" stroke="var(--ink)" stroke-width="2.4" stroke-linecap="round"/><path d="M14 30v4h12v-4" fill="none" stroke="var(--ink)" stroke-width="2"/>';

export function Robot({ size = 24 }) {
  return <svg viewBox="0 0 40 40" style={{ width: size, height: size }} aria-hidden="true" dangerouslySetInnerHTML={{ __html: ROBOT }} />;
}
