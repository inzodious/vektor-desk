import { describe, expect, it } from 'vitest';
import d from '../fixtures/agents.moves.json';
import { bigMoves, chipRows, confidenceWords, moveChip, moveHead, quietMoves } from './moves.js';

describe('why it moved', () => {
  it('puts big moves first and keeps quiet ones for the fold', () => {
    expect(bigMoves(d).map((r) => r.symbol)).toEqual(['ACME', 'NOVA']);
    expect(quietMoves(d).every((r) => r.label !== 'due')).toBe(true);
    expect(chipRows(d).map((r) => r.symbol)).toEqual(['ACME', 'NOVA', 'FTEC']);
    expect(chipRows(null)).toEqual([]);
  });

  it('names the verdict or the state, never a placeholder number', () => {
    expect(moveChip(d.rows[0]).t).toBe('Looks overdone');
    expect(moveChip(d.rows[1]).t).toBe('After the close');
    expect(moveChip(d.rows[1], { status: 'queued' }).t).toBe('Queued');
    expect(moveChip({ status: 'running' }).t).toBe('Researching');
    expect(moveChip({ label: 'market', status: 'market' }).t).toBe('With the market');
    expect(moveHead(d)).toBe('1 of 2 big moves explained');
    expect(moveHead({ rows: [] })).toBe('Nothing moved more than the market');
    expect(confidenceWords(0.6)).toBe('60% sure');
    expect(confidenceWords(null)).toBe(null);
  });
});
