import { describe, expect, it } from 'vitest';
import risk from '../fixtures/decisions.risk.json';
import versions from '../fixtures/decisions.risk.versions.json';
import { answeredCount, bandFacts, bandRows, byPart, limitText, riskRefusal, savedText, startAnswers, worstDollars } from './risk.js';

describe('risk check', () => {
  it('groups the eight questions by part', () => {
    const parts = byPart(risk.questions);
    expect(parts.map((p) => p.questions.length)).toEqual([5, 3]);
    expect(parts[0].title).toBe('How you feel about risk');
  });

  it('starts from the last answers and counts what is left', () => {
    const a = startAnswers(risk.questions, versions.versions);
    expect(answeredCount(risk.questions, a)).toBe(8);
    expect(answeredCount(risk.questions, {})).toBe(0);
    expect(startAnswers(risk.questions, [])).toEqual({});
  });

  it('words bands and what holds you there', () => {
    const rows = bandRows(risk.bands);
    expect(rows.map((r) => r.n)).toEqual([1, 2, 3, 4, 5]);
    expect(bandFacts(rows[3])).toEqual([
      { k: 'Stocks', v: '75–90%' },
      { k: 'Speculative', v: 'up to 10%' },
      { k: 'One stock', v: 'up to 10%' },
      { k: 'Worst year', v: '−33%' },
    ]);
    expect(bandFacts(rows[0])[1].v).toBe('none');
    expect(limitText({ band: 4, tolerance_band: 5, capacity_band: 4, limited_by: 'capacity' })).toBe('Your nerve says band 5; your timeline and cushion hold it at 4.');
    expect(limitText({ band: 3, tolerance_band: 3, capacity_band: 5, limited_by: 'tolerance' })).toBe('Your timeline could carry band 5; your comfort sets it at 3.');
    expect(limitText({ band: 4, limited_by: 'both' })).toBe('Your nerve and your timeline agree on band 4.');
    expect(worstDollars(rows[3], 16393)).toBe(5400);
  });

  it('words saves and refusals', () => {
    expect(savedText({ changed: true, result: { band: 4, label: 'Moderately aggressive' } })).toBe('Saved. You’re band 4, Moderately aggressive.');
    expect(savedText({ changed: false })).toMatch(/nothing changed/);
    expect(riskRefusal({ status: 422, message: 'goal is not answered' })).toBe('A few questions still need an answer.');
    expect(riskRefusal({ status: 404 })).toMatch(/next desk update/);
  });
});
