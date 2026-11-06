// Types for e2e_env.mjs, so the TypeScript configs that import it typecheck.
export declare const TEST_ADMIN_EMAIL: string;
export declare const TEST_ADMIN_PASSWORD: string;
export declare function serverEnv(options: {
  repoRoot: string;
  apiPort: string;
  uiPort: string;
  databaseUrl: string;
  bundle?: boolean;
  multiTenant?: boolean;
  billingUser?: boolean;
}): Record<string, string>;
