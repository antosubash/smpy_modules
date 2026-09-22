// @vitest-environment happy-dom
import { describe, expect, it, vi } from 'vitest';

import { click, mount } from '../../test-dom';
import type { DryRunReport } from '../../utils/types';

const { SchemaConflictPanel } = await import('./SchemaConflictPanel');

function report(overrides: Partial<DryRunReport> = {}): DryRunReport {
  return {
    checked: 12,
    failing: 12,
    sample: [],
    orphaned_conflicts: {},
    clean: false,
    ...overrides,
  } as DryRunReport;
}

describe('SchemaConflictPanel — U3: "Apply anyway" discloses that its count spans the Trash', () => {
  it('renders nothing when there is neither a report nor a conflict', async () => {
    const view = await mount(
      <SchemaConflictPanel
        report={null}
        conflicts={null}
        pending={false}
        onForce={vi.fn(async () => undefined)}
        onOrphaned={vi.fn(async () => undefined)}
      />,
    );
    expect(view.host.innerHTML).toBe('');
    await view.unmount();
  });

  it('says the count includes trashed records, on both the button and the dialog copy', async () => {
    const view = await mount(
      <SchemaConflictPanel
        report={report()}
        conflicts={null}
        pending={false}
        onForce={vi.fn(async () => undefined)}
        onOrphaned={vi.fn(async () => undefined)}
      />,
    );
    // `report.failing` (like the hub's `invalid_record_count` badge it will
    // be compared against a moment later) scans live and trashed records
    // alike, and this is the one screen that says so, rather than just
    // stating a number the hub's own live-only count will then disagree
    // with (U3).
    const button = view.button('Apply anyway');
    expect(button?.textContent).toContain('including trashed');

    await click(button);
    expect(document.querySelector('[data-slot="alert-dialog-description"]')?.textContent).toContain(
      'including trashed',
    );
    await view.unmount();
  });
});
