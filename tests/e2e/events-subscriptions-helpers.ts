import { execFileSync } from 'node:child_process';
import { mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';

const REPO = process.cwd(); // Playwright runs from the repository root
const DB_URL =
  process.env.SM_DATABASE_URL?.trim() || `sqlite+aiosqlite:///${resolve(REPO, 'host', 'test.db')}`;

/** Cached items for `subscription`, written by the module's own store function. */
export function seedItems(subscription: string, day: string, titles: string[]) {
  const dir = mkdtempSync(join(tmpdir(), 'events-feed-'));
  try {
    const compact = day.replaceAll('-', '');
    const events = titles.map((title, index) =>
      [
        'BEGIN:VEVENT',
        `UID:ext-${index}@feed`,
        `DTSTART:${compact}T0${8 + index}0000Z`,
        `DTEND:${compact}T0${9 + index}0000Z`,
        `SUMMARY:${title}`,
        'URL:https://source.example/holiday',
        'END:VEVENT',
      ].join('\r\n'),
    );
    const feed = [
      'BEGIN:VCALENDAR',
      'VERSION:2.0',
      'PRODID:-//e2e//EN',
      ...events,
      'END:VCALENDAR',
      '',
    ].join('\r\n');
    const file = join(dir, 'feed.ics');
    writeFileSync(file, feed);
    execFileSync(
      'uv',
      ['run', 'python', 'tests/e2e/support/seed_external.py', DB_URL, subscription, file],
      {
        cwd: REPO,
        stdio: 'pipe',
      },
    );
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
}
