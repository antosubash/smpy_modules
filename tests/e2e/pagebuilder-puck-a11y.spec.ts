/**
 * Puck's editor chrome, made usable without a mouse (#235): the zoom select
 * and an array field's add button are named, the plugin rail (Blocks,
 * Outline, Fields) is reachable and pressable from the keyboard, and Enter on
 * a focused canvas block selects it as a click does. `usePuckA11y` finds
 * Puck's markup by class-name prefix, so this spec is also what fails when a
 * Puck upgrade renames it.
 */

import { expect, test } from '@playwright/test';

import { login, makePage, uniqueSlug } from './helpers';

test.describe('Puck editor accessibility', () => {
  test.beforeEach(async ({ page }) => {
    await login(page);
  });

  test('the page editor can be driven from the keyboard', async ({ page }) => {
    const id = await makePage(page, {
      slug: uniqueSlug('a11y'),
      blocks: [
        { type: 'Heading', props: { id: 'h1', text: 'Keyboard heading', level: 'h2' } },
        { type: 'Gallery', props: { id: 'g1', items: [] } },
      ],
    });
    await page.goto(`/pagebuilder/${id}/edit`);

    await expect(page.getByRole('combobox', { name: 'Zoom' })).toBeVisible();

    // Enter on a focused block opens its fields, like a click.
    const canvas = page.frameLocator('#preview-frame');
    await canvas.locator('[data-puck-component="h1"]').focus();
    await page.keyboard.press('Enter');
    await expect(page.getByRole('textbox', { name: 'Text' })).toHaveValue('Keyboard heading');

    // A selected block's array field names its add button.
    await canvas.locator('[data-puck-component="g1"]').focus();
    await page.keyboard.press('Enter');
    await expect(page.getByRole('button', { name: 'Add item' }).first()).toBeVisible();

    // The plugin rail: Outline is a button a keyboard reaches and presses.
    const outline = page.getByRole('button', { name: 'Outline', exact: true });
    await outline.focus();
    await expect(outline).toBeFocused();
    await page.keyboard.press('Enter');
    // The Outline's rows are buttons; the Blocks drawer's are not.
    await expect(page.locator('button[class*="_Layer-clickable_"]').first()).toBeVisible();
  });

  test('both layout editors reach their plugin rail from the keyboard', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto('/pagebuilder/layout');
    // No viewport switcher here (the canvases are in the page), so no zoom.
    for (const slot of ['layout-header-slot', 'layout-footer-slot']) {
      const blocks = page.getByTestId(slot).getByRole('button', { name: 'Blocks', exact: true });
      await expect(blocks).toHaveAttribute('tabindex', '0');
      await blocks.focus();
      await page.keyboard.press('Enter');
      await expect(blocks).toBeFocused();
    }
  });
});
