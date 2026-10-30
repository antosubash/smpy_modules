// @vitest-environment happy-dom
import { describe, expect, it, vi } from 'vitest';

import { job } from '../../page-tests/support';
import { click, mount } from '../../page-tests/test-dom';
import { FAILURES_SHOWN, JobRow } from './JobRow';

vi.mock('@inertiajs/react', async () => (await import('../../page-tests/support')).inertiaMock());

const row = (item: number, extra: Record<string, unknown> = {}) => ({
  code: 'http_403',
  item,
  status: 403,
  reason: 'Forbidden',
  where: 'upload.wikimedia.org/a.jpg',
  at: '2026-10-29T10:00:00Z',
  ...extra,
});

async function render(errors: unknown[], failed: number) {
  return mount(
    <JobRow
      job={job({ kind: 'geojson_url', failed_count: failed, done_count: 0, errors } as never)}
      canEdit={false}
      onControl={async () => {}}
      onRemove={async () => {}}
    />,
  );
}

describe('an import job says why rows failed (QA retest 2, R2-IMPORT)', () => {
  it('lists the first failed rows with their HTTP answer and place, then how many more', async () => {
    const rows = Array.from({ length: FAILURES_SHOWN + 2 }, (_, i) => row(i));
    const view = await render(
      [...rows, row(99, { code: 'unsupported_type', status: undefined })],
      12,
    );
    const list = view.find('[data-testid="images-import-failures"]') as HTMLDetailsElement;
    expect(list).not.toBeNull();
    await click(list.querySelector('summary'));
    const items = view.all('[data-testid="images-import-failure"]');
    expect(items).toHaveLength(FAILURES_SHOWN);
    expect(items[0].textContent).toBe('Row 1: HTTP 403 Forbidden · upload.wikimedia.org/a.jpg');
    expect(view.find('[data-testid="images-import-failures-more"]')?.textContent).toBe(
      `…and ${12 - FAILURES_SHOWN} more`,
    );
    await view.unmount();
  });

  it('names a non-HTTP failure by its label', async () => {
    const view = await render([{ code: 'unsupported_type', item: 4, at: 'x' }], 1);
    await click(view.find('[data-testid="images-import-failures"] summary'));
    expect(view.find('[data-testid="images-import-failure"]')?.textContent).toMatch(/^Row 5: /);
    expect(view.find('[data-testid="images-import-failure"]')?.textContent).not.toContain(
      'unsupported_type',
    );
    expect(view.find('[data-testid="images-import-failures-more"]')).toBeNull();
    await view.unmount();
  });

  it('keeps job-level errors out of the row list', async () => {
    const view = await render([{ code: 'stalled', at: 'x' }], 0);
    expect(view.find('[data-testid="images-import-failures"]')).toBeNull();
    await view.unmount();
  });
});
