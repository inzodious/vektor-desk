import { describe, expect, it } from 'vitest';
import { fileLine, fileSize, inboxFiles, inboxRefusal, limitText, precheck, savedText } from './inbox.js';

const INBOX = { max_bytes: 25 * 1024 * 1024, suffixes: ['.json', '.csv'], brokers: { fidelity: { import_job: 'engine-lots', files: [{ name: 'a.csv', size: 2048, modified: '2026-10-01T12:00:00Z' }, { name: 'b.csv', size: 10, modified: '2026-11-09T14:05:00Z' }] } } };

describe('inbox helpers', () => {
  it('sizes and lists files newest first', () => {
    expect(fileSize(10)).toBe('10 B');
    expect(fileSize(2048)).toBe('2 KB');
    expect(fileSize(3 * 1024 * 1024)).toBe('3.0 MB');
    expect(inboxFiles(INBOX).map((f) => f.name)).toEqual(['b.csv', 'a.csv']);
    expect(inboxFiles(null)).toEqual([]);
    expect(fileLine(INBOX.brokers.fidelity.files[1], new Date('2026-11-09T16:42:00Z'))).toBe('10 B · added 9:05 AM');
    expect(limitText(INBOX)).toBe('JSON or CSV, up to 25 MB');
  });

  it('checks a file before sending it', () => {
    expect(precheck({ name: 'x.pdf', size: 5 }, INBOX)).toMatch(/Export the lots as CSV/);
    expect(precheck({ name: 'x.csv', size: 0 }, INBOX)).toBe('That file is empty.');
    expect(precheck({ name: 'x.CSV', size: 26 * 1024 * 1024 }, INBOX)).toBe('That file is 26.0 MB; the inbox takes up to 25 MB.');
    expect(precheck({ name: 'x.csv', size: 5 }, INBOX)).toBeNull();
  });

  it('words results and refusals', () => {
    expect(savedText({ name: 'a.csv', size: 2048, duplicate: false })).toBe('Saved as a.csv (2 KB).');
    expect(savedText({ name: 'a.csv', duplicate: true })).toMatch(/^Already in the inbox/);
    expect(inboxRefusal({ body: { error: 'too_large', message: 'Files up to 25 MB.' } })).toBe('Too big for the inbox. Files up to 25 MB.');
    expect(inboxRefusal({ body: { error: 'bad_name' } })).toMatch(/Rename it/);
    expect(inboxRefusal({ message: 'offline', body: null })).toBe('offline');
  });
});
