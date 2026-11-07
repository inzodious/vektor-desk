import { afterEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import Settings from './Settings.jsx';
import ok from '../fixtures/status.json';
import stale from '../fixtures/status.stale.json';
import failing from '../fixtures/status.failing.json';
import empty from '../fixtures/status.empty.json';
import health from '../fixtures/health.json';

function serve(status, code = 200) {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url) => {
      if (String(url).startsWith('/api/health')) return new Response(JSON.stringify(health), { status: 200 });
      if (code !== 200) return new Response('{}', { status: code });
      return new Response(JSON.stringify(status), { status: 200 });
    }),
  );
}

const page = () =>
  render(
    <MemoryRouter>
      <Settings />
    </MemoryRouter>,
  );

afterEach(() => vi.unstubAllGlobals());

describe('Settings', () => {
  it('shows a fresh desk', async () => {
    serve(ok);
    page();
    expect(await screen.findByText('All fresh')).toBeInTheDocument();
    expect(screen.getByText(/Last good pull Nov 9, 8:00 AM ET · 3.7 hours ago/)).toBeInTheDocument();
    expect(screen.getByText('359 days')).toBeInTheDocument();
    expect(screen.getByText('Good to Nov 3, 2027')).toBeInTheDocument();
    expect(screen.getByText('3f9c2ab')).toBeInTheDocument();
    expect(screen.getByText('Idle')).toBeInTheDocument();
  });

  it('flags a stale mirror, a token to renew and a running job', async () => {
    serve(stale);
    page();
    expect(await screen.findByText('2 to look at')).toBeInTheDocument();
    expect(screen.getByText('Stale')).toBeInTheDocument();
    expect(screen.getByText('Renew soon')).toBeInTheDocument();
    expect(screen.getByText('Mirror pull')).toBeInTheDocument();
  });

  it('explains a failing pull and an expired token', async () => {
    serve(failing);
    page();
    expect(await screen.findByText(/Firestore read timed out/)).toBeInTheDocument();
    expect(screen.getByText('8 days over')).toBeInTheDocument();
    expect(screen.getByText(/Desks stay paused/)).toBeInTheDocument();
  });

  it('handles a desk that has never pulled', async () => {
    serve(empty);
    page();
    expect(await screen.findByText("The mirror hasn't run yet.")).toBeInTheDocument();
    expect(screen.getByText('Not set')).toBeInTheDocument();
    expect(screen.getByTestId('mirror-row')).toBeDisabled();
  });

  it('says so when the API does not answer', async () => {
    serve(null, 502);
    page();
    expect(await screen.findByText("The desk API didn't answer")).toBeInTheDocument();
    expect(screen.getByText(/replied with 502/)).toBeInTheDocument();
  });

  it('opens the mirror tables drawer and closes it with Escape', async () => {
    serve(ok);
    page();
    fireEvent.click(await screen.findByTestId('mirror-row'));
    expect(screen.getByRole('dialog', { name: 'Mirror tables' })).toBeInTheDocument();
    expect(screen.getByText('transactions')).toBeInTheDocument();
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(screen.queryByRole('dialog')).toBeNull();
  });
});
