// @vitest-environment happy-dom
import { beforeAll, describe, expect, it, vi } from 'vitest';

import { mount } from '../test-dom';
import { loadRecordsCatalog } from '../utils/media-test-support';
import { RecordPagination } from './RecordPagination';

beforeAll(() => loadRecordsCatalog());

type Props = Parameters<typeof RecordPagination>[0];

/** Page 2 of a listing whose count stopped at 32 (`max_count`). */
const capped = (overrides: Partial<Props>): Props => ({
  page: 2,
  pageSize: 25,
  total: 32,
  capped: true,
  itemCount: 25,
  nextCursor: 'NEXT',
  onGo: vi.fn(),
  onContinue: vi.fn(),
  onPageSize: vi.fn(),
  ...overrides,
});

const info = (view: Awaited<ReturnType<typeof mount>>) =>
  Array.from(view.host.querySelectorAll('span'), (s) => s.textContent).filter(Boolean);

/**
 * Review 4, ux F12: the cap's last page read "Showing 26–40 of 32+" with
 * Next and Last disabled — a range past its own total, on a page that is
 * known to be the end. The server hands out a cursor for every full page,
 * so a capped page without one is short and the count is its last row.
 */
describe('RecordPagination — the count once the capped list is known to end', () => {
  it('says the real count on a short last page', async () => {
    const view = await mount(<RecordPagination {...capped({ itemCount: 15, nextCursor: null })} />);
    expect(info(view)).toContain('Showing 26–40 of 40');
    expect(view.find('[data-testid="records-page-position"]')?.textContent).toBe('Page 2 of 2');
    expect(view.host.querySelector('[title]')).toBeNull();
    await view.unmount();
  });

  it('keeps "32+" while more may follow — a full page always has a cursor', async () => {
    const view = await mount(<RecordPagination {...capped({})} />);
    expect(info(view)).toContain('Showing 26–50 of 32+');
    expect(view.find('[data-testid="records-page-position"]')?.textContent).toBe('Page 2');
    await view.unmount();
  });
});
