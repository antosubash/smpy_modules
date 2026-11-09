import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

import { defineConfig, devices } from '@playwright/test';

import { serverEnv } from './scripts/e2e_env.mjs';
import { DEFAULT_API_PORT, DEFAULT_UI_PORT, resolvePort } from './scripts/ports.mjs';

export { TEST_ADMIN_EMAIL, TEST_ADMIN_PASSWORD } from './scripts/e2e_env.mjs';

const REPO_ROOT = dirname(fileURLToPath(import.meta.url));
const TEST_DB_PATH = resolve(REPO_ROOT, 'host', 'test.db');

// Overridable so a worktree can run e2e beside a dev stack holding the
// default ports (E2E_API_PORT / E2E_UI_PORT). scripts/ports.mjs is the guard
// the Makefile and vite.config.ts use too, so a set-but-empty or garbage
// value means the default everywhere rather than three different things.
const API_PORT = resolvePort([process.env.E2E_API_PORT], DEFAULT_API_PORT);
const UI_PORT = resolvePort([process.env.E2E_UI_PORT], DEFAULT_UI_PORT);
const APP_URL = `http://localhost:${API_PORT}`;

// The suite's own SQLite file unless the caller names a database, which is how
// the same specs are run against Postgres (`SM_DATABASE_URL=postgresql+asyncpg
// ://... npx playwright test`). It has to be read *here* rather than left to
// the shell: `webServer.env` below is an explicit environment for the child,
// so a variable set in the parent shell that is also named in that object is
// overwritten by the object's value — exporting SM_DATABASE_URL without this
// line silently ran the whole suite on SQLite anyway.
//
// `start-test-server.sh` decides how to empty whichever database this names.
const DATABASE_URL =
  process.env.SM_DATABASE_URL?.trim() || `sqlite+aiosqlite:///${TEST_DB_PATH}`;

// E2E_BUNDLE=1 (CI, or `make e2e-bundle`) runs the suite against the
// production bundle served by a plain uvicorn instead of `make dev`'s Vite dev
// server and --reload (#119) — see start-test-server.sh. Locally the dev
// server stays the default, so a spec can be iterated on without a rebuild.
const BUNDLE = process.env.E2E_BUNDLE === '1';

// Every retry is reported, and in CI fails the job (`failOnFlakyTests`). The
// one retry is there so the report can tell a flake (passed on retry, marked
// "flaky") from a regression (failed twice), not so a flake can go green —
// scripts/e2e_report_summary.mjs lists both in the job summary (#119).
const CI = !!process.env.CI;

// E2E_BILLING_USER=1 runs billing with `subject_mode=user` (#274), a boot-time
// setting start-test-server.sh writes before the host starts. Only
// billing-user.spec.ts belongs to that host; every other spec assumes the
// default (tenant) mode, and that spec needs the user mode, so each run
// ignores the other's files (CI's `E2E (billing per user)` job).
const BILLING_USER = process.env.E2E_BILLING_USER === '1';

export default defineConfig({
  testDir: './tests/e2e',
  ...(BILLING_USER
    ? { testMatch: /billing-user\.spec\.ts$/ }
    : { testIgnore: /billing-user\.spec\.ts$/ }),
  // One worker against one host and one database: a second worker would be a
  // second writer to the same SQLite file. Parallelism comes from CI-level
  // `--shard=i/n` instead, each shard a separate job with its own host (#119).
  // With fullyParallel off a shard gets whole files, so every spec file has to
  // pass on a fresh database without any other file having run before it.
  fullyParallel: false,
  workers: 1,
  forbidOnly: CI,
  retries: CI ? 1 : 0,
  failOnFlakyTests: CI,
  // CI runs the suite in shards (ci.yml's `e2e-shard` matrix), each on its own
  // runner with its own host and SQLite file. Every shard writes a blob report;
  // the `E2E (Playwright)` job merges them with `playwright merge-reports` into
  // the one results.json the flaky/failed summary reads. The shard's own
  // results.json stays for reading a single shard's artifact.
  reporter: CI
    ? [
        ['github'],
        ['list'],
        ['json', { outputFile: 'playwright-report/results.json' }],
        ['blob', { outputDir: 'blob-report' }],
      ]
    : 'list',
  timeout: 60_000,
  expect: { timeout: 10_000 },

  use: {
    baseURL: APP_URL,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
  },

  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],

  webServer: {
    // `make dev` already orchestrates the API (uvicorn on API_PORT) and the
    // Vite dev server (UI_PORT); with E2E_BUNDLE=1 it is uvicorn alone. Our
    // wrapper resets the test SQLite DB and runs migrations before the server
    // boots so the host's bootstrap logic can seed the admin user on first
    // start.
    command: './tests/e2e/start-test-server.sh',
    // Not `/`: since framework 0.0.37 an anonymous request for a path no
    // route matches is a 404 rather than a redirect to sign-in (upstream
    // #473), and Playwright never counts a 404 as "up".
    url: `${APP_URL}/health/live`,
    // Never in bundle mode: a dev stack already on API_PORT would be reused
    // and the run would pass without ever loading the bundle.
    reuseExistingServer: !CI && !BUNDLE,
    timeout: 180_000,
    stdout: 'pipe',
    stderr: 'pipe',
    env: serverEnv({
      repoRoot: REPO_ROOT,
      apiPort: API_PORT,
      uiPort: UI_PORT,
      databaseUrl: DATABASE_URL,
      bundle: BUNDLE,
      multiTenant: !!process.env.E2E_MULTI_TENANT,
      billingUser: BILLING_USER,
    }),
  },
});
