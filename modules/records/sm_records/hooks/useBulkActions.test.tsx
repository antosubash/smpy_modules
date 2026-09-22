// @vitest-environment happy-dom
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { act, mount } from '../test-dom';
import { ApiError } from '../utils/api';
import type { BulkReport } from '../utils/api-records';

vi.mock('@inertiajs/react', () => ({ router: { reload: vi.fn() } }));

const bulkRecords = vi.fn();
const emptyTrash = vi.fn();
vi.mock('../utils/api-records', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../utils/api-records')>();
  return {
    ...actual,
    bulkRecords: (...args: unknown[]) => bulkRecords(...args),
    emptyTrash: (...args: unknown[]) => emptyTrash(...args),
  };
});

const { useBulkActions } = await import('./useBulkActions');

function fakeT(_key: string, opts: { defaultValue: string }): string {
  return opts.defaultValue;
}

type Hook = ReturnType<typeof useBulkActions>;

function Probe({ resetKey, onReady }: { resetKey: string; onReady: (hook: Hook) => void }) {
  const hook = useBulkActions('qa_v3_tag', fakeT, {
    uuids: ['aaa', 'bbb'],
    onDone: () => {},
    resetKey,
  });
  onReady(hook);
  return null;
}

function refusal(): BulkReport {
  return {
    action: 'trash',
    requested: 4,
    failed: [{ uuid: 'aaa', status: 409, message: '1 record(s) still reference aaa' }],
  };
}

describe('useBulkActions — U2: a refusal report goes with the page it was about', () => {
  beforeEach(() => {
    document.body.innerHTML = '';
    bulkRecords.mockReset();
    emptyTrash.mockReset();
  });

  it('clears the report once resetKey changes — a page/filter/sort change or a reload', async () => {
    let current: Hook | null = null;
    const view = await mount(<Probe resetKey="a,b,c,d" onReady={(h) => (current = h)} />);

    bulkRecords.mockRejectedValue(new ApiError(409, { report: refusal() }, 'refused'));
    await act(async () => {
      await (current as unknown as Hook).run('trash');
    });
    expect((current as unknown as Hook).report).not.toBeNull();

    // Same resetKey again (an unrelated re-render): the report survives.
    await view.render(<Probe resetKey="a,b,c,d" onReady={(h) => (current = h)} />);
    expect((current as unknown as Hook).report).not.toBeNull();

    // The page underneath changed — a filter, a sort, or the reload the
    // refused action itself could trigger on a retry.
    await view.render(<Probe resetKey="e,f" onReady={(h) => (current = h)} />);
    expect((current as unknown as Hook).report).toBeNull();
    await view.unmount();
  });

  it('does not clear a report that was set before the very first render settled', async () => {
    // A pure mount is not itself a "reset" — the effect runs once on mount
    // like any other, and must not race a refusal that arrives in the same
    // tick and wipe it back out.
    let current: Hook | null = null;
    const view = await mount(<Probe resetKey="a,b" onReady={(h) => (current = h)} />);
    bulkRecords.mockRejectedValue(new ApiError(409, { report: refusal() }, 'refused'));
    await act(async () => {
      await (current as unknown as Hook).run('trash');
    });
    expect((current as unknown as Hook).report).not.toBeNull();
    await view.unmount();
  });
});
