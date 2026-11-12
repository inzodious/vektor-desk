import { describe, expect, it } from 'vitest';
import calm from '../fixtures/memory.json';
import low from '../fixtures/memory.low.json';
import blind from '../fixtures/memory.blind.json';
import started from '../fixtures/start.low.json';
import { memoryStrip, memoryView, modeChoices, modeLine, modeRefusal, pausedLine, size } from './memory.js';

const NOW = new Date('2026-11-09T22:41:00Z');

describe('memory', () => {
  it('writes sizes the way the desk does', () => {
    expect(size(512)).toBe('512 MB');
    expect(size(1500)).toBe('1.5 GB');
    expect(size(15360)).toBe('15.0 GB');
    expect(size(null)).toBeNull();
  });

  it('shows nothing when the desk does not serve memory', () => {
    expect(memoryView(null)).toBeNull();
    expect(memoryView({ detail: 'Not Found' })).toBeNull();
  });

  it('reads a calm box', () => {
    const v = memoryView(calm, NOW);
    expect(v).toMatchObject({ state: 'ok', head: '6.0 GB free of 15.0 GB', used: 0.6, low: { on: false, mode: 'auto' }, paused: null, waiting: [], killed: [], hostSeen: true });
    expect(v.chip).toEqual({ t: 'Enough room', tone: '' });
    expect(v.line).toBe('Off right now. It switches itself on under 1.5 GB free.');
    expect(v.facts.map((f) => `${f.k}: ${f.v}`)).toEqual(['Swap: None', 'File cache: 2.0 GB', 'Scheduler: 180 MB of 640 MB']);
  });

  it('reads a box that is short on memory', () => {
    const v = memoryView(low, NOW);
    expect(v).toMatchObject({ state: 'tight', head: '512 MB free of 15.0 GB', low: { on: true, mode: 'auto' } });
    expect(v.chip.tone).toBe('watch');
    expect(v.line).toBe('On right now. The box has 512 MB free, under the 1.5 GB floor.');
    expect(v.paused).toBeNull();
    expect(v.waiting).toEqual([{ job: 'engine-review', title: 'Results review', since: '5:35 PM' }]);
    expect(v.killed).toHaveLength(3);
    expect(v.killed[0]).toMatchObject({ when: '2:03 PM', scope: 'cap', words: 'Agents run debrief was stopped: it needed more memory than the scheduler is allowed.' });
    expect(v.killed[2].when).toBe('Nov 8, 12:20 PM');
  });

  it('says so when memory cannot be read', () => {
    const v = memoryView(blind, NOW);
    expect(v).toMatchObject({ state: 'unknown', head: 'The box’s memory can’t be read from here', used: null, facts: [], hostSeen: false });
    expect(v.killed).toHaveLength(1);
  });

  it('words the three choices and what is true now', () => {
    expect(modeChoices(low.low_memory).map((c) => c.title)).toEqual(['Automatic', 'On', 'Off']);
    expect(modeChoices(low.low_memory)[0].blurb).toBe('On under 1.5 GB free, off again above 3.9 GB');
    expect(modeLine({ on: true, mode: 'on', why: 'You switched it on.' }, 'ok')).toBe('On right now. You switched it on.');
    expect(modeLine({ on: false, mode: 'off' }, 'tight')).toMatch(/^Off, and the box is tight on memory/);
    expect(modeLine({ on: false, mode: 'off' }, 'ok')).toBe('Off. Everything runs side by side.');
    expect(pausedLine({ on: false, paused: ['lab'] })).toBeNull();
    expect(pausedLine({ on: true, paused: [] })).toBeNull();
    expect(pausedLine({ on: true, paused: ['lab'] })).toBe('Paused until it is off: the strategy lab.');
    expect(pausedLine({ on: true, paused: ['lab', 'eval'] })).toBe('Paused until it is off: the strategy lab and the eval session.');
  });

  it('explains a refused switch', () => {
    expect(modeRefusal({ status: 422, body: { error: 'bad_mode', message: 'Mode is auto, on or off.' } })).toBe('Mode is auto, on or off.');
    expect(modeRefusal({ status: 404, body: null })).toBe('This switch arrives with the next desk update.');
    expect(modeRefusal({ message: 'offline' })).toBe('offline');
  });

  it('keeps the strip to one line, and only when there is something to say', () => {
    expect(memoryStrip(null)).toBeNull();
    expect(memoryStrip({ state: 'ok', low_memory: false, killed: 0, note: 'fine' })).toBeNull();
    expect(memoryStrip({ low_memory: true, killed: 0, note: 'Low-memory mode is on.' })).toBeNull();
    expect(memoryStrip(started.memory)).toMatchObject({ key: '0:3', tone: 'watch', head: 'The box ran short on memory', to: '/settings/box#memory' });
    expect(memoryStrip(started.memory).line).toBe('3 things were stopped for memory in the last two days.');
    expect(memoryStrip({ low_memory: false, killed: 1 }).line).toBe('One thing was stopped for memory in the last two days.');
  });

  it('speaks up about a wait only once a job has waited five minutes', () => {
    const calm = { low_memory: true, killed: 0 };
    const waiting = (since) => ({ waiting: [{ job: 'engine-review', title: 'Engine review', since }] });
    expect(memoryStrip(calm, waiting('2026-11-09T22:38:00Z'), NOW)).toBeNull();
    expect(memoryStrip(calm, waiting('2026-11-09T22:29:00Z'), NOW)).toMatchObject({ key: '2026-11-09T22:29:00Z:0', tone: 'info', head: 'A job is waiting on memory', line: 'Results review has waited 12 minutes for its turn.' });
    expect(memoryStrip({ low_memory: true, killed: 2 }, waiting('2026-11-09T22:29:00Z'), NOW).line).toBe('Results review has waited 12 minutes for its turn. 2 things were stopped for memory in the last two days.');
  });
});
