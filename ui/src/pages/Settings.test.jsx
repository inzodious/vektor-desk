import { afterEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import Settings from './Settings.jsx';
import ok from '../fixtures/status.json';
import stale from '../fixtures/status.stale.json';
import failing from '../fixtures/status.failing.json';
import empty from '../fixtures/status.empty.json';
import health from '../fixtures/health.json';
import crew from '../fixtures/agents.status.json';
import runs from '../fixtures/agents.runs.json';
import jobs from '../fixtures/jobs.json';

const busyJobs = { ...jobs, jobs: jobs.jobs.map((j) => (j.name === 'mirror' ? { ...j, running: true, running_since: '2026-11-09T16:40:00Z', can_run: false } : j)) };

function serve(status, code = 200, jobList = jobs) {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url) => {
      if (String(url).startsWith('/api/health')) return new Response(JSON.stringify(health), { status: 200 });
      if (String(url).startsWith('/api/agents/status')) return new Response(JSON.stringify(crew), { status: 200 });
      if (String(url).startsWith('/api/jobs')) return new Response(JSON.stringify(jobList), { status: 200 });
      if (String(url).startsWith('/api/agents/runs')) return new Response(JSON.stringify(runs), { status: 200 });
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
    expect(await screen.findByText('Scheduler on')).toBeInTheDocument();
    expect(screen.getByText('Daily numbers')).toBeInTheDocument();
  });

  it('flags a stale mirror, a token to renew and a running job', async () => {
    serve(stale, 200, busyJobs);
    page();
    expect(await screen.findByText('2 to look at')).toBeInTheDocument();
    expect(screen.getByText('Stale')).toBeInTheDocument();
    expect(screen.getByText('Renew soon')).toBeInTheDocument();
    expect(await screen.findByText('1 job running')).toBeInTheDocument();
    expect(screen.getByText(/^Running since/)).toBeInTheDocument();
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

  it('shows the crew with a switch per desk and weekly usage', async () => {
    serve(ok);
    page();
    expect(await screen.findByRole('switch', { name: 'All desks on' })).toBeInTheDocument();
    expect(screen.getByRole('switch', { name: 'Plan keeper on' })).toHaveAttribute('aria-checked', 'true');
    expect(screen.getAllByText('Ran fine').length).toBeGreaterThan(0);
    expect(screen.getAllByText('Not ready yet').length).toBeGreaterThan(0);
    expect(screen.getByRole('table', { name: /Runs this week/ })).toBeInTheDocument();
  });
});
