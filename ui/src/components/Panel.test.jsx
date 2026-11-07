import { useState } from 'react';
import { describe, expect, it } from 'vitest';
import { act, fireEvent, render, screen } from '@testing-library/react';
import { Panel } from './Panel.jsx';
import { Combo } from './Combo.jsx';

function Harness() {
  const [open, setOpen] = useState(true);
  return (
    <>
      <button type="button" onClick={() => setOpen(true)}>
        open
      </button>
      <Panel open={open} onClose={() => setOpen(false)} title="Mirror tables">
        <Combo label="Pick" options={['a', 'b']} value="a" />
      </Panel>
    </>
  );
}

describe('Panel', () => {
  it('closes on Escape', () => {
    render(<Harness />);
    expect(screen.getByRole('dialog', { name: 'Mirror tables' })).toBeInTheDocument();
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it('closes on an outside click', () => {
    render(<Harness />);
    fireEvent.click(screen.getByTestId('scrim'));
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it('lets Escape close an inner combo first', async () => {
    render(<Harness />);
    const combo = screen.getByRole('button', { name: /pick/i });
    await act(async () => fireEvent.click(combo));
    expect(combo).toHaveAttribute('aria-expanded', 'true');
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(combo).toHaveAttribute('aria-expanded', 'false');
    expect(screen.getByRole('dialog')).toBeInTheDocument();
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(screen.queryByRole('dialog')).toBeNull();
  });
});
