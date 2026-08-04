import { defineConfig } from 'vitest/config';

// Unit tests for module frontend code. The e2e suite covers what the browser
// does; this covers logic that a browser test can only reach indirectly — the
// block registry's memo invalidation being the case that prompted it.
export default defineConfig({
  test: {
    include: ['modules/**/*.test.ts', 'modules/**/*.test.tsx'],
    environment: 'node',
  },
});
