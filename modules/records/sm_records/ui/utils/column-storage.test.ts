// @vitest-environment happy-dom
import { afterEach, describe, expect, it, vi } from 'vitest';

import { columnStorageKey, readSavedColumns, writeSavedColumns } from './column-storage';

afterEach(() => {
  vi.restoreAllMocks();
  window.localStorage.clear();
});

describe('column-storage — the per-browser default', () => {
  it('round-trips a choice per type key', () => {
    writeSavedColumns('book', ['status', 'price']);
    expect(readSavedColumns('book')).toEqual(['status', 'price']);
    expect(readSavedColumns('author')).toBeNull();
  });

  it('forgets the choice on null ("Reset to default")', () => {
    writeSavedColumns('book', ['price']);
    writeSavedColumns('book', null);
    expect(window.localStorage.getItem(columnStorageKey('book'))).toBeNull();
    expect(readSavedColumns('book')).toBeNull();
  });

  it('reads anything that is not a JSON array of strings as nothing saved', () => {
    for (const junk of ['{not json', '"price"', '{"a":1}', '[1,2]', 'null']) {
      window.localStorage.setItem(columnStorageKey('book'), junk);
      expect(readSavedColumns('book')).toBeNull();
    }
  });

  it('survives a storage that throws on every access', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('SecurityError');
    });
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('QuotaExceededError');
    });
    expect(readSavedColumns('book')).toBeNull();
    expect(() => writeSavedColumns('book', ['price'])).not.toThrow();
  });
});
