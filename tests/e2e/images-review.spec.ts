import { execFileSync } from 'node:child_process';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

import { expect, test } from '@playwright/test';

import { login } from './helpers';

/**
 * The review queue, end to end: two images carry seeded, unreviewed AI results
 * (no AI call - `seed_images_review.py` writes them as a finished run would);
 * one is accepted with the `a` key and one corrected in the form generated
 * from the prompt's output schema.
 *
 * Standalone: it creates its own collection and images, and relies on no
 * settings beyond the suite's (`start-test-server.sh`).
 */

const here = dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = resolve(here, '..', '..');
const fixture = (name: string) => resolve(REPO_ROOT, 'modules/images/tests/fixtures', name);

function seed(collectionId: string) {
  const database =
    process.env.SM_DATABASE_URL?.trim() ||
    `sqlite+aiosqlite:///${resolve(REPO_ROOT, 'host', 'test.db')}`;
  const out = execFileSync(
    'uv',
    ['run', 'python', 'tests/e2e/seed_images_review.py', collectionId],
    {
      cwd: REPO_ROOT,
      encoding: 'utf8',
      env: {
        ...process.env,
        SM_DATABASE_URL: database,
        SM_E2E_DATABASE: database,
        SM_SECRET_KEY: 'e2e-test-secret-key-not-for-production-use',
        SM_PROJECT_ROOT: REPO_ROOT,
        SM_BG_TASKS_TASK_ALWAYS_EAGER: 'true',
        SM_BG_TASKS_BROKER_URL: 'memory://',
        SM_BG_TASKS_RESULT_BACKEND: 'cache+memory://',
        SM_BG_TASKS_BROADCAST_INVALIDATIONS: 'false',
        SM_E2E_SEED: '1',
        SM_ENVIRONMENT: 'development',
      },
    },
  );
  return JSON.parse(out.trim().split('\n').at(-1) ?? '{}') as { prompt: string; results: number[] };
}

test('accept one AI result with the keyboard and correct another with the generated form', async ({
  page,
}) => {
  await login(page);

  const name = `Review ${Date.now().toString(36)}`;
  await page.goto('/admin/images/');
  await page.getByTestId('images-new-collection').click();
  await page.getByLabel('Name').fill(name);
  await page.getByRole('button', { name: 'Create collection' }).click();
  await page.waitForURL(/\/admin\/images\/[0-9a-f-]{36}$/);
  const collectionUrl = new URL(page.url()).pathname;
  const collectionId = collectionUrl.split('/').at(-1) ?? '';
  await page
    .getByTestId('images-upload-input')
    .setInputFiles([fixture('rotated.jpg'), fixture('geotagged.jpg')]);
  await expect(page.getByTestId('images-gallery-tile')).toHaveCount(2);

  const seeded = seed(collectionId);
  expect(seeded.results).toHaveLength(2);

  // The collection page offers the queue to an editor.
  await page.reload();
  await page.getByTestId('images-open-review').click();
  await page.waitForURL(`${collectionUrl}/review`);
  const panel = page.getByTestId('images-review-panel');
  await expect(panel).toBeVisible();
  await expect(page.getByTestId('images-review-position')).toContainText('1 of 2');
  await expect(panel).toContainText('geotagged.jpg');
  await expect(panel).toContainText('Tree count');

  // `a` accepts the first; the second moves up.
  await page.keyboard.press('a');
  await expect(panel).toContainText('rotated.jpg');
  await expect(panel).toHaveAttribute('data-result-id', String(seeded.results[1]));

  // `e` opens the form built from the schema; typing `a` in it is not a shortcut.
  await page.keyboard.press('e');
  const count = page.getByTestId('images-review-field-count');
  await expect(count).toHaveValue('5');
  await count.fill('8');
  await page.getByTestId('images-review-field-species').selectOption('oak');
  await page.getByTestId('images-review-save').click();
  await expect(page.getByTestId('images-review-empty')).toBeVisible();

  // Both left the unreviewed queue; the API holds the verdicts and the values.
  const done = await page.request.get(`/api/images/collections/${collectionId}/review?status=all`);
  expect(done.status()).toBe(200);
  const items = (await done.json()).items as {
    id: number;
    review_status: string;
    reviewed_data: Record<string, unknown>;
    result_data: Record<string, unknown>;
  }[];
  const byId = new Map(items.map((i) => [i.id, i]));
  const accepted = byId.get(seeded.results[0]);
  const corrected = byId.get(seeded.results[1]);
  expect(accepted?.review_status).toBe('accepted');
  expect(accepted?.reviewed_data).toEqual({ count: 3, species: 'oak' });
  expect(corrected?.review_status).toBe('corrected');
  expect(corrected?.reviewed_data).toEqual({ count: 8, species: 'oak' });
  expect(corrected?.result_data).toEqual({ count: 5, species: 'pine' });

  // The status filter finds them again.
  await page.getByTestId('images-review-status-filter').selectOption('corrected');
  await expect(page.getByTestId('images-review-panel')).toContainText('rotated.jpg');
  await expect(page.getByTestId('images-review-status')).toHaveText('Corrected');
});
