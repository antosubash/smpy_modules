#!/usr/bin/env node
// Turns Playwright's JSON report into the CI job summary (#119).
//
//   node scripts/e2e_report_summary.mjs [playwright-report/results.json]
//
// CI retries a failed test once, so a test can fail and then pass. Playwright
// marks that "flaky", and without this nothing anyone reads would say so: the
// run is green and the flake accumulates unseen. Every flaky and every failed
// test is listed in $GITHUB_STEP_SUMMARY (stdout when that is unset), and the
// script exits 1 when any test was flaky or failed — the same gates as
// `failOnFlakyTests` in playwright.config.ts and Playwright's own exit code,
// kept here too so that removing (or `continue-on-error`-ing) one of them does
// not quietly let a flake or a failure pass.
//
// A missing report means Playwright never got as far as writing one (the
// webServer did not boot, say); the Playwright step has already failed with
// the reason, so that is reported and is not a second failure.

import { appendFileSync, existsSync, readFileSync } from 'node:fs';

const reportPath = process.argv[2] ?? 'playwright-report/results.json';

function emit(markdown) {
  const target = process.env.GITHUB_STEP_SUMMARY;
  if (target) appendFileSync(target, `${markdown}\n`);
  else process.stdout.write(`${markdown}\n`);
}

/** Every test in the report, with the spec's file and title path. */
export function collectTests(report) {
  const out = [];
  const walk = (suite, titles) => {
    // A file's own suite is titled with its path, which the row already shows.
    const path = suite.title && suite.title !== suite.file ? [...titles, suite.title] : titles;
    for (const spec of suite.specs ?? []) {
      for (const test of spec.tests ?? []) {
        out.push({
          file: spec.file ?? suite.file,
          line: spec.line,
          title: [...path, spec.title].join(' › '),
          status: test.status,
          attempts: (test.results ?? []).length,
          error: (test.results ?? []).map((r) => r.error?.message).find(Boolean),
        });
      }
    }
    for (const child of suite.suites ?? []) walk(child, path);
  };
  for (const suite of report.suites ?? []) walk(suite, []);
  return out;
}

const firstLine = (text) =>
  (text ?? '')
    // biome-ignore lint/suspicious/noControlCharactersInRegex: ANSI colour codes
    .replace(/\u001b\[[0-9;]*m/g, '')
    .split('\n')
    .find((l) => l.trim())
    ?.trim()
    .slice(0, 160) ?? '';

const cell = (text) =>
  text
    .replace(/\s+/g, ' ')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('`', "'")
    .replaceAll('|', '\\|');

function table(rows) {
  const lines = ['| Test | Attempts | First error |', '| --- | --- | --- |'];
  for (const t of rows) {
    lines.push(
      `| \`${cell(`${t.file}:${t.line}`)}\` ${cell(t.title)} | ${t.attempts} | ${cell(firstLine(t.error))} |`,
    );
  }
  return lines.join('\n');
}

function main() {
  if (!existsSync(reportPath)) {
    emit(`### E2E\n\nNo Playwright report at \`${reportPath}\`; see the test step's log.`);
    return 0;
  }
  const report = JSON.parse(readFileSync(reportPath, 'utf8'));
  const tests = collectTests(report);
  const by = (status) => tests.filter((t) => t.status === status);
  const flaky = by('flaky');
  const failed = by('unexpected');
  const s = report.stats ?? {};
  const minutes = s.duration ? ` in ${(s.duration / 60_000).toFixed(1)} min` : '';

  const parts = [
    '### E2E',
    '',
    `${by('expected').length} passed, ${failed.length} failed, ${flaky.length} flaky, ` +
      `${by('skipped').length} skipped${minutes}.`,
  ];
  if (flaky.length) {
    parts.push(
      '',
      `#### Flaky (failed, then passed on retry) — this fails the job`,
      '',
      table(flaky),
    );
  }
  if (failed.length) parts.push('', '#### Failed', '', table(failed));
  emit(parts.join('\n'));
  return flaky.length || failed.length ? 1 : 0;
}

if (import.meta.url === `file://${process.argv[1]}`) process.exit(main());
