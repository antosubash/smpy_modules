import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { EVENT_MAX_DAYS, SERIES_EVENT_MAX_DAYS } from './limits';

describe('limits', () => {
  it('agree with the backend', () => {
    const python = readFileSync(
      new URL('../../core/constants/__init__.py', import.meta.url),
      'utf8',
    );
    const read = (name: string) => Number(new RegExp(`^${name} = (\\d+)`, 'm').exec(python)?.[1]);
    expect(EVENT_MAX_DAYS).toBe(read('MAX_EVENT_DAYS'));
    expect(SERIES_EVENT_MAX_DAYS).toBe(read('MAX_SERIES_EVENT_DAYS'));
  });
});
