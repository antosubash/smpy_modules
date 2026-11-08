import { expect, test } from '@playwright/test';
import { login, moduleCsrfHeader, uniqueSlug } from './helpers';

test('analytics opt-in, public and app tracking, events, unknown locations and deletion', async ({
  page,
}) => {
  await login(page);
  const csrf = await moduleCsrfHeader(page, '/pagebuilder/');
  const slug = uniqueSlug('analytics');
  const created = await page.request.post('/api/pagebuilder/pages', {
    headers: csrf,
    data: {
      title: `Analytics ${slug}`,
      slug,
      draft_data: { root: { props: { title: slug, width: 'full' } }, content: [], zones: {} },
    },
  });
  expect(created.status(), await created.text()).toBe(201);
  const content = (await created.json()) as { id: number };
  const published = await page.request.post(`/api/pagebuilder/pages/${content.id}/publish`, {
    headers: csrf,
    data: {},
  });
  expect(published.ok(), await published.text()).toBeTruthy();
  const ids: string[] = [];
  try {
    await page.goto('/analytics/');
    await expect(page.getByRole('heading', { name: 'Analytics', exact: true })).toBeVisible();
    await expect(
      page.getByRole('button', { name: /^(Manage property|New property)$/ }),
    ).toBeVisible();
    if (await page.getByRole('button', { name: 'Manage property', exact: true }).isVisible())
      await page.getByRole('button', { name: 'Manage property', exact: true }).click();
    await page.getByRole('button', { name: 'New property', exact: true }).click();
    const name = `Public ${slug}`;
    await page.getByLabel('Name', { exact: true }).fill(name);
    await page.getByLabel('Tracked routes', { exact: true }).fill(`/p/${slug}`);
    await page.getByLabel('Custom events', { exact: true }).fill('download: format');
    await expect(page.getByLabel('Enable tracking', { exact: true })).not.toBeChecked();
    await page.getByRole('button', { name: 'Save property', exact: true }).click();
    await expect(page.getByLabel('Property', { exact: true })).toContainText(name);
    const properties = (await (await page.request.get('/api/analytics/properties')).json()) as {
      id: string;
      name: string;
    }[];
    const publicId = properties.find((property) => property.name === name)?.id;
    expect(publicId).toBeTruthy();
    ids.push(publicId as string);
    const disabled = (await (await page.request.get('/api/analytics/config')).json()) as {
      properties: { id: string }[];
    };
    expect(disabled.properties.some((property) => property.id === publicId)).toBe(false);
    await page.getByRole('button', { name: 'Manage property', exact: true }).click();
    await page.getByRole('button', { name: 'Edit', exact: true }).click();
    await page.getByLabel('Enable tracking', { exact: true }).check();
    await page.getByRole('button', { name: 'Save property', exact: true }).click();
    await expect(page.getByText('Tracking enabled', { exact: true })).toBeVisible();
    const pageview = page.waitForResponse(
      (response) =>
        response.url().endsWith('/api/analytics/collect') && response.request().method() === 'POST',
    );
    await page.goto(`/p/${slug}?token=must-not-be-stored`);
    expect((await pageview).status()).toBe(204);
    const eventStatus = await page.evaluate(async (propertyId) => {
      const response = await fetch('/api/analytics/collect', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          property_id: propertyId,
          event_id: crypto.randomUUID(),
          kind: 'event',
          path: window.location.pathname,
          name: 'download',
          properties: { format: 'pdf' },
        }),
      });
      return response.status;
    }, publicId);
    expect(eventStatus).toBe(204);
    await page.goto('/analytics/');
    await page.getByLabel('Property', { exact: true }).selectOption(publicId as string);
    await expect(
      page.getByRole('heading', { name: 'Visitor locations', exact: true }),
    ).toBeVisible();
    await expect(page.getByText('download', { exact: true }).first()).toBeVisible();
    await page.getByRole('button', { name: 'Filters', exact: true }).click();
    await page.getByLabel('Country', { exact: true }).selectOption('__unknown__');
    await page.getByRole('button', { name: 'Apply', exact: true }).click();
    await expect(
      page.getByRole('button', { name: 'Remove Country filter', exact: true }),
    ).toContainText('Unknown');
    await expect(
      page.getByRole('heading', { name: 'Visitor locations', exact: true }),
    ).toBeVisible();
    const report = await (
      await page.request.get(`/api/analytics/properties/${publicId}/report?country=`)
    ).json();
    expect(report.totals.pageviews).toBeGreaterThanOrEqual(1);
    expect(report.totals.events).toBe(1);
    expect(
      report.breakdowns.path.some((row: { value: string }) => row.value.includes('token=')),
    ).toBe(false);

    await page.getByRole('button', { name: 'Manage property', exact: true }).click();
    await page.getByRole('button', { name: 'New property', exact: true }).click();
    const appName = `App ${slug}`;
    await page.getByLabel('Name', { exact: true }).fill(appName);
    await page.getByLabel('Tracking type', { exact: true }).selectOption('application');
    await page.getByLabel('Tracked routes', { exact: true }).fill('/pagebuilder/:id/edit');
    await page.getByLabel('Enable tracking', { exact: true }).check();
    await page.getByRole('button', { name: 'Save property', exact: true }).click();
    await expect(page.getByLabel('Property', { exact: true })).toContainText(appName);
    const nextProperties = (await (await page.request.get('/api/analytics/properties')).json()) as {
      id: string;
      name: string;
    }[];
    const appId = nextProperties.find((property) => property.name === appName)?.id as string;
    ids.push(appId);
    const appView = page.waitForResponse(
      (response) =>
        response.url().endsWith('/api/analytics/collect') && response.request().method() === 'POST',
    );
    await page.goto(`/pagebuilder/${content.id}/edit`);
    expect((await appView).status()).toBe(204);
    const appReport = await (
      await page.request.get(`/api/analytics/properties/${appId}/report`)
    ).json();
    expect(appReport.breakdowns.path).toEqual(
      expect.arrayContaining([expect.objectContaining({ value: '/pagebuilder/:id/edit' })]),
    );
    await page.goto('/analytics/');
    await page.getByLabel('Property', { exact: true }).selectOption(appId);
    await page.getByRole('button', { name: 'Manage property', exact: true }).click();
    await page.getByRole('button', { name: 'Delete property', exact: true }).click();
    const confirmation = page.getByRole('alertdialog');
    await expect(confirmation).toContainText('permanently deletes');
    await confirmation.getByRole('button', { name: 'Delete property', exact: true }).click();
    await expect(confirmation).toHaveCount(0);
    expect((await page.request.get(`/api/analytics/properties/${appId}/report`)).status()).toBe(
      404,
    );
  } finally {
    for (const id of ids)
      await page.request.delete(`/api/analytics/properties/${id}`, { headers: csrf });
    await page.request.delete(`/api/pagebuilder/pages/${content.id}`, { headers: csrf });
  }
});
