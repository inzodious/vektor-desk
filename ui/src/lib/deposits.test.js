import { describe, expect, it } from 'vitest';
import { emptyText, moneyIn, ordinal, rhythmText, seenText } from './deposits.js';

describe('deposit words', () => {
  it('reads cadence and days plainly', () => {
    expect(ordinal(1)).toBe('1st');
    expect(ordinal(12)).toBe('12th');
    expect(ordinal(22)).toBe('22nd');
    expect(rhythmText({ amount_usd: 500, cadence: 'monthly', days: [1], account: 'individual-0001' })).toBe('$500 every month on the 1st to individual-0001');
    expect(rhythmText({ amount_usd: 50, cadence: 'semimonthly', days: [1, 15] })).toBe('$50 twice a month on the 1st and 15th');
    expect(rhythmText({ amount_usd: 500, cadence: 'biweekly', anchor: '2026-11-06' })).toBe('$500 every two weeks');
    expect(seenText({ observed: 6, last: '2026-11-02' })).toBe('seen 6 times, last Nov 2');
    expect(seenText({})).toBeNull();
  });

  it('says activity does the talking in auto mode', () => {
    expect(emptyText('auto')).toMatch(/read from your activity/);
    expect(emptyText('listed')).toMatch(/desk\.yaml/);
  });
});

describe('moneyIn', () => {
  const list = [
    { id: 'hsa', date: '2026-11-02', status: 'landed', amount_usd: 100, landed: { amount: 100 }, scheduled: true },
    { id: 'money-in-x', date: '2026-11-05', account: 'individual-0001', status: 'landed', amount_usd: 250, scheduled: false },
    { id: 'hsa', date: '2026-12-01', status: 'expected', amount_usd: 100, scheduled: true },
    { id: 'hsa', date: '2027-01-01', status: 'expected', amount_usd: 100, scheduled: true },
    { id: 'payday', date: '2026-10-20', status: 'late', amount_usd: 500, scheduled: true },
  ];

  it('orders late, the next expected per deposit, then recent landings', () => {
    expect(moneyIn(list).map((d) => `${d.status} ${d.label}`)).toEqual(['late payday', 'expected hsa', 'landed Money in', 'landed hsa']);
  });

  it('shows unscheduled money as landed with no due date', () => {
    const free = moneyIn(list).find((d) => !d.scheduled);
    expect(free).toMatchObject({ label: 'Money in', status: 'landed', amount: 250, when: 'Landed Nov 5 · individual-0001' });
  });

  it('never calls unscheduled money late', () => {
    expect(moneyIn([{ id: 'money-in-y', date: '2026-10-01', status: 'late', amount_usd: 90, scheduled: false }])).toEqual([]);
  });

  it('handles nothing', () => {
    expect(moneyIn(undefined)).toEqual([]);
  });
});
