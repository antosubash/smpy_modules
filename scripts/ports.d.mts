// Types for ports.mjs, so the TypeScript configs that import it typecheck.
export declare const DEFAULT_API_PORT: string;
export declare const DEFAULT_UI_PORT: string;
export declare function resolvePort(
  candidates: readonly (string | undefined)[],
  fallback: string,
): string;
