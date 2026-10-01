// @vitest-environment happy-dom
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { act, mount } from '../test-dom';
import type { RecordRead } from '../utils/types';

const deleted = vi.fn(async () => undefined);
const restored = vi.fn(async () => undefined);
const purged = vi.fn(async () => undefined);
const reload = vi.fn();
const success = vi.fn();

vi.mock('@inertiajs/react', () => ({
  router: { reload: (...args: unknown[]) => reload(...args) },
  Link: ({ children }: { children?: unknown }) => children,
}));
vi.mock('sonner', () => ({ toast: { success, error: vi.fn() } }));
vi.mock('../utils/api-records', () => ({
  deleteRecord: (...args: unknown[]) => deleted(...(args as [])),
  restoreRecord: (...args: unknown[]) => restored(...(args as [])),
  purgeRecord: (...args: unknown[]) => purged(...(args as [])),
}));

const { useRecordListMutations } = await import('./useRecordListMutations');

function fakeT(key: string, opts?: Record<string, unknown>): string {
  return (opts?.defaultValue as string) ?? key;
}

function record(overrides: Partial<RecordRead> = {}): RecordRead {
  return { uuid: 'r1', type_key: 'book', is_deleted: false, ...overrides } as RecordRead;
}

type Hook = ReturnType<typeof useRecordListMutations>;

function Probe({ onRender }: { onRender: (hook: Hook) => void }) {
  onRender(useRecordListMutations('book', fakeT));
  return null;
}

describe('useRecordListMutations — U4/U9: every row mutation reloads and says what happened', () => {
  beforeEach(() => {
    deleted.mockClear();
    restored.mockClear();
    purged.mockClear();
    reload.mockClear();
    success.mockClear();
  });

  it('handleDelete calls deleteRecord, reloads records, and raises the undo-able trash toast', async () => {
    let hook!: Hook;
    const view = await mount(<Probe onRender={(h) => (hook = h)} />);
    await act(async () => {
      await hook.handleDelete(record());
    });
    expect(deleted).toHaveBeenCalledWith('book', 'r1');
    expect(reload).toHaveBeenCalledWith({ only: ['records'] });
    expect(success).toHaveBeenCalledWith('Moved to the Trash', expect.anything());
    await view.unmount();
  });

  it('handleRestore calls restoreRecord, reloads, and raises a plain restored toast', async () => {
    let hook!: Hook;
    const view = await mount(<Probe onRender={(h) => (hook = h)} />);
    await act(async () => {
      await hook.handleRestore(record({ is_deleted: true }));
    });
    expect(restored).toHaveBeenCalledWith('book', 'r1');
    expect(reload).toHaveBeenCalledWith({ only: ['records'] });
    expect(success).toHaveBeenCalledWith('Record restored');
    await view.unmount();
  });

  it('handlePurge calls purgeRecord, reloads, and raises a plain purged toast', async () => {
    let hook!: Hook;
    const view = await mount(<Probe onRender={(h) => (hook = h)} />);
    await act(async () => {
      await hook.handlePurge(record({ is_deleted: true }));
    });
    expect(purged).toHaveBeenCalledWith('book', 'r1');
    expect(reload).toHaveBeenCalledWith({ only: ['records'] });
    expect(success).toHaveBeenCalledWith('Deleted permanently');
    await view.unmount();
  });
});
