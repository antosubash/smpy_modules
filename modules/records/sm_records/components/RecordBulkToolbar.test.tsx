// @vitest-environment happy-dom
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { click, mount } from '../test-dom';

const { RecordBulkToolbar } = await import('./RecordBulkToolbar');

/** Radix's AlertDialog renders into a body portal, so the confirm button is
 *  found there right after the trigger that opened it — the pattern
 *  `RecordRowAction.test.tsx` already uses. */
function confirmButton(): HTMLElement | null {
  return document.querySelector('[data-slot="alert-dialog-action"]');
}

function labels(host: HTMLElement): string[] {
  return Array.from(host.querySelectorAll('button')).map((el) => el.textContent ?? '');
}

describe('RecordBulkToolbar — the actions that mean something for this view', () => {
  beforeEach(() => {
    document.body.innerHTML = '';
  });

  it('is not there at all with nothing selected', async () => {
    const view = await mount(
      <RecordBulkToolbar count={0} trashed={false} onRun={vi.fn()} onClear={vi.fn()} />,
    );
    expect(view.find('[data-testid="records-bulk-toolbar"]')).toBeNull();
  });

  it('offers Trash, Publish and Unpublish on the live list — and neither trash action', async () => {
    const view = await mount(
      <RecordBulkToolbar count={3} trashed={false} onRun={vi.fn()} onClear={vi.fn()} />,
    );
    expect(view.find('[data-testid="records-bulk-trash"]')).not.toBeNull();
    expect(view.find('[data-testid="records-bulk-publish"]')).not.toBeNull();
    expect(view.find('[data-testid="records-bulk-unpublish"]')).not.toBeNull();
    // Restoring a live record and purging one are refusals the server would
    // have to spell out — the UI does not ask for them.
    expect(view.find('[data-testid="records-bulk-restore"]')).toBeNull();
    expect(view.find('[data-testid="records-bulk-purge"]')).toBeNull();
  });

  it('offers Restore and Delete permanently in the Trash view, and nothing else', async () => {
    const view = await mount(
      <RecordBulkToolbar count={2} trashed onRun={vi.fn()} onClear={vi.fn()} />,
    );
    expect(view.find('[data-testid="records-bulk-restore"]')).not.toBeNull();
    expect(view.find('[data-testid="records-bulk-purge"]')).not.toBeNull();
    expect(view.find('[data-testid="records-bulk-trash"]')).toBeNull();
    expect(view.find('[data-testid="records-bulk-publish"]')).toBeNull();
    expect(view.find('[data-testid="records-bulk-unpublish"]')).toBeNull();
  });

  it('runs an action only once its confirmation is confirmed', async () => {
    const onRun = vi.fn(async () => undefined);
    const view = await mount(
      <RecordBulkToolbar count={4} trashed={false} onRun={onRun} onClear={vi.fn()} />,
    );

    await click(view.find('[data-testid="records-bulk-trash"]'));
    // A dialog opened and nothing has happened yet: the count in it is
    // `utils/bulk-copy`'s, asserted there with interpolation applied.
    expect(onRun).not.toHaveBeenCalled();
    expect(confirmButton()).not.toBeNull();

    await click(confirmButton());
    expect(onRun).toHaveBeenCalledWith('trash');
  });

  it('clears the selection without a confirmation — nothing is destroyed', async () => {
    const onClear = vi.fn();
    const view = await mount(
      <RecordBulkToolbar count={4} trashed={false} onRun={vi.fn()} onClear={onClear} />,
    );
    await click(view.find('[data-testid="records-bulk-clear"]'));
    expect(onClear).toHaveBeenCalled();
  });

  it('disables its actions while one is in flight rather than disappearing', async () => {
    const view = await mount(
      <RecordBulkToolbar count={4} trashed={false} pending onRun={vi.fn()} onClear={vi.fn()} />,
    );
    expect(view.find<HTMLButtonElement>('[data-testid="records-bulk-trash"]')?.disabled).toBe(true);
    // The count stays on screen while the request runs.
    expect(view.find('[data-testid="records-bulk-count"]')).not.toBeNull();
    expect(labels(view.host).join(' ')).not.toBe('');
  });
});
