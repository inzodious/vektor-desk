import { describe, expect, it } from 'vitest';
import index from '../fixtures/engine.reviews.index.json';
import day from '../fixtures/engine.reviews.day.json';
import week from '../fixtures/engine.reviews.week.json';
import month from '../fixtures/engine.reviews.month.json';
import year from '../fixtures/engine.reviews.year.json';
import fresh from '../fixtures/engine.reviews.fresh.json';
import freshIndex from '../fixtures/engine.reviews.index.fresh.json';
import {
  accountName,
  bandLine,
  changeText,
  cleanKind,
  debriefState,
  decisionRows,
  diffText,
  eventWord,
  firstRunNote,
  gainLine,
  kpis,
  ledger,
  moverLine,
  moverRows,
  rewritePath,
  periodPath,
  riskFacts,
  scoreLine,
  stateChip,
  stepper,
  versusLine,
  versusRows,
  versusScale,
} from './results.js';

describe('results', () => {
  it('steps through the periods the index lists', () => {
    const rows = index.kinds.day;
    const latest = stepper(index, 'day', null);
    expect(latest).toMatchObject({ at: 0, latest: true, newer: null });
    expect(latest.older.end).toBe(rows[1].end);
    const back = stepper(index, 'day', rows[1].end);
    expect(back).toMatchObject({ at: 1, latest: false });
    expect(back.newer.end).toBe(rows[0].end);
    expect(stepper(index, 'day', '1999-01-01').at).toBe(0);
    expect(stepper(freshIndex, 'day', null)).toMatchObject({ at: -1, current: null });
    expect(periodPath('day', rows[1], rows[0])).toBe(`/results/day?end=${rows[1].end}`);
    expect(periodPath('week', index.kinds.week[0], index.kinds.week[0])).toBe('/results/week');
    expect(cleanKind('decade')).toBe('day');
  });

  it('says whether a period is open, restatable or final', () => {
    expect(stateChip(month).t).toBe('So far');
    expect(stateChip(day).t).toBe('May restate once');
    expect(stateChip({ closed: true, final: true }).t).toBe('Final');
    expect(stateChip(null)).toBeNull();
  });

  it('words the change and where it came from', () => {
    expect(changeText(week.pack.value)).toEqual({ usd: '+$933', pct: '+2.09%', tone: 'up' });
    expect(changeText({ change_usd: -12.4, change_pct: -0.2 })).toEqual({ usd: '−$12', pct: '−0.20%', tone: 'dn' });
    expect(changeText(null).usd).toBe('—');
    expect(gainLine(week.pack.value)).toBe('+$333 from the market, +$600 you put in');
    expect(gainLine(day.pack.value)).toBe('All of it from the market: +$53');
    expect(gainLine({ gain_usd: 10, net_flows: -200 })).toBe('+$10 from the market, −$200 you took out');
  });

  it('builds the numbers strip', () => {
    const ids = kpis(week.pack).map((k) => k.id);
    expect(ids).toEqual(['start', 'end', 'flows', 'gain', 'income', 'fi']);
    expect(kpis(week.pack).find((k) => k.id === 'flows')).toMatchObject({ value: '+$600', sub: '2 moves' });
    const sold = kpis({ ...week.pack, fi: null, realized: { short_term: -40, long_term: 120, total: 80, sales: 2 } });
    expect(sold.find((k) => k.id === 'realized')).toMatchObject({ value: '+$80', tone: 'up', sub: '−$40 short, +$120 long' });
    expect(kpis(null)).toEqual([]);
  });

  it('lines you up against the S&P 500 and each mix', () => {
    const rows = versusRows(week.pack);
    expect(rows[0]).toMatchObject({ id: 'you', return_pct: week.pack.value.change_pct });
    expect(rows.map((r) => r.id)).toEqual(['you', 'spy', 'safe-mix', 'as-held', 'tech-tilt']);
    expect(versusLine(week.pack)).toBe('0.34 pts behind the S&P 500');
    expect(versusLine(day.pack)).toBe('0.19 pts ahead of the S&P 500');
    expect(versusLine({ vs: [] })).toBeNull();
    expect(diffText(rows[1])).toBe('You’re $51 behind');
    expect(diffText(rows[2])).toBe('You’re $131 ahead');
    expect(diffText(rows[0])).toBe('');
    expect(diffText({ kind: 'mix', diff_usd: 0.2 })).toBe('Level with you');
  });

  it('scales the bars from zero, both ways when signs differ', () => {
    const up = versusScale([{ return_pct: 2 }, { return_pct: 1 }]);
    expect(up.zero).toBe(0);
    expect(up.width(1)).toBe(50);
    const mixed = versusScale([{ return_pct: 1 }, { return_pct: -3 }]);
    expect(mixed.zero).toBe(75);
    expect(mixed.width(-3)).toBe(75);
  });

  it('ranks what moved the period', () => {
    const rows = moverRows(week.pack.movers);
    expect(rows.map((r) => r.symbol)).toEqual(['FXAIX', 'ACME', 'VXUS', 'FTEC', 'BND']);
    expect(rows[0]).toMatchObject({ tone: 'up', share: 100 });
    expect(rows[2].tone).toBe('dn');
    expect(moverLine(rows[0])).toBe('+4.7% itself · 58.8% of the portfolio');
    const other = moverRows({ up: [], down: [], other_usd: 12 });
    expect(other).toHaveLength(1);
    expect(other[0]).toMatchObject({ symbol: null, tone: 'up' });
    expect(moverRows(null)).toEqual([]);
  });

  it('merges cash moves and trades into one ledger, newest first', () => {
    const rows = ledger(week.pack);
    expect(rows).toHaveLength(10);
    expect(rows[0]).toMatchObject({ type: 'flow', title: 'Deposit', amount: 100 });
    expect(rows[2]).toMatchObject({ type: 'buy', title: 'Bought', symbol: 'BND', detail: '0.064 sh at $77.56' });
    expect(ledger({ flows: [], trades: [{ date: '2026-11-03', side: 'sell', symbol: 'ACME', shares: 2, price: 30, amount: 60 }] })[0]).toMatchObject({ title: 'Sold', type: 'sell' });
    expect(ledger(day.pack)).toEqual([]);
    expect(accountName('hsa-0002')).toBe('HSA');
    expect(accountName('individual-0001')).toBe('Individual');
  });

  it('keeps risk honest about a single day', () => {
    expect(riskFacts(day.pack)).toEqual([]);
    expect(riskFacts(week.pack).map((f) => f.id)).toEqual(['dd', 'vol', 'best', 'worst']);
    expect(bandLine(week.pack.risk.band)).toMatchObject({ chip: 'Band 4 · Moderately aggressive', fit: 'Calmer than your band', tone: 'info' });
    expect(bandLine(null)).toBeNull();
  });

  it('lists decisions made and scores that came due', () => {
    const { made, matured } = decisionRows(week.pack.decisions);
    expect(made).toHaveLength(3);
    expect(made[0]).toMatchObject({ who: 'Plan keeper', status: 'Placed' });
    expect(matured[0]).toMatchObject({ who: 'Risk desk', tone: 'up' });
    expect(scoreLine(matured[0])).toBe('90 days on: helped by $230');
    expect(scoreLine(matured[1])).toBe('90 days on: cost $89');
    expect(eventWord({ type: 'discount' })).toBe('Discount day');
    expect(eventWord({ type: 'guidance_cut' })).toBe('guidance cut');
  });

  it('knows what the debrief is waiting on', () => {
    expect(debriefState(week)).toEqual({ state: 'ok', hint: null });
    expect(debriefState(year)).toEqual({ state: 'stale', hint: 'Written before the final numbers. The rewrite is running late; the next try is tomorrow at 1:40 AM.' });
    const stale = (rewrite) => ({ ...day, debrief: { ...day.debrief, stale: true, rewrite } });
    expect(debriefState(stale(undefined))).toEqual({ state: 'rewriting', hint: null });
    expect(debriefState(stale(null))).toEqual({ state: 'rewriting', hint: null });
    expect(debriefState(stale({ state: 'due', due_at: '2026-11-09T22:46:00+00:00', words: null }))).toEqual({ state: 'rewriting', hint: null });
    expect(debriefState(stale({ state: 'failed', words: 'Written before the final numbers. The rewrite did not finish; the desk tries again at 5:46 PM.' })).hint).toBe('Written before the final numbers. The rewrite did not finish; the desk tries again at 5:46 PM.');
    expect(debriefState(stale({ state: 'late', words: null }))).toEqual({ state: 'stale', hint: 'Written before the final numbers.' });
    expect(debriefState({ ...day, debrief: { ...day.debrief, stale: false, rewrite: { state: 'failed', words: 'x' } } })).toEqual({ state: 'ok', hint: null });
  });

  it('asks the debrief desk only when the review does not say', () => {
    const { rewrite, ...bare } = day.debrief;
    const old = { ...day, debrief: { ...bare, stale: true } };
    expect(rewrite).toBeNull();
    expect(rewritePath(old)).toBe('/api/agents/debrief?kind=day&end=2026-11-06');
    expect(rewritePath({ ...old, debrief: { ...bare, stale: false } })).toBeNull();
    expect(rewritePath(year)).toBeNull();
    expect(rewritePath(month)).toBeNull();
    expect(debriefState(old, null)).toEqual({ state: 'rewriting', hint: null });
    expect(debriefState(old, { kind: 'day', end: '2026-11-06', stale: true, rewrite: { state: 'due', due_at: null, words: null } })).toEqual({ state: 'rewriting', hint: null });
    expect(debriefState(old, { rewrite: { state: 'late', due_at: null, words: 'Written before the final numbers. The Debrief desk is switched off, so it stays as written.' } })).toEqual({ state: 'stale', hint: 'Written before the final numbers. The Debrief desk is switched off, so it stays as written.' });
    expect(debriefState(year, { rewrite: null }).state).toBe('stale');
    expect(debriefState(month)).toMatchObject({ state: 'waiting', hint: 'The debrief lands when the month closes.' });
    expect(debriefState({ ...day, debrief: null }).hint).toBe('The debrief desk writes this up after its next run.');
    expect(debriefState(fresh).state).toBe('none');
    expect(firstRunNote(freshIndex, fresh)).toMatch(/first one runs after tonight/);
    expect(firstRunNote(null, null)).toMatch(/5:35 PM/);
  });
});
