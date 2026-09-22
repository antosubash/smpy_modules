import { describe, expect, it, vi } from 'vitest';

const success = vi.fn();
const error = vi.fn();
vi.mock('sonner', () => ({ toast: { success, error } }));
vi.mock('@inertiajs/react', () => ({ Link: ({ children }: { children?: unknown }) => children }));

const { trashToast } = await import('./trashToast');

function fakeT(key: string, opts?: Record<string, unknown>): string {
  return (opts?.defaultValue as string) ?? key;
}

/** The `action.onClick` sonner was handed, for the last toast raised. */
function undoHandler(): () => void {
  const options = success.mock.calls.at(-1)?.[1] as { action: { onClick: () => void } };
  return options.action.onClick;
}

describe('trashToast — R5: a refused Undo is announced, not swallowed', () => {
  it('surfaces the rejection through toast.error', async () => {
    success.mockClear();
    error.mockClear();
    trashToast(fakeT, {
      typeKey: 'book',
      // The real 409: the slug this record still claims was taken while it
      // sat in the Trash.
      onUndo: () => Promise.reject(new Error('slug already in use')),
    });
    undoHandler()();
    // The catch runs on the microtask queue the rejection settles on.
    await Promise.resolve();
    await Promise.resolve();
    expect(error).toHaveBeenCalledWith('slug already in use');
  });

  it('says nothing extra when the undo works', async () => {
    success.mockClear();
    error.mockClear();
    const restore = vi.fn(async () => ({}));
    trashToast(fakeT, { typeKey: 'book', onUndo: restore });
    undoHandler()();
    await Promise.resolve();
    await Promise.resolve();
    expect(restore).toHaveBeenCalledOnce();
    expect(error).not.toHaveBeenCalled();
  });
});
