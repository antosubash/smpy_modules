// The environment an e2e host runs with. playwright.config.ts gives it to the
// host it starts, and scripts/e2e_shards.mjs to the one-off that prepares a
// template database, so the two cannot drift apart.
export const TEST_ADMIN_EMAIL = 'admin@example.com';
export const TEST_ADMIN_PASSWORD = 'changeme1';

export function serverEnv({
  repoRoot,
  apiPort,
  uiPort,
  databaseUrl,
  bundle = false,
  multiTenant = false,
  billingUser = false,
}) {
  return {
    // Anything outside development/testing makes the host reference the
    // built assets (host/static/dist) rather than a Vite dev url, and turns
    // on what a deployment runs with: strict CSP, strict module discovery,
    // Secure cookies (which Chromium honours on http://localhost).
    SM_ENVIRONMENT: bundle ? 'production' : 'development',
    // Set here as a real env var so it takes precedence over the repo-root
    // .env (which points at host/app.db). This is what keeps an e2e run
    // from touching the development database. See DATABASE_URL in
    // playwright.config.ts for how it is chosen.
    SM_DATABASE_URL: databaseUrl,
    SM_USERS_BOOTSTRAP_EMAIL: TEST_ADMIN_EMAIL,
    SM_USERS_BOOTSTRAP_PASSWORD: TEST_ADMIN_PASSWORD,
    // Production refuses to boot on the users module's placeholder token
    // secrets, and CI has no .env for `make env` to have filled them in.
    ...(bundle
      ? {
          E2E_BUNDLE: '1',
          SM_USERS_RESET_PASSWORD_TOKEN_SECRET: 'e2e-reset-secret-not-for-production-use',
          SM_USERS_VERIFICATION_TOKEN_SECRET: 'e2e-verify-secret-not-for-production-use',
        }
      : { SM_VITE_DEV_URL: `http://localhost:${uiPort}` }),
    SM_PROJECT_ROOT: repoRoot,
    SM_SECRET_KEY: 'e2e-test-secret-key-not-for-production-use',
    // The console speaks English and German, so `console-de.spec.ts` can
    // switch to the second catalogue. English stays the default and the
    // browser asks for en-US, so every other spec still reads English.
    SM_I18N_SUPPORTED_LOCALES: '["en","de"]',
    // Opt-in: the billing tenant flow needs an active organisation, which
    // only exists with multi-tenancy on. The default suite runs without it.
    ...(multiTenant ? { SM_MULTI_TENANT: 'true' } : {}),
    // Opt-in: billing per user (see BILLING_USER above).
    ...(billingUser ? { E2E_BILLING_USER: '1' } : {}),
    // Consumed by Makefile dev-api and vite.config.ts respectively.
    API_PORT: apiPort,
    SM_UI_PORT: uiPort,
  };
}
