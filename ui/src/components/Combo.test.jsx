import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { Combo } from './Combo.jsx';

const OPTS = [
  { v: 'light', t: 'Light' },
  { v: 'dark', t: 'Graphite dark' },
  { v: 'x', t: 'Off option', off: true },
];

function setup(onChange = vi.fn()) {
  render(
    <div>
      <p>outside</p>
      <Combo label="Theme" options={OPTS} value="light" onChange={onChange} />
    </div>,
  );
  return { button: screen.getByRole('button', { name: /theme/i }), onChange };
}

describe('Combo', () => {
  it('opens, picks and closes', () => {
    const { button, onChange } = setup();
    fireEvent.click(button);
    expect(button).toHaveAttribute('aria-expanded', 'true');
    fireEvent.click(screen.getByRole('option', { name: 'Graphite dark' }));
    expect(onChange).toHaveBeenCalledWith('dark');
    expect(button).toHaveAttribute('aria-expanded', 'false');
  });

  it('closes on Escape', () => {
    const { button } = setup();
    fireEvent.click(button);
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(button).toHaveAttribute('aria-expanded', 'false');
  });

  it('closes on an outside click', () => {
    const { button } = setup();
    fireEvent.click(button);
    fireEvent.pointerDown(screen.getByText('outside'));
    expect(button).toHaveAttribute('aria-expanded', 'false');
  });

  it('skips disabled options with the keyboard', () => {
    const { button, onChange } = setup();
    fireEvent.keyDown(button, { key: 'ArrowDown' });
    fireEvent.keyDown(button, { key: 'ArrowDown' });
    fireEvent.keyDown(button, { key: 'ArrowDown' });
    fireEvent.keyDown(button, { key: 'Enter' });
    expect(onChange).not.toHaveBeenCalled();
    fireEvent.keyDown(button, { key: 'ArrowDown' });
    fireEvent.keyDown(button, { key: 'ArrowDown' });
    fireEvent.keyDown(button, { key: 'Enter' });
    expect(onChange).toHaveBeenCalledWith('dark');
  });
});
