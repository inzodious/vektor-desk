import { describe, expect, it } from 'vitest';
import d from '../fixtures/decisions.profile.json';
import { FIELDS, changeCount, changesFrom, formFrom, getAt, lockedGroups, parseField, pendingLine, savedLine, toText } from './profileEdit.js';

const field = (key) => FIELDS.find((f) => f.key === key);
const p = d.profile;

describe('profile editor', () => {
  it('reads the profile into text fields', () => {
    const form = formFrom(p);
    expect(form['growth.horizon_years']).toBe('10');
    expect(form['opportunity.min_confidence']).toBe('55');
    expect(form['tax.lot_method']).toBe('highest_cost');
    expect(form['industry_focus.themes']).toBe('');
    expect(getAt(p, 'tax.year_end_start')).toBe('12-01');
    expect(toText(field('industry_focus.themes'), [{ name: 'space', weight: 30 }, 'chips'])).toBe('space, chips');
  });

  it('never offers the risk band, desks, deposits or rules', () => {
    const sections = new Set(FIELDS.map((f) => f.key.split('.')[0]));
    ['risk_level', 'agents', 'deposits', 'rules', 'usage'].forEach((s) => expect(sections.has(s)).toBe(false));
  });

  it('parses each kind and refuses what desk.yaml would', () => {
    expect(parseField(field('growth.horizon_years'), '15')).toEqual({ value: 15 });
    expect(parseField(field('growth.horizon_years'), '90').error).toBe('80 or less.');
    expect(parseField(field('opportunity.ideas_per_month'), '2.5').error).toBe('Whole numbers only.');
    expect(parseField(field('opportunity.min_confidence'), '60')).toEqual({ value: 0.6 });
    expect(parseField(field('tax.harvest_threshold_usd'), '').error).toBe('Needs a number.');
    expect(parseField(field('tax.year_end_start'), '13-01').error).toMatch(/MM-DD/);
    expect(parseField(field('tax.year_end_start'), '11-15')).toEqual({ value: '11-15' });
    expect(parseField(field('industry_focus.exclude'), 'tobacco, , ACME ')).toEqual({ value: ['tobacco', 'ACME'] });
  });

  it('keeps theme weights by name', () => {
    const out = parseField(field('industry_focus.themes'), 'Space, chips, space', [{ name: 'space', weight: 30 }]);
    expect(out.value).toEqual([{ name: 'Space', weight: 30 }, { name: 'chips' }]);
  });

  it('sends only what changed, grouped by section', () => {
    const form = { ...formFrom(p), 'growth.tilt': 'balanced', 'opportunity.min_confidence': '60', 'tax.lot_method': 'highest_cost', 'industry_focus.themes': 'space' };
    const { changes, errors } = changesFrom(p, form);
    expect(errors).toEqual({});
    expect(changes).toEqual({ growth: { tilt: 'balanced' }, opportunity: { min_confidence: 0.6 }, industry_focus: { themes: [{ name: 'space' }] } });
    expect(changeCount(changes)).toBe(3);
    expect(changesFrom(p, formFrom(p)).changes).toEqual({});
  });

  it('treats a retyped equal value as no change', () => {
    const { changes } = changesFrom(p, { ...formFrom(p), 'growth.horizon_years': '10.0', 'opportunity.min_confidence': '55.0' });
    expect(changes).toEqual({});
  });

  it('holds back bad fields and sections the API refuses', () => {
    const { changes, errors } = changesFrom(p, { ...formFrom(p), 'growth.horizon_years': 'soon', 'alerts.min_priority': 'high' }, ['growth']);
    expect(errors).toEqual({ 'growth.horizon_years': 'Needs a number.' });
    expect(changes).toEqual({});
    expect(lockedGroups(['growth', 'tax'])).toEqual(['opportunity', 'industry_focus', 'alerts']);
    expect(lockedGroups(null)).toEqual([]);
  });

  it('words the save', () => {
    expect(savedLine({ changed: true, sections: ['growth', 'tax'], version: 4 })).toBe('Saved 2 sections as profile v4. desk.yaml kept a backup.');
    expect(savedLine({ changed: false })).toBe('Nothing changed in desk.yaml.');
    expect(pendingLine(0)).toBe('No changes yet');
    expect(pendingLine(1)).toBe('1 change to save');
    expect(pendingLine(3)).toBe('3 changes to save');
  });
});
