#!/usr/bin/env node
// `make e2e-parallel`: the e2e suite on the production bundle, in shards (#119's
// split, run on one machine). The migrations and seeds run once into a template
// database. Each shard then gets a copy of it, its own host on its own port and
// its own upload directories, so shards share nothing a test can write to.
//
//   E2E_SHARDS=3 node scripts/e2e_shards.mjs [extra playwright args]
//
// Bundle only: the dev stack would need a Vite server per shard. SQLite only:
// the template is a file. Default mode only: multi-tenant and per-user billing
// write boot-time settings into the template, and CI runs those small suites. Every shard runs to its end, so one failure does not
// hide another's. Output goes to .e2e-shards/: shard-<i>.log for each shard's
// list and its host, and merged.log for all the tests in one report.
import { spawn, spawnSync } from 'node:child_process';
import { createWriteStream, mkdirSync, rmSync, writeFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

import { serverEnv } from './e2e_env.mjs';

const REPO_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const WORK = join(REPO_ROOT, '.e2e-shards');
const SHARDS = Number(process.env.E2E_SHARDS ?? 3);
const BASE_PORT = Number(process.env.E2E_SHARD_BASE_PORT ?? 8100);
const sqliteUrl = (path) => `sqlite+aiosqlite:///${path}`;

if (!Number.isInteger(SHARDS) || SHARDS < 1) {
  console.error(`E2E_SHARDS must be a positive whole number, got ${process.env.E2E_SHARDS}`);
  process.exit(2);
}

if (process.env.E2E_MULTI_TENANT || process.env.E2E_BILLING_USER) {
  console.error('make e2e-parallel runs the default suite only; use make e2e-bundle for this mode');
  process.exit(2);
}

rmSync(WORK, { recursive: true, force: true });
mkdirSync(join(WORK, 'blobs'), { recursive: true });

const template = join(WORK, 'template.db');
console.log('Preparing the template database');
const prepared = spawnSync('tests/e2e/start-test-server.sh', {
  cwd: REPO_ROOT,
  stdio: ['ignore', 'ignore', 'inherit'],
  env: {
    ...process.env,
    ...serverEnv({
      repoRoot: REPO_ROOT,
      apiPort: String(BASE_PORT),
      uiPort: String(BASE_PORT + 1000),
      databaseUrl: sqliteUrl(template),
      bundle: true,
    }),
    E2E_PREPARE_ONLY: '1',
  },
});
if (prepared.status !== 0) process.exit(prepared.status ?? 1);

const children = [];
// Stopping the runner stops its shards, whose Playwright then stops their hosts.
for (const signal of ['SIGINT', 'SIGTERM']) {
  process.on(signal, () => {
    for (const child of children) child.kill(signal);
  });
}

function runShard(shard) {
  const dir = join(WORK, `shard-${shard}`);
  mkdirSync(dir, { recursive: true });
  const logPath = join(WORK, `shard-${shard}.log`);
  const log = createWriteStream(logPath);
  const child = spawn(
    'npx',
    [
      'playwright',
      'test',
      `--shard=${shard}/${SHARDS}`,
      `--output=${join(dir, 'test-results')}`,
      '--reporter=list,blob',
      ...process.argv.slice(2),
    ],
    {
      cwd: REPO_ROOT,
      stdio: ['ignore', 'pipe', 'pipe'],
      env: {
        ...process.env,
        E2E_BUNDLE: '1',
        E2E_API_PORT: String(BASE_PORT + shard),
        E2E_UI_PORT: String(BASE_PORT + 1000 + shard),
        SM_DATABASE_URL: sqliteUrl(join(dir, 'test.db')),
        E2E_DB_TEMPLATE: template,
        E2E_STORAGE_DIR: join(dir, 'storage'),
        PLAYWRIGHT_BLOB_OUTPUT_FILE: join(WORK, 'blobs', `report-${shard}.zip`),
      },
    },
  );
  // `end: false`: whichever stream ended first would otherwise close the log.
  child.stdout.pipe(log, { end: false });
  child.stderr.pipe(log, { end: false });
  children.push(child);
  return new Promise((done) => {
    child.on('close', (code) => {
      log.end();
      console.log(`Shard ${shard}/${SHARDS}: ${code === 0 ? 'passed' : `failed (${code})`}, log ${logPath}`);
      done(code ?? 1);
    });
  });
}

const started = Date.now();
const shards = Array.from({ length: SHARDS }, (_, i) => i + 1);
const codes = await Promise.all(shards.map(runShard));

const merged = spawnSync(
  'npx',
  ['playwright', 'merge-reports', '--reporter=list', join(WORK, 'blobs')],
  { cwd: REPO_ROOT, encoding: 'utf8', maxBuffer: 64 * 1024 * 1024 },
);
writeFileSync(join(WORK, 'merged.log'), merged.stdout ?? '');
if (merged.status !== 0) console.error(`Merging the reports failed:\n${merged.stderr}`);
console.log(`${SHARDS} shards in ${Math.round((Date.now() - started) / 1000)}s`);
process.exit(merged.status === 0 && codes.every((code) => code === 0) ? 0 : 1);
