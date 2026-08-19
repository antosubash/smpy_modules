import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

import { defineConfig, devices } from '@playwright/test';

export const TEST_ADMIN_EMAIL = 'admin@example.com';
export const TEST_ADMIN_PASSWORD = 'changeme1';

const REPO_ROOT = dirname(fileURLToPath(import.meta.url));
const TEST_DB_PATH = resolve(REPO_ROOT, 'host', 'test.db');

// Ports follow the Makefile's SM_API_PORT / SM_VITE_PORT so a second checkout
// can run its own e2e pass without colliding with the primary dev server.
const API_PORT = process.env.SM_API_PORT ?? '8000';
const VITE_PORT = process.env.SM_VITE_PORT ?? '5050';
const APP_URL = `http://localhost:${API_PORT}`;

export default defineConfig({
  testDir: './tests/e2e',
  fullyParallel: false,
  workers: 1,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  reporter: process.env.CI ? [['github'], ['list']] : 'list',
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
    // `make dev` already orchestrates the API (uvicorn on 8000) and the
    // Vite dev server (5050). Our wrapper resets the test SQLite DB and
    // runs migrations before `make dev` boots so the host's bootstrap
    // logic can seed the admin user on first start.
    command: './tests/e2e/start-test-server.sh',
    url: APP_URL,
    reuseExistingServer: !process.env.CI,
    timeout: 180_000,
    stdout: 'pipe',
    stderr: 'pipe',
    env: {
      SM_ENVIRONMENT: 'development',
      // Absolute path, and set here as a real env var so it takes precedence
      // over the repo-root .env (which points at host/app.db). This is what
      // keeps an e2e run from touching the development database.
      SM_DATABASE_URL: `sqlite+aiosqlite:///${TEST_DB_PATH}`,
      SM_USERS_BOOTSTRAP_EMAIL: TEST_ADMIN_EMAIL,
      SM_USERS_BOOTSTRAP_PASSWORD: TEST_ADMIN_PASSWORD,
      SM_VITE_DEV_URL: `http://localhost:${VITE_PORT}`,
      SM_API_PORT: API_PORT,
      SM_VITE_PORT: VITE_PORT,
      SM_PROJECT_ROOT: REPO_ROOT,
      SM_SECRET_KEY: 'e2e-test-secret-key-not-for-production-use',
    },
  },
});
