import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

import { defineConfig, devices } from '@playwright/test';

import { DEFAULT_API_PORT, DEFAULT_UI_PORT, resolvePort } from './scripts/ports.mjs';

export const TEST_ADMIN_EMAIL = 'admin@example.com';
export const TEST_ADMIN_PASSWORD = 'changeme1';

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
    env: {
      // Anything outside development/testing makes the host reference the
      // built assets (host/static/dist) rather than a Vite dev url, and turns
      // on what a deployment runs with: strict CSP, strict module discovery,
      // Secure cookies (which Chromium honours on http://localhost).
      SM_ENVIRONMENT: BUNDLE ? 'production' : 'development',
      // Set here as a real env var so it takes precedence over the repo-root
      // .env (which points at host/app.db). This is what keeps an e2e run
      // from touching the development database. See DATABASE_URL above for
      // how it is chosen.
      SM_DATABASE_URL: DATABASE_URL,
      SM_USERS_BOOTSTRAP_EMAIL: TEST_ADMIN_EMAIL,
      SM_USERS_BOOTSTRAP_PASSWORD: TEST_ADMIN_PASSWORD,
      // Production refuses to boot on the users module's placeholder token
      // secrets, and CI has no .env for `make env` to have filled them in.
      ...(BUNDLE
        ? {
            E2E_BUNDLE: '1',
            SM_USERS_RESET_PASSWORD_TOKEN_SECRET: 'e2e-reset-secret-not-for-production-use',
            SM_USERS_VERIFICATION_TOKEN_SECRET: 'e2e-verify-secret-not-for-production-use',
          }
        : { SM_VITE_DEV_URL: `http://localhost:${UI_PORT}` }),
      SM_PROJECT_ROOT: REPO_ROOT,
      SM_SECRET_KEY: 'e2e-test-secret-key-not-for-production-use',
      // The console speaks English and German, so `console-de.spec.ts` can
      // switch to the second catalogue. English stays the default and the
      // browser asks for en-US, so every other spec still reads English.
      SM_I18N_SUPPORTED_LOCALES: '["en","de"]',
      // Opt-in: the billing tenant flow needs an active organisation, which
      // only exists with multi-tenancy on. The default suite runs without it.
      ...(process.env.E2E_MULTI_TENANT ? { SM_MULTI_TENANT: 'true' } : {}),
      // Opt-in: billing per user (see BILLING_USER above).
      ...(BILLING_USER ? { E2E_BILLING_USER: '1' } : {}),
      // Consumed by Makefile dev-api and vite.config.ts respectively.
      API_PORT,
      SM_UI_PORT: UI_PORT,
    },
  },
});
