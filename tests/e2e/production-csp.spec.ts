import { expect, test } from '@playwright/test';

import { login } from './helpers';

/**
 * Framework 0.0.43 made the production script policy nonce-based: no
 * `unsafe-inline`, no `unsafe-eval`. A script without the nonce, or a bundled
 * dependency calling `new Function`, fails only in the built app, which is
 * the only place this spec runs (development keeps a permissive Vite policy).
 */
test.describe('Production CSP', () => {
  test.skip(process.env.E2E_BUNDLE !== '1', 'only the built bundle gets the nonce policy');

  test('every script on a page carries the nonce its policy names', async ({ request }) => {
    const response = await request.get('/users/login');
    const policy = response.headers()['content-security-policy'];
    const nonce = policy.match(/'nonce-([\w-]+)'/)?.[1];
    expect(nonce, policy).toBeTruthy();
    expect(policy).not.toContain("'unsafe-eval'");
    expect(policy).not.toMatch(/script-src[^;]*unsafe-inline/);

    const html = await response.text();
    const scripts = html.match(/<script\b[^>]*>/g) ?? [];
    const executable = scripts.filter((tag) => !tag.includes('type="application/json"'));
    expect(executable.length).toBeGreaterThan(0);
    for (const tag of executable) expect(tag).toContain(`nonce="${nonce}"`);
  });

  test('signing in and opening the page editor breaks no policy', async ({ page }) => {
    const violations: string[] = [];
    page.on('console', (message) => {
      if (message.text().includes('Content Security Policy')) violations.push(message.text());
    });
    page.on('pageerror', (error) => violations.push(String(error)));

    await login(page);
    await page.goto('/pagebuilder/new');
    await page.waitForLoadState('networkidle');
    await page.goto('/admin/images/');
    await page.waitForLoadState('networkidle');

    expect(violations).toEqual([]);
  });
});
