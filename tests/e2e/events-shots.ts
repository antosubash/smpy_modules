import type { Locator, Page } from '@playwright/test';

/** Screenshots for a pull request, written only when `E2E_SHOTS_DIR` names a folder: a normal or
 *  CI run writes nothing (and a spec never hard-codes a path into the repository). */
export async function shoot(
  page: Page | Locator,
  name: string,
  options: { fullPage?: boolean } = {},
) {
  const dir = process.env.E2E_SHOTS_DIR;
  if (dir) await page.screenshot({ path: `${dir}/${name}.png`, ...options });
}
