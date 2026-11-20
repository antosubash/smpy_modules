// The framework's dark tokens put muted text at about 4.1:1 and the error red at about 3.7:1 on the
// dark card: below 4.5:1. Every use in this module pairs them with a lighter dark-mode colour.
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';

const ROOT = join(__dirname, '..');

function sources(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return name === 'page-tests' ? [] : sources(path);
    return /\.tsx$/.test(name) && !/\.test\.tsx$/.test(name) ? [path] : [];
  });
}

describe('dark mode contrast', () => {
  it('gives every dialog description the lighter dark-mode text', () => {
    const bare: string[] = [];
    for (const path of sources(ROOT)) {
      const text = readFileSync(path, 'utf8');
      for (const match of text.matchAll(/<(?:Alert)?DialogDescription(?=[\s>])([^>]*)>/g)) {
        if (!match[1].includes('dark:text-zinc-400')) bare.push(path.slice(ROOT.length + 1));
      }
    }
    expect(bare).toEqual([]);
  });

  it('never uses the bare muted or destructive text token', () => {
    const bare: string[] = [];
    for (const path of sources(ROOT)) {
      const text = readFileSync(path, 'utf8');
      for (const [token, dark] of [
        ['text-muted-foreground', 'dark:text-zinc-400'],
        ['text-destructive', 'dark:text-red-400'],
      ] as const) {
        const pattern = new RegExp(`(?<![\\w:/-])${token}(?![\\w/-])(?! ${dark})`, 'g');
        if (pattern.test(text)) bare.push(`${path.slice(ROOT.length + 1)}: ${token}`);
      }
    }
    expect(bare).toEqual([]);
  });
});
