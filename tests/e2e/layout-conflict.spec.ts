import { expect, test } from '@playwright/test';

import { login, moduleCsrfHeader } from './helpers';

function document(slot: string) {
  return {
    content: [1, 2].map((n) => ({
      type: 'Heading',
      props: { id: `${slot.replaceAll(' ', '-')}-${n}`, text: `${slot} ${n}`, level: 'h2' },
    })),
    root: { props: {} },
  };
}

test('stale layout save offers Reload and Overwrite, then resumes guarded saves', async ({
  page,
}) => {
  await login(page);
  const headers = await moduleCsrfHeader(page, '/pagebuilder/');
  const path = '/api/pagebuilder/layout';
  // This singleton needs no pages or seed data from another spec.
  const seeded = await page.request.put(path, {
    headers,
    data: { header_data: document('Original header'), footer_data: document('Original footer') },
  });
  expect(seeded.ok(), await seeded.text()).toBe(true);
  const loadedVersion = (await seeded.json()).updated_at;
  // The narrow screen's accessible outline edits the same documents as Puck.
  await page.setViewportSize({ width: 650, height: 900 });
  await page.goto('/pagebuilder/layout');
  const header = page.getByTestId('layout-header-slot');
  const footer = page.getByTestId('layout-footer-slot');
  await expect(header.getByRole('listitem').first()).toContainText('Original header 1');
  await header
    .getByRole('button', { name: /^Move .* down$/ })
    .first()
    .click();
  await footer
    .getByRole('button', { name: /^Move .* down$/ })
    .first()
    .click();

  const other = await page.request.put(path, {
    headers,
    data: {
      expected_updated_at: loadedVersion,
      header_data: document('Server header'),
      footer_data: document('Server footer'),
    },
  });
  expect(other.ok(), await other.text()).toBe(true);
  const refused = page.waitForResponse((r) => r.url().endsWith('/layout') && r.status() === 409);
  await page.getByRole('button', { name: 'Save layout', exact: true }).click();
  expect((await refused).request().postDataJSON().expected_updated_at).toBe(loadedVersion);
  const banner = page.getByRole('alert').filter({ hasText: 'This layout was changed elsewhere' });
  await expect(banner).toBeVisible();
  await expect(page.getByText(/^Layout saved/)).toHaveCount(0);
  expect(await (await page.request.get(path)).json()).toEqual(await other.json());

  await banner.getByRole('button', { name: 'Reload', exact: true }).click();
  await expect(banner).toHaveCount(0);
  await expect(header.getByRole('listitem').first()).toContainText('Server header 1');
  await expect(footer.getByRole('listitem').first()).toContainText('Server footer 1');
  await header
    .getByRole('button', { name: /^Move .* down$/ })
    .first()
    .click();
  await footer
    .getByRole('button', { name: /^Move .* down$/ })
    .first()
    .click();
  const external = await page.request.put(path, {
    headers,
    data: { header_data: document('Another editor') },
  });
  expect(external.ok(), await external.text()).toBe(true);
  await page.getByRole('button', { name: 'Save layout', exact: true }).click();
  await expect(banner).toBeVisible();
  const overwritten = page.waitForResponse(
    (r) => r.url().endsWith('/layout') && r.request().method() === 'PUT' && r.ok(),
  );
  await banner.getByRole('button', { name: 'Overwrite', exact: true }).click();
  const saved = await overwritten;
  expect(saved.request().postDataJSON()).not.toHaveProperty('expected_updated_at');
  await expect(banner).toHaveCount(0);
  await expect(page.getByText(/^Layout saved/)).toBeVisible();
  const stored = await (await page.request.get(path)).json();
  expect(stored.header_data.content.map((b: { props: { text: string } }) => b.props.text)).toEqual([
    'Server header 2',
    'Server header 1',
  ]);
  expect(stored.footer_data.content.map((b: { props: { text: string } }) => b.props.text)).toEqual([
    'Server footer 2',
    'Server footer 1',
  ]);

  await footer
    .getByRole('button', { name: /^Move .* down$/ })
    .first()
    .click();
  const resumed = page.waitForResponse(
    (r) => r.url().endsWith('/layout') && r.request().method() === 'PUT' && r.ok(),
  );
  await page.getByRole('button', { name: 'Save layout', exact: true }).click();
  expect((await resumed).request().postDataJSON().expected_updated_at).toBe(
    (await saved.json()).updated_at,
  );
});
