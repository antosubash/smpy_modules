/**
 * The article body editor's Puck chrome, made usable without a mouse (#286),
 * as pagebuilder's editors are (#235): the zoom select is named, the plugin
 * rail (Blocks, Outline, Fields) is reachable and pressable from the
 * keyboard, and Enter on a focused canvas block selects it as a click does.
 * news' `usePuckA11y` finds Puck's markup by class-name prefix, so this spec
 * is also what fails when a Puck upgrade renames it.
 */

import { expect, test } from '@playwright/test';

import { seedArticle } from './article-helpers';
import { login } from './helpers';

test.beforeEach(async ({ page }) => {
  await login(page);
});

test('the article body editor can be driven from the keyboard', async ({ page }) => {
  const { articleId } = await seedArticle(page, {
    prefix: 'a11y',
    // Dated, so it does not join the undated pile at the top of the admin
    // list that other specs read (see article-contents.spec.ts).
    publishedAt: '2026-02-11T00:00:00Z',
    body: {
      root: { props: {} },
      content: [{ type: 'Heading', props: { id: 'h1', text: 'Keyboard heading', level: '2' } }],
      zones: {},
    },
  });
  await page.goto(`/admin/news/articles/${articleId}/body`);

  await expect(page.getByRole('combobox', { name: 'Zoom' })).toBeVisible();

  // Enter on a focused block opens its fields, like a click.
  const canvas = page.frameLocator('#preview-frame');
  await canvas.locator('[data-puck-component="h1"]').focus();
  await page.keyboard.press('Enter');
  await expect(page.getByRole('textbox', { name: 'Text' })).toHaveValue('Keyboard heading');

  // The plugin rail: Outline is a button a keyboard reaches and presses.
  const outline = page.getByRole('button', { name: 'Outline', exact: true });
  await expect(outline).toHaveAttribute('tabindex', '0');
  await outline.focus();
  await expect(outline).toBeFocused();
  await page.keyboard.press('Enter');
  // The Outline's rows are buttons; the Blocks drawer's are not.
  await expect(page.locator('button[class*="_Layer-clickable_"]').first()).toBeVisible();
});
