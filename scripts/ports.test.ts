import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

import { describe, expect, it } from 'vitest';

import { DEFAULT_API_PORT, DEFAULT_UI_PORT, resolvePort } from './ports.mjs';

const CLI = fileURLToPath(new URL('./ports.mjs', import.meta.url));
const cli = (...args: string[]) => execFileSync('node', [CLI, ...args], { encoding: 'utf8' }).trim();

describe('resolvePort', () => {
  it('takes the first non-empty candidate', () => {
    expect(resolvePort([undefined, '', '8045', '9000'], '8000')).toBe('8045');
  });

  it('falls back when nothing is set', () => {
    expect(resolvePort([], '8000')).toBe('8000');
    expect(resolvePort([undefined, ''], '5050')).toBe('5050');
  });

  it.each(['0', '08', '0x1f90', '1e3', ' 8045', '8045 ', '-1', '80.5', "x' ; rm -rf /"])(
    'rejects %j rather than trying the next candidate',
    (bad) => {
      expect(resolvePort([bad, '9000'], '8000')).toBe('8000');
    },
  );
});

describe('CLI', () => {
  it('prints the default for each kind', () => {
    expect(cli('api')).toBe(DEFAULT_API_PORT);
    expect(cli('ui')).toBe(DEFAULT_UI_PORT);
  });

  it('applies the same guard as the module', () => {
    expect(cli('ui', '', '5105', '9')).toBe('5105');
    expect(cli('api', '08', '8045')).toBe(DEFAULT_API_PORT);
  });

  it('rejects an unknown kind', () => {
    expect(() => execFileSync('node', [CLI, 'db'], { stdio: 'pipe' })).toThrow();
  });
});
