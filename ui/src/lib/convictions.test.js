import { describe, expect, it } from 'vitest';
import d from '../fixtures/decisions.convictions.json';
import { bandBody, bandCheck, bandText, droppedText, editRefusal, meter, nudgeLine, pct, savedText, scaleMax, startForm, statusWord, suggestLine, weightLine } from './convictions.js';

const [acme, orbt] = d.items;

describe('conviction holds', () => {
  it('words the band, weight and status', () => {
    expect(bandText(orbt)).toBe('2% to 8%');
    expect(pct(12.4)).toBe('12.4%');
    expect(pct(null)).toBe('—');
    expect(statusWord(acme)).toEqual({ t: 'Above the ceiling', tone: 'watch' });
    expect(statusWord({ ...orbt, enabled: false }).t).toBe('Paused');
    expect(statusWord({ status: null }).t).toBe('No weight yet');
    expect(weightLine(orbt)).toBe('5.1% of the portfolio as of 2026-11-09');
    expect(weightLine({ weight_pct: null })).toMatch(/next daily run/);
  });

  it('nudges a trim only above the ceiling', () => {
    expect(nudgeLine(acme)).toMatch(/suggests a trim once a week/);
    expect(nudgeLine(orbt)).toBe('Inside its band. No nudges.');
    expect(nudgeLine({ ...orbt, status: 'below' })).toMatch(/Under 2%/);
    expect(nudgeLine({ status: null })).toBeNull();
  });

  it('says where the suggestion comes from', () => {
    expect(suggestLine(d.suggested)).toBe(`Band ${d.suggested.from_band} (${d.suggested.label}) suggests 0% to ${d.suggested.band_max_pct}%.`);
    expect(suggestLine(null)).toMatch(/Take the risk check/);
  });

  it('scales the meter past the ceiling and the weight', () => {
    expect(scaleMax({ band_max_pct: 10, weight_pct: 12.4 })).toBe(20);
    expect(scaleMax({ band_max_pct: 1, weight_pct: null })).toBe(5);
    const m = meter({ band_min_pct: 2, band_max_pct: 8, weight_pct: 5.1 });
    expect(m.max).toBe(15);
    expect(m.from).toBeCloseTo(13.33, 1);
    expect(m.to).toBeCloseTo(53.33, 1);
    expect(m.mark).toBeCloseTo(34, 0);
    expect(meter({ band_min_pct: 0, band_max_pct: 8, weight_pct: null }).mark).toBeNull();
  });

  it('starts the add form from the suggestion and the edit form from the hold', () => {
    expect(startForm(null, d.suggested)).toEqual({ symbol: '', min: '0', max: String(d.suggested.band_max_pct), note: '' });
    expect(startForm(null, null)).toEqual({ symbol: '', min: '0', max: '', note: '' });
    expect(startForm(orbt)).toEqual({ symbol: 'ORBT', min: '2', max: '8', note: '' });
  });

  it('checks the form before it writes', () => {
    const ok = { symbol: 'acme', min: '0', max: '10', note: '' };
    expect(bandCheck(ok)).toBeNull();
    expect(bandCheck({ ...ok, symbol: 'no way' })).toMatch(/ticker/);
    expect(bandCheck({ ...ok, symbol: 'ORBT' }, { taken: ['ORBT'] })).toMatch(/already has a band/);
    expect(bandCheck({ ...ok, symbol: 'ORBT' }, { taken: ['ORBT'], editing: true })).toBeNull();
    expect(bandCheck({ ...ok, max: '' })).toBe('Give it a ceiling.');
    expect(bandCheck({ ...ok, max: 'ten' })).toMatch(/numbers/);
    expect(bandCheck({ ...ok, min: '12' })).toMatch(/floor sits above/);
    expect(bandCheck({ ...ok, max: '120' })).toMatch(/between 0% and 100%/);
    expect(bandCheck({ ...ok, min: '-1' })).toMatch(/between 0% and 100%/);
  });

  it('sends numbers and a trimmed note', () => {
    expect(bandBody({ min: '', max: '12.5', note: '  why  ' })).toEqual({ band_min_pct: 0, band_max_pct: 12.5, note: 'why' });
  });

  it('words what the write did', () => {
    expect(savedText({ changed: true, item: orbt }, 'ORBT')).toBe('Saved. ORBT now holds 2% to 8%. desk.yaml kept a backup.');
    expect(savedText({ changed: false }, 'ORBT')).toBe('Nothing changed for ORBT.');
    expect(droppedText({ changed: true }, 'ORBT')).toMatch(/single-stock cap covers it again/);
  });

  it('turns refusals into plain words', () => {
    expect(editRefusal({ status: 422, message: 'band_min_pct must be at most band_max_pct' })).toBe('band_min_pct must be at most band_max_pct');
    expect(editRefusal({ status: 409, message: 'The desk API answered 409.' })).toMatch(/no desk.yaml yet/);
    expect(editRefusal({ status: 404, message: 'ACME has no conviction hold' })).toBe('ACME has no conviction hold');
    expect(editRefusal({ status: 500, message: 'x' })).toBe('The desk answered 500. Nothing was written.');
    expect(editRefusal({ status: 0, message: 'x' })).toMatch(/didn’t answer/);
    expect(editRefusal(null)).toBeNull();
  });
});
