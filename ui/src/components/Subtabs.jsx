import { NavLink } from 'react-router-dom';

export function Subtabs({ label, tabs }) {
  return (
    <nav className="subtabs" aria-label={label}>
      {tabs.map((t) => (
        <NavLink key={t.to} to={t.to} end={t.end}>
          {t.label}
        </NavLink>
      ))}
    </nav>
  );
}
