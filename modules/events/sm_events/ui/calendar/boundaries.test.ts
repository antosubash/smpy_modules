import { readdirSync, readFileSync, statSync } from 'node:fs';
import { dirname, join, relative, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

const HERE = dirname(fileURLToPath(import.meta.url));
const PACKAGE_ROOT = resolve(HERE, '../..');
const MODULE_ROOT = resolve(PACKAGE_ROOT, '..');
const REPO_ROOT = resolve(MODULE_ROOT, '../..');

/** The only FullCalendar-family packages this module may depend on (all MIT). */
export const ALLOWED = ['@fullcalendar/react', '@fullcalendar/core', '@full-ui/headless-calendar'];
const SCOPES = ['@fullcalendar/', '@full-ui/'];
const PREMIUM = /scheduler|resource|timeline|premium/;
const ADAPTER = 'ui/calendar/adapter/';

type Manifest = Record<string, Record<string, string> | string | undefined>;
type Lock = { packages: Record<string, { license?: string }> };

function inScope(name: string): boolean {
  return SCOPES.some((scope) => name.startsWith(scope));
}

/** Every complaint about a manifest's FullCalendar-family dependencies. */
export function manifestProblems(manifest: Manifest): string[] {
  const problems: string[] = [];
  for (const field of ['dependencies', 'devDependencies', 'peerDependencies']) {
    const block = (manifest[field] ?? {}) as Record<string, string>;
    for (const name of Object.keys(block)) {
      if (PREMIUM.test(name) && inScope(name)) problems.push(`premium name: ${name}`);
      else if (inScope(name) && !ALLOWED.includes(name)) problems.push(`not allowed: ${name}`);
    }
  }
  return problems;
}

/** The lockfile's FullCalendar-family packages, by name, with their licence. */
export function lockProblems(lock: Lock): string[] {
  const problems: string[] = [];
  for (const [path, entry] of Object.entries(lock.packages)) {
    const name = path.split('node_modules/').pop() ?? '';
    if (!inScope(name)) {
      if (PREMIUM.test(name) && /fullcalendar|full-ui/.test(name))
        problems.push(`premium: ${name}`);
      continue;
    }
    if (PREMIUM.test(name)) problems.push(`premium name: ${name}`);
    else if (!ALLOWED.includes(name)) problems.push(`not allowed: ${name}`);
    else if (entry.license !== 'MIT') problems.push(`licence of ${name}: ${entry.license}`);
  }
  return problems;
}

function walk(dir: string, out: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    if (name === 'node_modules') continue;
    const path = join(dir, name);
    if (statSync(path).isDirectory()) walk(path, out);
    else out.push(path);
  }
  return out;
}

describe('FullCalendar dependency allow-list', () => {
  const manifest = JSON.parse(readFileSync(join(MODULE_ROOT, 'package.json'), 'utf8')) as Manifest;
  const lock = JSON.parse(readFileSync(join(REPO_ROOT, 'package-lock.json'), 'utf8')) as Lock;

  it('allow-lists FullCalendar packages in the module manifest', () => {
    expect(manifestProblems(manifest)).toEqual([]);
    expect((manifest.dependencies as Record<string, string>)['@fullcalendar/react']).toBeDefined();
  });

  it('allow-lists every FullCalendar package in the lockfile', () => {
    expect(lockProblems(lock)).toEqual([]);
    const names = Object.keys(lock.packages).map((path) => path.split('node_modules/').pop());
    for (const allowed of ALLOWED) expect(names).toContain(allowed);
  });

  it('refuses premium names, in the manifest and in the lockfile', () => {
    expect(
      manifestProblems({ dependencies: { '@fullcalendar/react-scheduler': '7.0.0' } }),
    ).not.toEqual([]);
    expect(
      manifestProblems({ dependencies: { '@fullcalendar/resource-timeline': '7.0.0' } }),
    ).not.toEqual([]);
    expect(manifestProblems({ dependencies: { '@fullcalendar/rrule': '7.0.0' } })).not.toEqual([]);
    expect(
      lockProblems({ packages: { 'node_modules/@fullcalendar/premium-common': {} } }),
    ).not.toEqual([]);
    expect(
      lockProblems({ packages: { 'node_modules/@fullcalendar/react': { license: 'AGPL-3.0' } } }),
    ).not.toEqual([]);
  });

  it('keeps the module free of any name that looks premium', () => {
    const all = JSON.stringify(manifest);
    expect(all).not.toMatch(/@(fullcalendar|full-ui)\/[^"]*(scheduler|resource|timeline|premium)/);
  });
});

describe('FullCalendar import boundary', () => {
  it('imports FullCalendar only from the adapter', () => {
    const offenders = walk(PACKAGE_ROOT)
      .filter((file) => /\.(ts|tsx|css)$/.test(file))
      .filter((file) => !file.endsWith('boundaries.test.ts'))
      .map((file) => relative(PACKAGE_ROOT, file).split('\\').join('/'))
      .filter((file) => !file.startsWith(ADAPTER))
      .filter((file) => readFileSync(join(PACKAGE_ROOT, file), 'utf8').includes('@fullcalendar/'));
    expect(offenders).toEqual([]);
  });
});
