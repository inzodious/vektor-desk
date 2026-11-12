import { describe, expect, it } from 'vitest';
import queue from '../fixtures/decisions.queue.snoozed.json';
import cleared from '../fixtures/decisions.cleared.json';
import { snoozedRows, successorLine } from './queue.js';

const NOW = new Date('2026-11-09T16:42:00Z');

describe('snoozed proposals', () => {
  it('lists each with its reason and when it comes back', () => {
    const rows = snoozedRows(queue, NOW);
    expect(rows).toHaveLength(queue.snoozed);
    expect(rows[0]).toEqual({ id: queue.snoozed_items[0].id, title: 'Trim $150 FTEC', why: 'Waiting for Friday’s deposit.', who: 'Plan keeper', back: 'back Tue Nov 10, 9:30 AM ET' });
    expect(rows[1].why).toBe('Carries the snooze from the proposal it replaced.');
  });

  it('reads an older desk and odd rows as nothing', () => {
    expect(snoozedRows({ count: 1, snoozed: 2, items: [] })).toEqual([]);
    expect(snoozedRows(null)).toEqual([]);
    expect(snoozedRows({ snoozed_items: [null, { id: 'a', snoozed_until: 'soon', status_reason: '{"x":1}' }] }, NOW)).toEqual([{ id: 'a', title: 'Untitled proposal', why: null, who: 'Unknown', back: null }]);
    expect(snoozedRows({ snoozed_items: [{ id: 'a', snoozed_until: '2026-11-09T20:00:00Z' }] }, NOW)[0].back).toBe('back today, 3:00 PM ET');
  });
});

describe('what became of a replaced proposal', () => {
  it('says nothing for a row that was not replaced', () => {
    expect(successorLine(cleared.items.find((d) => d.check === 'plan'))).toBeNull();
    expect(successorLine({})).toBeNull();
    expect(successorLine({ successor: 'x' })).toBeNull();
  });

  it('points at the one that is still open', () => {
    const open = cleared.items.find((d) => d.successor?.open);
    expect(successorLine(open)).toEqual({ open: true, id: open.successor.id, text: 'The latest one, “Buy $400 ACME”, is waiting in your queue.' });
    expect(successorLine({ successor: { id: 'b', title: 'Trim FTEC', status: 'snoozed', open: true } }).text).toBe('The latest one, “Trim FTEC”, is snoozed.');
    expect(successorLine({ successor: { id: 'b', status: 'proposed', open: true } }).text).toBe('The latest one is waiting in your queue.');
  });

  it('says why when the chain ended with nothing', () => {
    const gone = cleared.items.find((d) => d.successor && !d.successor.open);
    expect(successorLine(gone)).toEqual({ open: false, id: gone.successor.id, text: 'The latest one, “Buy $300 ACME”, has left the queue too. ACME is at $23.50, above the $18.00 to $22.00 zone this was written for.' });
    expect(successorLine({ successor: { title: 'Buy $50 BND', status: 'approved', status_reason: 'fine', open: false } }).text).toBe('You approved the latest one, “Buy $50 BND”.');
    expect(successorLine({ successor: { title: 'Buy $50 BND', status: 'passed', open: false } }).text).toBe('You passed on the latest one, “Buy $50 BND”.');
    expect(successorLine({ successor: { status: 'expired', status_reason: '{"raw":1}', open: false } }).text).toBe('The latest one has left the queue too.');
  });
});
