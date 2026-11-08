import { describe, expect, it } from 'vitest';
import status from '../fixtures/status.json';
import jobs from '../fixtures/jobs.json';
import jobsFresh from '../fixtures/jobs.fresh.json';
import health from '../fixtures/engine.health.json';
import healthFresh from '../fixtures/engine.health.fresh.json';
import profile from '../fixtures/decisions.profile.status.json';
import profileFresh from '../fixtures/decisions.profile.status.fresh.json';
import agents from '../fixtures/agents.status.json';
import agentsLifted from '../fixtures/agents.status.lifted.json';
import board from '../fixtures/engine.lab.leaderboard.json';
import boardEmpty from '../fixtures/engine.lab.leaderboard.empty.json';
import { countdown, firstRunScore, firstRunSteps } from './firstrun.js';

const api = (data) => ({ data, error: null, loading: false });
const states = (steps) => Object.fromEntries(steps.map((s) => [s.id, s.state]));

describe('first run', () => {
  it('ticks off what a running desk has done', () => {
    const steps = firstRunSteps({ status: api(status), jobs: api(jobs), health: api(health), profile: api(profile), agents: api(agents), board: api(board) });
    expect(states(steps)).toEqual({ mirror: 'done', token: 'done', backfill: 'done', daily: 'done', profile: 'done', lots: 'todo', research: 'done', crew: 'todo', race: 'done', risk: 'soon' });
    expect(firstRunScore(steps)).toMatchObject({ done: 7, total: 9, left: 2, next: { id: 'lots' } });
  });

  it('starts a fresh desk at the top', () => {
    const steps = firstRunSteps({ status: api({ ...status, mirror: { state: 'empty' }, claude_token: { state: 'unknown' } }), jobs: api(jobsFresh), health: api({ ...healthFresh, checks: [] }), profile: api(profileFresh), agents: api(agentsLifted), board: api(boardEmpty) });
    const score = firstRunScore(steps);
    expect(score.next.id).toBe('mirror');
    expect(states(steps)).toMatchObject({ mirror: 'todo', token: 'todo', backfill: 'todo', profile: 'todo', crew: 'done', race: 'todo' });
  });

  it('waits rather than guessing while the API answers', () => {
    const steps = firstRunSteps({ status: { data: null, loading: true } });
    expect(steps[0].state).toBe('loading');
    expect(firstRunScore(steps).done).toBe(0);
  });

  it('counts down to liftoff', () => {
    expect(countdown(3)).toBe('T-minus 3 steps');
    expect(countdown(1)).toBe('T-minus 1 step');
    expect(countdown(0)).toMatch(/^Liftoff/);
  });
});
