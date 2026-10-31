/**
 * Pagebuilder screens that did not fit their viewport (#236, #237): a long
 * media filename widening the page, the new-page dialog's actions cut off at a
 * short height, the blobs timeline wider than a 320px phone, and the layout
 * editor's two Puck instances each taking a full viewport, so the footer's
 * toolbar sat on top of the header's inspector and took its clicks.
 */

import { expect, type Page, test } from '@playwright/test';

import { login, makePage, moduleCsrfHeader, uniqueSlug } from './helpers';

/** 1x1 transparent PNG: the upload endpoint sniffs content, not the name. */
const PNG = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==',
  'base64',
);

async function overflowX(page: Page): Promise<number> {
  return page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
}

test.describe('Pagebuilder fits its viewport', () => {
  test.beforeEach(async ({ page }) => {
    await login(page);
  });

  test('a long media filename wraps instead of widening the page', async ({ page }) => {
    const headers = await moduleCsrfHeader(page, '/pagebuilder/');
    // 68 characters and no hyphen, space or dot before the extension to break at.
    const name = `${'longassetfilename'.repeat(3)}${Date.now().toString(36)}xxxxxxxxxx.png`.slice(
      -68,
    );
    const created = await page.request.post('/api/pagebuilder/uploads', {
      headers,
      multipart: { file: { name, mimeType: 'image/png', buffer: PNG } },
    });
    expect(created.ok(), await created.text()).toBeTruthy();
    const { id } = (await created.json()) as { id: number };

    for (const width of [375, 768]) {
      await page.setViewportSize({ width, height: 800 });
      await page.goto(`/pagebuilder/media/${id}`);
      await expect(page.getByRole('heading', { name, level: 1 })).toBeVisible();
      expect(await overflowX(page)).toBe(0);
    }
    // The delete confirmation names the file too, and must wrap it as well.
    await page.setViewportSize({ width: 375, height: 800 });
    await page.getByRole('button', { name: 'Delete asset' }).click();
    const confirm = page.getByRole('alertdialog');
    const title = confirm.getByRole('heading', { name: `Delete “${name}”?` });
    await expect(title).toBeVisible();
    // The header is a grid, so an unbreakable title widens its own box past
    // the dialog's edge rather than overflowing itself.
    const [dialogBox, titleBox] = [await confirm.boundingBox(), await title.boundingBox()];
    expect(titleBox && dialogBox && titleBox.x + titleBox.width).toBeLessThanOrEqual(
      (dialogBox?.x ?? 0) + (dialogBox?.width ?? 0),
    );
    await page.keyboard.press('Escape');
    await page.request.delete(`/api/pagebuilder/uploads/${id}`, { headers });
  });

  test('the new-page dialog keeps its actions reachable at 720x450', async ({ page }) => {
    await page.setViewportSize({ width: 720, height: 450 });
    await page.goto('/pagebuilder/');
    await page.getByRole('button', { name: 'New page' }).first().click();
    const dialog = page.getByRole('dialog');
    await expect(dialog).toBeVisible();

    const box = await dialog.boundingBox();
    expect(box).not.toBeNull();
    expect(box?.y ?? -1).toBeGreaterThanOrEqual(0);
    expect((box?.y ?? 0) + (box?.height ?? 0)).toBeLessThanOrEqual(450);

    await expect(dialog.getByRole('button', { name: 'Close' })).toBeInViewport();
    // The form scrolls inside the dialog, so the actions are a scroll away.
    const create = dialog.getByRole('button', { name: 'Create and open editor' });
    await create.scrollIntoViewIfNeeded();
    await expect(create).toBeInViewport();
    // The close button does not scroll away with the form.
    await expect(dialog.getByRole('button', { name: 'Close' })).toBeInViewport();
  });

  test('the blobs timeline fits a 320px phone', async ({ page }) => {
    const slug = uniqueSlug('timeline');
    const item = (marker: string) => ({ marker, title: `Step ${marker}`, body: 'Body text' });
    await makePage(page, {
      slug,
      publish: true,
      blocks: [
        {
          type: 'Timeline',
          props: {
            id: 't1',
            eyebrow: 'Plan',
            title: 'Roadmap',
            variant: 'blobs',
            items: [item('1'), item('2'), item('3')],
          },
        },
      ],
    });

    await page.setViewportSize({ width: 320, height: 700 });
    await page.goto(`/p/${slug}`);
    await expect(page.getByText('Step 3')).toBeVisible();
    expect(await overflowX(page)).toBe(0);
  });

  test('each layout editor stays in its half', async ({ page }) => {
    for (const size of [
      { width: 1440, height: 900 },
      { width: 1280, height: 720 },
    ]) {
      await page.setViewportSize(size);
      await page.goto('/pagebuilder/layout');
      const header = page.getByTestId('layout-header-slot');
      const footer = page.getByTestId('layout-footer-slot');
      await expect(header).toBeVisible();

      const footerTop = (await footer.boundingBox())?.y ?? 0;
      // The header's Puck ends above the footer's slot; before the fix it
      // took 100dvh and ran a full viewport down.
      const headerBottom = await header.evaluate(
        (slot) =>
          slot.querySelector(':scope > div.flex-1 > *')?.getBoundingClientRect().bottom ??
          Number.POSITIVE_INFINITY,
      );
      expect(headerBottom).toBeLessThanOrEqual(footerTop + 1);

      // And a point inside the header's editor belongs to the header.
      const box = await header.boundingBox();
      const owner = await page.evaluate(
        ([x, y]) => {
          const el = document.elementFromPoint(x, y);
          return el?.closest('[data-testid$="-slot"]')?.getAttribute('data-testid') ?? null;
        },
        [(box?.x ?? 0) + (box?.width ?? 0) - 60, (box?.y ?? 0) + (box?.height ?? 0) - 20],
      );
      expect(owner).toBe('layout-header-slot');
    }
  });
});
