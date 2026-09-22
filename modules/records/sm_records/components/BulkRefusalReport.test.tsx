// @vitest-environment happy-dom
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { click, mount } from '../test-dom';
import type { BulkReport } from '../utils/api-records';

const { BulkRefusalReport } = await import('./BulkRefusalReport');

function report(overrides: Partial<BulkReport> = {}): BulkReport {
  return {
    action: 'trash',
    requested: 3,
    failed: [
      { uuid: 'aaa', status: 409, message: '2 record(s) still reference aaa' },
      { uuid: 'bbb', status: 404, message: "no product record with uuid 'bbb'" },
    ],
    ...overrides,
  };
}

describe('BulkRefusalReport — the refusal an operator can act on', () => {
  beforeEach(() => {
    document.body.innerHTML = '';
  });

  it('lists every failing record with the reason the server gave', async () => {
    const view = await mount(
      <BulkRefusalReport report={report()} records={[]} onDeselect={vi.fn()} onDismiss={vi.fn()} />,
    );

    const items = view.all('[data-testid="records-bulk-refusal-list"] li');
    expect(items).toHaveLength(2);
    expect(items[0].textContent).toContain('aaa');
    expect(items[0].textContent).toContain('still reference');
    expect(items[1].textContent).toContain('bbb');
    expect(items[1].textContent).toContain('no product record');
  });

  it('is announced, not merely drawn', async () => {
    const view = await mount(
      <BulkRefusalReport report={report()} records={[]} onDeselect={vi.fn()} onDismiss={vi.fn()} />,
    );
    expect(view.find('[data-testid="records-bulk-refusal"]')?.getAttribute('role')).toBe('alert');
  });

  it('deselects exactly the uuids it named, and nothing else', async () => {
    const onDeselect = vi.fn();
    const onDismiss = vi.fn();
    const view = await mount(
      <BulkRefusalReport
        report={report()}
        records={[]}
        onDeselect={onDeselect}
        onDismiss={onDismiss}
      />,
    );

    await click(view.button('Deselect'));

    expect(onDeselect).toHaveBeenCalledWith(['aaa', 'bbb']);
    // And the panel goes: what it was telling the operator to do is done.
    expect(onDismiss).toHaveBeenCalled();
  });

  it('can be dismissed without touching the selection', async () => {
    const onDeselect = vi.fn();
    const onDismiss = vi.fn();
    const view = await mount(
      <BulkRefusalReport
        report={report()}
        records={[]}
        onDeselect={onDeselect}
        onDismiss={onDismiss}
      />,
    );

    await click(view.button('Dismiss'));

    expect(onDismiss).toHaveBeenCalled();
    expect(onDeselect).not.toHaveBeenCalled();
  });
});

describe('BulkRefusalReport — U1: names a refused record by its title, not just its uuid', () => {
  beforeEach(() => {
    document.body.innerHTML = '';
  });

  it('shows the title (and the short uuid as a detail) for a refused row that is on the page', async () => {
    const view = await mount(
      <BulkRefusalReport
        report={report()}
        records={[
          { uuid: 'aaa', display_title: 'Tag 01' },
          { uuid: 'bbb', display_title: 'Tag 02' },
        ]}
        onDeselect={vi.fn()}
        onDismiss={vi.fn()}
      />,
    );
    const items = view.all('[data-testid="records-bulk-refusal-list"] li');
    expect(items[0].textContent).toContain('Tag 01');
    expect(items[0].textContent).toContain('still reference');
    expect(items[1].textContent).toContain('Tag 02');
  });

  it('falls back to the uuid for a refused row that is not on this page', async () => {
    const view = await mount(
      <BulkRefusalReport
        report={report()}
        records={[{ uuid: 'bbb', display_title: 'Tag 02' }]}
        onDeselect={vi.fn()}
        onDismiss={vi.fn()}
      />,
    );
    const items = view.all('[data-testid="records-bulk-refusal-list"] li');
    // 'aaa' has no match in `records` — a blocker uuid can equally well name
    // a related record of a *different* type, which is never on this page.
    expect(items[0].textContent).toContain('aaa');
    expect(items[1].textContent).toContain('Tag 02');
  });
});
