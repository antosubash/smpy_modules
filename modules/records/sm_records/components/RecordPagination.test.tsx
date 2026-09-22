// @vitest-environment happy-dom
import { describe, expect, it, vi } from 'vitest';

import { mount } from '../test-dom';
import { RecordPagination } from './RecordPagination';

function pagination(loading: boolean) {
  return (
    <RecordPagination
      page={2}
      pageSize={25}
      total={100}
      capped={false}
      itemCount={25}
      loading={loading}
      onGo={vi.fn()}
      onPageSize={vi.fn()}
    />
  );
}

describe('RecordPagination — U12: the pager disables itself while a page change is in flight', () => {
  it('leaves First/Previous/Next/Last and the page-size select enabled when idle', async () => {
    const view = await mount(pagination(false));
    for (const label of ['First', 'Previous', 'Next', 'Last']) {
      expect((view.button(label) as HTMLButtonElement).disabled).toBe(false);
    }
    expect(view.find<HTMLSelectElement>('#records-page-size')?.disabled).toBe(false);
    await view.unmount();
  });

  it('disables every control while loading, on top of whatever First/Last already disable', async () => {
    const view = await mount(pagination(true));
    for (const label of ['First', 'Previous', 'Next', 'Last']) {
      expect((view.button(label) as HTMLButtonElement).disabled).toBe(true);
    }
    expect(view.find<HTMLSelectElement>('#records-page-size')?.disabled).toBe(true);
    await view.unmount();
  });
});
